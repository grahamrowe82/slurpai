# Plan: `slurpai record` — Screen + Audio Recording

**Status:** Planning
**Author:** Graham Rowe
**Date:** April 2026

## Summary

Add a `record` subcommand to SlurpAI that captures screen, microphone, and system audio (e.g. a Teams call) on macOS, then feeds the recording into the existing SlurpAI pipeline for transcription and frame extraction.

**User experience:**

```bash
slurpai record --name "client-meeting"

# ✓ BlackHole detected
# ✓ Audio routing configured
# ✓ Recording — screen + mic + system audio
# Press q to stop...

# [user presses q]

# ✓ Recording saved (1.2 GB)
# ✓ Audio restored
# Processing...
# ✓ Transcript: client-meeting/transcript.txt
# ✓ Frames: client-meeting/frames/ (347 frames)
```

One command. No manual setup. Full cleanup on exit.

## Motivation

SlurpAI processes voice notes and videos after they've been recorded. But recording a meeting on macOS — with both sides of the audio — currently requires manually configuring OBS, BlackHole, and Audio MIDI Setup. This is error-prone and the setup doesn't persist reliably.

By integrating recording directly into SlurpAI, a consultant can go from "meeting starting" to "recording + transcript + frames" with a single command. The entire post-processing pipeline already exists.

## Architecture

### New files

| File | Purpose | Lines (est.) |
|---|---|---|
| `src/slurpai/macos_audio.py` | CoreAudio ctypes bindings — device discovery, Multi-Output Device lifecycle, output switching | ~170 |
| `src/slurpai/record.py` | Recording orchestration — prerequisites, setup, ffmpeg capture, teardown, pipeline handoff | ~120 |
| `cli.py` changes | Add `record` subcommand to Click group | ~30 |

### Dependencies

| Dependency | Type | Purpose |
|---|---|---|
| BlackHole 2ch | System (brew cask) | Virtual audio driver — makes system audio available as a recordable input |
| ffmpeg | System (existing) | Screen + audio capture via avfoundation, already a SlurpAI dependency |
| CoreAudio.framework | macOS system | Audio device management via ctypes — no pip package needed |
| CoreFoundation.framework | macOS system | CFString/CFDictionary for CoreAudio API calls — no pip package needed |

No new Python package dependencies. CoreAudio and CoreFoundation are accessed via ctypes from the system frameworks.

### Recording pipeline

```
slurpai record --name "meeting"
        │
        ▼
┌─────────────────────────────────┐
│  1. Prerequisites               │
│  ─────────────────              │
│  • ffmpeg on PATH?              │
│  • BlackHole 2ch installed?     │
│  • Screen Recording permission? │
└───────────┬─────────────────────┘
            ▼
┌─────────────────────────────────┐
│  2. Audio setup                 │
│  ──────────────                 │
│  • Snapshot current state       │
│  • Create Multi-Output Device   │
│  • Switch system output         │
│  • Register cleanup handlers    │
└───────────┬─────────────────────┘
            ▼
┌─────────────────────────────────┐
│  3. Record                      │
│  ────────                       │
│  • ffmpeg avfoundation capture  │
│  • Screen + BlackHole + mic     │
│  • User presses q to stop       │
└───────────┬─────────────────────┘
            ▼
┌─────────────────────────────────┐
│  4. Teardown                    │
│  ────────                       │
│  • Restore original output      │
│  • Destroy Multi-Output Device  │
│  • Verify restoration           │
└───────────┬─────────────────────┘
            ▼
┌─────────────────────────────────┐
│  5. Process (existing pipeline) │
│  ──────────────────────────     │
│  • Extract audio → MP3          │
│  • Transcribe (Whisper)         │
│  • Extract frames (if video)    │
└─────────────────────────────────┘
```

## Audio Safety: Defense in Depth

**This is the most important section of this plan.**

Capturing system audio on macOS requires temporarily changing the user's audio output device. If the recording process crashes, is killed, or has a bug, the user can be left with broken audio — no sound from speakers, audio routed to a nonexistent device, or volume controls not working. This is unacceptable.

The design principle: **no single failure should leave the user with broken audio.** Multiple independent recovery mechanisms ensure that audio is always restorable, even in worst-case scenarios.

### Layer 1: State snapshot before any changes

Before touching audio configuration, save the complete current state to a JSON file on disk:

```python
# ~/.slurpai/audio_snapshot.json
{
    "timestamp": "2026-04-08T08:55:00",
    "original_output_device_uid": "AppleHDAEngineOutput:1B,0,1,1:0",
    "original_output_device_name": "MacBook Pro Speakers",
    "aggregate_device_id": null,  # populated after creation
    "recording_pid": 12345
}
```

**Why a file, not just a variable:** If the Python process is killed (SIGKILL, OOM, kernel panic), in-memory state is lost. The snapshot file survives and enables recovery by a subsequent `slurpai record --restore` command (see Layer 5).

The snapshot is written **before** any audio changes are made. If the process crashes between writing the snapshot and changing the audio, the snapshot is stale but harmless — the restore is a no-op because audio was never changed.

### Layer 2: atexit handler

```python
atexit.register(restore_audio)
```

Fires on normal exit, unhandled exceptions, and `sys.exit()`. This is the primary cleanup path for the happy case and most error cases.

**What it does:**
1. Switch system output back to `original_output_device_uid` from snapshot
2. Destroy the aggregate device
3. Verify the output device is restored (read back and compare)
4. Delete the snapshot file
5. Log the restoration

**Limitation:** Does not fire on SIGKILL or hard crashes. That's what Layers 3-5 handle.

### Layer 3: Signal handlers

```python
for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(sig, graceful_shutdown)
```

Catches Ctrl+C (SIGINT), `kill <pid>` (SIGTERM), and terminal close (SIGHUP). The handler:
1. Sends `q` to ffmpeg stdin (clean recording stop)
2. Waits for ffmpeg to finalise the file (up to 5 seconds)
3. Calls `restore_audio()` (same function as atexit)
4. Exits cleanly

**Why both atexit AND signal handlers:** atexit doesn't fire if `os._exit()` is called or if the signal handler calls `sys.exit()` in some Python versions. Belt and suspenders.

### Layer 4: Aggregate device is temporary

The Multi-Output Device created by `AudioHardwareCreateAggregateDevice` is **owned by the creating process**. When the process exits — for any reason, including SIGKILL — macOS automatically destroys the aggregate device.

When the aggregate device is destroyed while it's the active output, macOS falls back to the built-in output device (usually MacBook Pro Speakers). This is macOS's own recovery mechanism and it works even when our code doesn't get a chance to run.

**What this means:** Even if the Python process is killed with `kill -9`, the aggregate device disappears and macOS recovers audio output automatically. The user might hear a brief audio glitch but speakers will work.

**Testing required:** Verify this fallback behaviour on macOS 14 Sonoma specifically. If macOS does NOT fall back gracefully, Layer 5 becomes critical rather than supplementary.

### Layer 5: Manual recovery command

```bash
slurpai record --restore
```

Reads `~/.slurpai/audio_snapshot.json`, switches output back to the saved device, and cleans up. This is the escape hatch for scenarios where all automatic recovery fails.

**When this is needed:**
- The process was killed AND macOS didn't fall back gracefully (unlikely but possible)
- A bug in the cleanup code left audio in a bad state
- The user wants to manually verify their audio is restored

**What it does:**
1. Read the snapshot file
2. If `recording_pid` is still running, warn and ask for confirmation
3. Switch output to `original_output_device_uid`
4. Attempt to destroy any aggregate device we created (by UID)
5. Verify output is restored
6. Delete the snapshot file

**If the snapshot file doesn't exist:** Print "No audio snapshot found — nothing to restore. If your audio is broken, open System Settings → Sound → Output and select your speakers."

### Layer 6: Startup check

Every time `slurpai record` starts, before doing anything else:

1. Check if `~/.slurpai/audio_snapshot.json` exists
2. If it does, check if `recording_pid` is still running
3. If the PID is dead (stale snapshot from a crashed previous run):
   - Restore audio from the snapshot automatically
   - Log: "Recovered audio from previous crashed recording session"
   - Delete the snapshot
   - Continue with the new recording

This means a crash during one recording is automatically cleaned up at the start of the next one, even if the user never ran `--restore`.

### Summary of failure modes

| Failure | What happens | Audio restored by |
|---|---|---|
| User presses q | ffmpeg stops cleanly, atexit fires | Layer 2 (atexit) |
| User presses Ctrl+C | Signal handler fires, then atexit | Layer 3 (signal) → Layer 2 |
| Unhandled Python exception | atexit fires | Layer 2 (atexit) |
| `kill <pid>` | SIGTERM handler fires | Layer 3 (signal) |
| `kill -9 <pid>` | Process dies immediately | Layer 4 (macOS fallback — aggregate device destroyed) |
| Kernel panic / power loss | Machine reboots, aggregate device gone | Layer 4 (device gone) + Layer 6 (startup check on next run) |
| Bug in cleanup code | Audio left in bad state | Layer 5 (`--restore`) |
| OOM kill | Process dies | Layer 4 + Layer 6 |
| User closes terminal | SIGHUP handler fires | Layer 3 (signal) |
| Two recordings started simultaneously | Second invocation detects snapshot, warns | Layer 6 (startup check) |

### What we explicitly do NOT do

- **Never delete or modify the user's existing audio devices.** We only create a temporary aggregate device and switch the default output. The user's speakers, headphones, and any other devices are untouched.
- **Never persist the aggregate device.** It's temporary and process-owned. No permanent system modifications.
- **Never suppress errors in cleanup.** If restoration fails, log the error AND print instructions for manual recovery. Don't silently swallow the failure.
- **Never leave the snapshot file behind on success.** A leftover snapshot means something went wrong. Layer 6 treats it as a crash indicator.

## CoreAudio Implementation

### Framework access

Both frameworks accessed via ctypes. No pip packages needed — these ship with macOS.

```python
CoreAudio = ctypes.cdll.LoadLibrary(
    '/System/Library/Frameworks/CoreAudio.framework/CoreAudio'
)
CoreFoundation = ctypes.cdll.LoadLibrary(
    '/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation'
)
```

### Functions needed

**CoreAudio (6 functions):**

| Function | Purpose |
|---|---|
| `AudioObjectGetPropertyDataSize` | Get size of property data (to allocate buffer) |
| `AudioObjectGetPropertyData` | Read device properties (UID, name, device list) |
| `AudioObjectSetPropertyData` | Set default output device |
| `AudioHardwareCreateAggregateDevice` | Create Multi-Output Device |
| `AudioHardwareDestroyAggregateDevice` | Destroy Multi-Output Device |

**CoreFoundation (7 functions):**

| Function | Purpose |
|---|---|
| `CFStringCreateWithCString` | Create CFString from Python string |
| `CFArrayCreate` | Create CFArray of sub-device UIDs |
| `CFDictionaryCreate` | Create config dict for aggregate device |
| `CFNumberCreate` | Create CFNumber (for boolean flags) |
| `CFStringGetCString` | Read CFString back to Python string |
| `CFStringGetLength` | Get CFString length |
| `CFRelease` | Free CF objects |

### High-level API (what record.py calls)

```python
# macos_audio.py — public interface

def get_default_output() -> AudioDevice:
    """Return the current default output device (name + UID)."""

def find_blackhole() -> str | None:
    """Return BlackHole 2ch device UID, or None if not installed."""

def create_multi_output(name: str, device_uids: list[str]) -> int:
    """Create a temporary Multi-Output Device. Returns device ID."""

def destroy_multi_output(device_id: int) -> None:
    """Destroy an aggregate device."""

def set_default_output(device_uid: str) -> None:
    """Switch the system default output device."""

def verify_output(expected_uid: str) -> bool:
    """Read back the current output and confirm it matches expected."""
```

## ffmpeg Recording

### Capture command

```bash
ffmpeg \
  -f avfoundation -capture_cursor 1 -framerate 5 \
    -i "Capture screen 0:none" \
  -f avfoundation \
    -i ":BlackHole 2ch" \
  -f avfoundation \
    -i ":MacBook Pro Microphone" \
  -filter_complex "[1:a][2:a]amerge=inputs=2[a]" \
  -map 0:v -map "[a]" \
  -c:v libx264 -preset ultrafast -crf 28 \
  -c:a aac -b:a 128k \
  -movflags +faststart \
  output.mp4
```

**Design choices:**
- **5 fps, not 30:** Meeting recordings don't need smooth video. 5 fps reduces file size by ~6x with no loss of useful information. Slides and screen shares are static — 5 fps captures every transition.
- **CRF 28:** Lower quality than default (23) but fine for screen content. Further reduces file size.
- **ultrafast preset:** Minimal CPU usage during the meeting. Quality tradeoff is acceptable for screen recordings.
- **Two audio inputs merged:** System audio (BlackHole) + mic combined into one stereo track. Both sides of the conversation in one file.
- **faststart:** Moves the moov atom to the front of the file so playback can start before the full file is downloaded/loaded. Small thing, nice to have.

### Stopping the recording

ffmpeg accepts `q` on stdin to stop cleanly and finalise the file. The recording loop:

1. Start ffmpeg as a subprocess with `stdin=PIPE`
2. Wait for user input (q or Ctrl+C)
3. Send `q` to ffmpeg stdin
4. Wait for ffmpeg to exit (up to 10 seconds, then SIGTERM)
5. Verify the output file exists and is non-empty

### Screen Recording permission

macOS requires Screen Recording permission for any process capturing the screen. On first use, the OS will prompt the user. If denied, ffmpeg produces a blank/black screen.

**Detection:** After starting ffmpeg, check if the first few frames are solid black (can sample with ffprobe). If so, warn the user:

```
Screen recording permission required.
Grant access: System Settings → Privacy & Security → Screen Recording → Terminal
Then restart the recording.
```

Alternatively, we can check the TCC database before starting, but parsing the TCC database is fragile across macOS versions. Detecting black frames after the fact is more reliable.

**For v1:** Print a pre-flight reminder before starting: "Make sure Terminal has Screen Recording permission (System Settings → Privacy & Security → Screen Recording)."

## CLI Interface

### Converting to a Click group

The current CLI is a single `@click.command()`. Adding `record` requires converting to a `@click.group()` with subcommands.

**Before:**
```bash
slurpai file1.opus file2.mp4        # process files
```

**After:**
```bash
slurpai process file1.opus file2.mp4  # process files (explicit subcommand)
slurpai file1.opus file2.mp4          # process files (default, backwards-compatible)
slurpai record --name "meeting"       # record screen + audio
slurpai record --restore              # recover audio from crashed session
```

**Backwards compatibility:** Use Click's `invoke_without_command=True` and `result_callback` pattern so that bare `slurpai file.opus` still works without the `process` subcommand. Existing users' scripts and muscle memory are preserved.

### Record subcommand options

```
slurpai record [OPTIONS]

Options:
  --name TEXT          Recording name (default: recording_YYYYMMDD_HHMMSS)
  -o, --output-dir     Output directory (default: current directory)
  -f, --frame-interval Frame extraction interval in seconds (default: 15)
  -b, --backend        Transcription backend (default: openai)
  -l, --language        Language hint (default: en)
  --no-process         Record only, skip transcription and frame extraction
  --restore            Restore audio from a crashed previous session
  --dry-run            Show what would happen without recording
```

## Testing Plan

### Manual testing (before first real use)

1. **Install BlackHole:** `brew install --cask blackhole-2ch` — verify no restart needed, device appears in System Settings → Sound
2. **Basic recording:** `slurpai record --name test` — record 30 seconds of a YouTube video, verify playback has screen + both audio channels
3. **Ctrl+C stop:** Start recording, Ctrl+C after 10 seconds. Verify: audio restored, file playable, no corruption
4. **Kill -9 recovery:** Start recording, `kill -9 <pid>` from another terminal. Verify: macOS falls back to speakers, `slurpai record --restore` cleans up snapshot
5. **Pipeline integration:** Full recording → verify transcript.txt and frames/ are generated
6. **Permission denied:** Revoke Screen Recording permission, attempt recording, verify clear error message
7. **No BlackHole:** Uninstall BlackHole, attempt recording, verify clear error with install instructions
8. **Headphones:** Start recording with headphones plugged in. Verify system audio routes through headphones AND is captured.

### Automated tests

- Unit tests for `macos_audio.py` device discovery (mock CoreAudio calls)
- Integration test: create + destroy aggregate device, verify cleanup
- Test snapshot write/read/delete cycle
- Test `--restore` with stale snapshot file
- Test backwards compatibility: `slurpai file.opus` still works

## Scope Boundaries

### In scope (v1)

- macOS only (avfoundation + CoreAudio are macOS-specific)
- Main screen capture (no multi-monitor selection)
- Default mic (no mic selection)
- BlackHole as the only supported virtual audio driver
- Click group conversion with backwards compatibility
- Six-layer audio safety (as described above)

### Out of scope (future)

- Linux/Windows recording support
- Multiple screen selection (`--screen` option)
- Mic selection (`--mic` option)
- Audio-only recording (no screen)
- Live streaming
- Webcam overlay
- Recording pause/resume
- Alternative virtual audio drivers (Soundflower, Loopback)
