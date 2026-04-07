"""Screen + audio recording orchestration for macOS.

Coordinates BlackHole, SwitchAudioSource, and ffmpeg to capture screen,
microphone, and system audio, then feeds the result into the existing
SlurpAI pipeline.
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

SLURPAI_DIR = Path.home() / ".slurpai"
SNAPSHOT_PATH = SLURPAI_DIR / "audio_snapshot.json"
SWIFT_SOURCE = Path(__file__).parent / "swift" / "audio_setup.swift"
SWIFT_BINARY = SLURPAI_DIR / "audio_setup"
DEVICE_NAME = "SlurpAI Multi-Output"

# Module-level ref so signal handlers can reach the ffmpeg process.
_ffmpeg_process: subprocess.Popen | None = None


# ---------------------------------------------------------------------------
# Prerequisite checking
# ---------------------------------------------------------------------------

def check_prerequisites() -> dict[str, bool]:
    """Check that all required tools are available.

    Returns a dict mapping tool name to availability.
    """
    results: dict[str, bool] = {}

    results["ffmpeg"] = shutil.which("ffmpeg") is not None
    results["SwitchAudioSource"] = shutil.which("SwitchAudioSource") is not None
    results["swiftc"] = shutil.which("swiftc") is not None

    # BlackHole requires SwitchAudioSource to detect
    if results["SwitchAudioSource"]:
        try:
            out = subprocess.run(
                ["SwitchAudioSource", "-a"],
                capture_output=True, text=True, timeout=5,
            )
            results["BlackHole 2ch"] = "BlackHole 2ch" in out.stdout
        except (subprocess.TimeoutExpired, OSError):
            results["BlackHole 2ch"] = False
    else:
        results["BlackHole 2ch"] = False

    return results


def check_multi_output_device() -> bool:
    """Return True if the SlurpAI Multi-Output device exists."""
    try:
        out = subprocess.run(
            ["SwitchAudioSource", "-a"],
            capture_output=True, text=True, timeout=5,
        )
        return DEVICE_NAME in out.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


# ---------------------------------------------------------------------------
# Setup phase
# ---------------------------------------------------------------------------

def compile_swift_helper() -> Path:
    """Compile the Swift audio setup helper. Returns the binary path."""
    SLURPAI_DIR.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [
            "swiftc", "-O",
            "-o", str(SWIFT_BINARY),
            str(SWIFT_SOURCE),
            "-framework", "CoreAudio",
            "-framework", "AudioToolbox",
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Swift compilation failed:\n{result.stderr.strip()}")

    return SWIFT_BINARY


def create_multi_output_device() -> None:
    """Run the compiled Swift helper to create the Multi-Output Device."""
    result = subprocess.run(
        [str(SWIFT_BINARY)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create Multi-Output Device:\n{result.stderr.strip()}")

    click.echo(result.stdout.strip())

    # Verify the device appeared
    if not check_multi_output_device():
        raise RuntimeError(
            "Multi-Output Device was created but does not appear in the device list. "
            "Try running 'slurpai record --setup' again."
        )


_INSTALL_HINTS = {
    "ffmpeg": "brew install ffmpeg",
    "SwitchAudioSource": "brew install switchaudio-osx",
    "swiftc": "xcode-select --install",
    "BlackHole 2ch": "brew install --cask blackhole-2ch",
}


def run_setup() -> None:
    """One-time setup: check prerequisites and create the Multi-Output Device."""
    prereqs = check_prerequisites()
    missing = {k: v for k, v in prereqs.items() if not v}

    if missing:
        click.echo("Missing prerequisites:", err=True)
        for name in missing:
            hint = _INSTALL_HINTS.get(name, "")
            click.echo(f"  {name} — install with: {hint}", err=True)
        sys.exit(1)

    if check_multi_output_device():
        click.echo(f"Already set up: '{DEVICE_NAME}' exists.")
        return

    click.echo("Compiling audio setup helper...")
    compile_swift_helper()

    click.echo("Creating Multi-Output Device...")
    create_multi_output_device()

    click.echo(f"\nSetup complete. Run: slurpai record --name <name>")


# ---------------------------------------------------------------------------
# Audio snapshot / restore (safety)
# ---------------------------------------------------------------------------

def snapshot_audio() -> str:
    """Save the current default output device to a snapshot file.

    Returns the device name.
    """
    result = subprocess.run(
        ["SwitchAudioSource", "-c"],
        capture_output=True, text=True, timeout=5,
    )
    device = result.stdout.strip()
    if not device:
        raise RuntimeError("Could not determine current audio output device.")

    SLURPAI_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "device": device,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
    }
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return device


def restore_audio(*, quiet: bool = False) -> None:
    """Restore audio output from the snapshot file.

    If quiet=True, swallow all errors (for use in atexit / signal handlers).
    """
    try:
        if not SNAPSHOT_PATH.exists():
            if not quiet:
                click.echo(
                    "No audio snapshot found. If your audio output is wrong, "
                    "open System Settings > Sound > Output and select your speakers."
                )
            return

        snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        device = snapshot["device"]

        subprocess.run(
            ["SwitchAudioSource", "-s", device],
            capture_output=True, text=True, timeout=5,
        )

        SNAPSHOT_PATH.unlink(missing_ok=True)

        if not quiet:
            click.echo(f"Audio output restored to: {device}")
    except Exception:
        if not quiet:
            raise


def check_stale_snapshot() -> str | None:
    """Check for a stale snapshot from a crashed previous recording.

    Returns the original device name if a stale snapshot is found, None otherwise.
    """
    if not SNAPSHOT_PATH.exists():
        return None

    try:
        snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        pid = snapshot.get("pid")

        if pid is not None:
            try:
                os.kill(pid, 0)  # Check if process is still running
                return None  # Process alive — concurrent recording, leave it
            except OSError:
                pass  # Process dead — stale snapshot

        return snapshot.get("device")
    except (json.JSONDecodeError, KeyError):
        # Corrupt snapshot — treat as stale, let restore handle it
        return None


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def _detect_microphone() -> str | None:
    """Auto-detect the built-in microphone name from avfoundation devices."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True, text=True, timeout=10,
        )
        # Device list is printed to stderr
        for line in result.stderr.splitlines():
            # Match lines like "[...] [2] MacBook Air Microphone"
            lower = line.lower()
            if "microphone" in lower and ("macbook" in lower or "built-in" in lower):
                # Extract the device name after the index
                idx = line.rfind("]")
                if idx != -1:
                    return line[idx + 1:].strip()
    except Exception:
        pass
    return None


def build_ffmpeg_cmd(output_path: Path) -> list[str]:
    """Build the ffmpeg avfoundation capture command."""
    mic_name = _detect_microphone()
    if not mic_name:
        raise RuntimeError(
            "Could not detect built-in microphone. "
            "Run `ffmpeg -f avfoundation -list_devices true -i \"\"` to check available devices."
        )

    return [
        "ffmpeg",
        # Screen capture + microphone in one avfoundation session
        "-f", "avfoundation",
        "-capture_cursor", "1",
        "-framerate", "5",
        "-i", f"Capture screen 0:{mic_name}",
        # System audio (via BlackHole) as separate session
        "-f", "avfoundation",
        "-i", ":BlackHole 2ch",
        # Merge mic (mono, from input 0) + system audio (stereo, from input 1)
        # into a stereo downmix: mic on both channels + system L/R
        "-filter_complex",
        "[0:a][1:a]amerge=inputs=2,pan=stereo|c0=c0+c1|c1=c0+c2[a]",
        "-map", "0:v",
        "-map", "[a]",
        # Video: low-overhead screen recording
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "28",
        # Audio: AAC 128k
        "-c:a", "aac",
        "-b:a", "128k",
        # Fast-start for playback
        "-movflags", "+faststart",
        str(output_path),
    ]


def _graceful_shutdown(signum, _frame):
    """Signal handler: stop ffmpeg cleanly, restore audio, exit."""
    global _ffmpeg_process
    if _ffmpeg_process and _ffmpeg_process.poll() is None:
        try:
            _ffmpeg_process.stdin.write(b"q")
            _ffmpeg_process.stdin.flush()
            _ffmpeg_process.wait(timeout=5)
        except Exception:
            _ffmpeg_process.kill()

    restore_audio(quiet=True)
    sys.exit(128 + signum)


def run_recording(output_path: Path) -> Path:
    """Run the screen + audio recording. Returns the output file path."""
    global _ffmpeg_process

    # Safety: register cleanup handlers
    atexit.register(restore_audio, quiet=True)
    signal.signal(signal.SIGINT, _graceful_shutdown)
    signal.signal(signal.SIGTERM, _graceful_shutdown)
    signal.signal(signal.SIGHUP, _graceful_shutdown)

    # Snapshot current audio and switch to Multi-Output Device
    original_device = snapshot_audio()
    click.echo(f"Current audio output: {original_device}")

    subprocess.run(
        ["SwitchAudioSource", "-s", DEVICE_NAME],
        capture_output=True, text=True, timeout=5, check=True,
    )
    click.echo(f"Switched audio output to: {DEVICE_NAME}")

    click.echo(
        "\nMake sure Terminal has Screen Recording permission "
        "(System Settings > Privacy & Security > Screen Recording).\n"
    )

    # Start ffmpeg
    cmd = build_ffmpeg_cmd(output_path)
    _ffmpeg_process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    click.echo("Recording — press q to stop...\n")

    try:
        # Read single characters from stdin to catch 'q'
        import termios
        import tty

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while True:
                ch = sys.stdin.read(1)
                if ch.lower() == "q":
                    break
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    except Exception:
        # Fallback: just wait for ffmpeg to finish (e.g. in non-TTY context)
        _ffmpeg_process.wait()

    # Stop ffmpeg cleanly
    if _ffmpeg_process.poll() is None:
        _ffmpeg_process.stdin.write(b"q")
        _ffmpeg_process.stdin.flush()
        try:
            _ffmpeg_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _ffmpeg_process.kill()
            _ffmpeg_process.wait()

    # Capture stderr before releasing the process
    ffmpeg_stderr = ""
    if _ffmpeg_process.stderr:
        ffmpeg_stderr = _ffmpeg_process.stderr.read().decode(errors="replace")
    _ffmpeg_process = None

    # Restore audio
    restore_audio()

    # Verify output
    if not output_path.exists() or output_path.stat().st_size == 0:
        msg = f"Recording failed — output file is missing or empty: {output_path}"
        if ffmpeg_stderr:
            # Show the last 20 lines of ffmpeg output for diagnosis
            tail = "\n".join(ffmpeg_stderr.strip().splitlines()[-20:])
            msg += f"\n\nffmpeg output:\n{tail}"
        raise RuntimeError(msg)

    size_mb = output_path.stat().st_size / (1024 * 1024)
    click.echo(f"\nRecording saved: {output_path} ({size_mb:.1f} MB)")

    return output_path


def record_command(
    *,
    name: str,
    output_dir: str | None,
    no_process: bool,
    backend: str,
    frame_interval: int,
    language: str,
) -> None:
    """Top-level recording orchestrator called by the CLI."""
    from .ffmpeg import check_ffmpeg

    if not check_ffmpeg():
        click.echo("Error: ffmpeg not found. Install it: brew install ffmpeg", err=True)
        sys.exit(1)

    if not check_multi_output_device():
        click.echo(
            f"Error: '{DEVICE_NAME}' not found. Run setup first:\n"
            f"  slurpai record --setup",
            err=True,
        )
        sys.exit(1)

    # Auto-recover from a previous crashed session
    stale_device = check_stale_snapshot()
    if stale_device:
        click.echo(f"Recovering audio from previous crashed session (restoring to: {stale_device})...")
        restore_audio(quiet=True)

    # Resolve output path
    base = Path(output_dir) if output_dir else Path.cwd()
    output_path = base / f"{name}.mp4"

    if output_path.exists():
        click.echo(f"Error: output file already exists: {output_path}", err=True)
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Record
    recording = run_recording(output_path)

    # Process through existing pipeline
    if no_process:
        click.echo("Skipping post-processing (--no-process).")
        return

    click.echo(f"\nProcessing recording: {recording.name}")
    from .process import process_file

    result = process_file(
        recording,
        backend=backend,
        frame_interval=frame_interval,
        language=language,
    )
    click.echo(f"Output: {result}")
