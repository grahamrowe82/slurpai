# Plan: `slurpai record` — Screen + Audio Recording

**Status:** Planning
**Author:** Graham Rowe
**Date:** April 2026

## Summary

Add a `record` subcommand to SlurpAI that captures screen, microphone, and system audio (e.g. a Teams call) on macOS, then feeds the recording into the existing SlurpAI pipeline for transcription and frame extraction.

**User experience:**

```bash
# One-time setup (takes ~30 seconds)
slurpai record --setup

# ✓ BlackHole 2ch detected
# ✓ Multi-Output Device "SlurpAI Multi-Output" created
# ✓ Setup complete — ready to record

# Recording a meeting
slurpai record --name "client-meeting"

# ✓ Switched audio output to SlurpAI Multi-Output
# ✓ Recording — screen + mic + system audio
# Press q to stop...

# [user presses q]

# ✓ Recording saved (1.2 GB)
# ✓ Audio output restored to MacBook Pro Speakers
# Processing...
# ✓ Transcript: client-meeting/transcript.txt
# ✓ Frames: client-meeting/frames/ (347 frames)
```

Two commands: one setup (once ever), one to record. Full cleanup on exit.

## Motivation

SlurpAI processes voice notes and videos after they've been recorded. But recording a meeting on macOS — with both sides of the audio — currently requires manually configuring OBS, BlackHole, and Audio MIDI Setup. This is error-prone and the setup doesn't persist reliably.

By integrating recording directly into SlurpAI, a consultant can go from "meeting starting" to "recording + transcript + frames" with a single command. The entire post-processing pipeline already exists.

## Design Philosophy

**Invent as little as possible.** This feature coordinates existing tools — it does not reimplement audio device management, screen capture, or transcription. Specifically:

- **BlackHole** handles virtual audio routing (open source, well-maintained, brew-installable)
- **A tiny Swift helper** creates the Multi-Output Device via Apple's own CoreAudio API — the same thing Audio MIDI Setup does when you click the "+" button
- **SwitchAudioSource** handles device switching (open source, brew-installable, one command)
- **ffmpeg** handles screen + audio capture (already a SlurpAI dependency)
- **The existing SlurpAI pipeline** handles transcription and frame extraction

SlurpAI's job is to check prerequisites, coordinate these tools, and clean up afterwards.

## Architecture

### New files

| File | Purpose | Lines (est.) |
|---|---|---|
| `src/slurpai/record.py` | Recording orchestration — setup, capture, teardown, pipeline handoff | ~120 |
| `src/slurpai/audio_setup.swift` | Standalone Swift script — creates a persistent Multi-Output Device | ~40 |
| `cli.py` changes | Add `record` subcommand to Click group | ~30 |

### Dependencies

| Dependency | Type | How installed | Purpose |
|---|---|---|---|
| BlackHole 2ch | System | `brew install --cask blackhole-2ch` | Virtual audio driver — makes system audio recordable |
| SwitchAudioSource | System | `brew install switchaudio-osx` | CLI for switching default audio output device |
| ffmpeg | System | Already a SlurpAI dependency | Screen + audio capture via avfoundation |
| Xcode Command Line Tools | System | Already installed on most dev Macs | Compiles the Swift helper (one-time) |

No new Python package dependencies. The Swift helper is compiled and run once during setup.

### Why these tools?

**BlackHole** is the standard open-source virtual audio driver for macOS. It creates a virtual audio device that applications can record from. When combined with a Multi-Output Device, system audio is simultaneously sent to speakers and to BlackHole, where ffmpeg can capture it.

**SwitchAudioSource** replaces what would otherwise be ~170 lines of CoreAudio ctypes bindings in Python. It's a mature, well-tested C utility that wraps the same CoreAudio API calls. Device switching becomes a single shell command:

```bash
SwitchAudioSource -s "SlurpAI Multi-Output"  # before recording
SwitchAudioSource -s "MacBook Pro Speakers"   # after recording
```

**The Swift helper** is needed because no existing CLI tool can _create_ aggregate/multi-output devices. `SwitchAudioSource`, `audiodevice`, and similar tools can only switch between existing devices. AppleScript GUI scripting of Audio MIDI Setup is fragile and locale-dependent. A ~40-line Swift script calling `AudioHardwareCreateAggregateDevice` is the simplest reliable approach. The key insight: setting `kAudioAggregateDeviceIsPrivateKey = 0` makes the device **public and persistent** — it survives process exit, reboots, and macOS updates, just like one created manually in Audio MIDI Setup.

## The Two Phases

### Phase 1: One-time setup (`slurpai record --setup`)

This runs once. It creates the persistent Multi-Output Device that all future recordings will use.

```
slurpai record --setup
        │
        ▼
┌─────────────────────────────────────┐
│  1. Check prerequisites             │
│  ──────────────────────             │
│  • ffmpeg on PATH?                  │
│  • BlackHole 2ch installed?         │
│  • SwitchAudioSource installed?     │
│  • Xcode CLT available (swiftc)?    │
│  → Print install commands for any   │
│    missing dependencies             │
└───────────┬─────────────────────────┘
            ▼
┌─────────────────────────────────────┐
│  2. Check if already set up         │
│  ──────────────────────             │
│  • Does "SlurpAI Multi-Output"      │
│    already appear in device list?   │
│  → If yes: "Already set up" + exit  │
└───────────┬─────────────────────────┘
            ▼
┌─────────────────────────────────────┐
│  3. Compile + run Swift helper      │
│  ────────────────────────           │
│  • swiftc audio_setup.swift         │
│  • Run it → creates persistent      │
│    Multi-Output Device combining:   │
│    - Built-in Output (top/clock)    │
│    - BlackHole 2ch                  │
│  • Verify device appears in list    │
└───────────┬─────────────────────────┘
            ▼
┌─────────────────────────────────────┐
│  4. Print confirmation              │
│  ────────────────────               │
│  • "SlurpAI Multi-Output created"   │
│  • "Run: slurpai record --name X"   │
└─────────────────────────────────────┘
```

#### The Swift helper (`audio_setup.swift`)

This is a standalone Swift script, not a module. It does one thing: create a persistent Multi-Output Device.

```swift
import CoreAudio
import CoreFoundation

// 1. Find Built-in Output device UID
// 2. Find BlackHole 2ch device UID
// 3. Create aggregate device with:
//    - uid: "com.slurpai.multi-output"
//    - name: "SlurpAI Multi-Output"
//    - private: 0  (persistent, survives reboot)
//    - stacked: 0  (multi-output: all sub-devices get same audio)
//    - subdevices: [Built-in Output, BlackHole 2ch]
//    - Built-in Output as clock/top device
// 4. Print success or error to stdout
```

Built-in Output must be the top device in the Multi-Output Device. This is a [documented macOS requirement](https://github.com/ExistentialAudio/BlackHole/wiki/Multi-Output-Device) — if BlackHole is listed first, audio routing silently fails.

The device is created with `kAudioAggregateDeviceIsPrivateKey = 0`, which makes it public and persistent. It behaves identically to a device created manually in Audio MIDI Setup.

### Phase 2: Recording (`slurpai record`)

```
slurpai record --name "meeting"
        │
        ▼
┌─────────────────────────────────────┐
│  1. Pre-flight checks               │
│  ───────────────────                │
│  • "SlurpAI Multi-Output" exists?   │
│    → If not: "Run --setup first"    │
│  • ffmpeg on PATH?                  │
│  • Stale snapshot? (see Safety)     │
│  • Print reminder: "Make sure       │
│    Terminal has Screen Recording    │
│    permission"                      │
└───────────┬─────────────────────────┘
            ▼
┌─────────────────────────────────────┐
│  2. Switch audio output             │
│  ─────────────────────              │
│  • Snapshot current output device   │
│    to ~/.slurpai/audio_snapshot.json│
│  • SwitchAudioSource -s             │
│    "SlurpAI Multi-Output"           │
│  • Register cleanup handlers        │
└───────────┬─────────────────────────┘
            ▼
┌─────────────────────────────────────┐
│  3. Record                          │
│  ──────                             │
│  • ffmpeg avfoundation capture      │
│  • Screen + BlackHole + mic         │
│  • User presses q to stop           │
└───────────┬─────────────────────────┘
            ▼
┌─────────────────────────────────────┐
│  4. Restore audio output            │
│  ──────────────────────             │
│  • SwitchAudioSource -s             │
│    "<original device>"              │
│  • Delete snapshot file             │
└───────────┬─────────────────────────┘
            ▼
┌─────────────────────────────────────┐
│  5. Process (existing pipeline)     │
│  ──────────────────────             │
│  • Extract audio → MP3              │
│  • Transcribe (Whisper)             │
│  • Extract frames (if video)        │
└─────────────────────────────────────┘
```

## Audio Safety

The original plan had six layers of safety because it was creating and destroying aggregate devices per-recording. With the simplified approach, the Multi-Output Device is persistent and never touched during recording. The only thing that changes per-recording is which device is the default output — a single `SwitchAudioSource` call.

### What can go wrong

The failure mode is simple: if the process crashes mid-recording, the default output is left pointing at "SlurpAI Multi-Output" instead of the user's speakers. This is annoying (volume keys stop working — see Known Limitations below) but not catastrophic. Audio still plays through speakers since Built-in Output is a sub-device of the Multi-Output Device. The user can fix it manually in System Settings > Sound > Output, or by running `slurpai record --restore`.

### Layer 1: State snapshot

Before switching audio, save the current output device to disk:

```python
# ~/.slurpai/audio_snapshot.json
{
    "timestamp": "2026-04-08T08:55:00",
    "original_output_device": "MacBook Pro Speakers",
    "recording_pid": 12345
}
```

This is a flat file with the device name. Written before the switch, deleted after successful restoration.

### Layer 2: atexit handler

```python
atexit.register(restore_audio)
```

Fires on normal exit, unhandled exceptions, and `sys.exit()`. Runs `SwitchAudioSource -s "<original device>"` and deletes the snapshot.

### Layer 3: Signal handlers

```python
for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(sig, graceful_shutdown)
```

Catches Ctrl+C, `kill <pid>`, and terminal close. Sends `q` to ffmpeg, waits for it to finalise the file, then calls `restore_audio()`.

### Layer 4: Startup check

Every time `slurpai record` starts, before doing anything else:

1. Check if `~/.slurpai/audio_snapshot.json` exists
2. If it does, check if `recording_pid` is still running
3. If the PID is dead (stale snapshot from a crashed session):
   - Restore audio: `SwitchAudioSource -s "<original device>"`
   - Log: "Recovered audio from previous crashed recording session"
   - Delete the snapshot
   - Continue with the new recording

### Layer 5: Manual recovery

```bash
slurpai record --restore
```

Reads the snapshot and switches back. Also works if the user just wants to manually confirm their audio is restored.

If no snapshot exists: prints "No audio snapshot found. If your audio output is wrong, open System Settings > Sound > Output and select your speakers."

### What we do NOT need (vs. the original plan)

- **No aggregate device creation/destruction per recording.** The device is persistent.
- **No CoreAudio ctypes bindings.** Device switching is handled by SwitchAudioSource.
- **No process-owned device fallback.** The device survives process exit by design.
- **No kernel panic / SIGKILL / OOM recovery for device cleanup.** The device persists regardless. The only thing to recover is the output switch, which the startup check (Layer 4) handles on next run.

### Summary of failure modes

| Failure | Audio output | Restored by |
|---|---|---|
| User presses q | Restored immediately | Layer 2 (atexit) |
| User presses Ctrl+C | Restored immediately | Layer 3 (signal) → Layer 2 |
| Unhandled Python exception | Restored immediately | Layer 2 (atexit) |
| `kill <pid>` | Restored immediately | Layer 3 (signal) |
| `kill -9 <pid>` | Left on Multi-Output Device* | Layer 4 (startup check on next run) or Layer 5 (manual --restore) |
| Kernel panic / power loss | Reset to default by macOS on reboot | No action needed |
| Bug in cleanup code | Left on Multi-Output Device* | Layer 5 (manual --restore) |

*Audio still works through speakers (Built-in Output is a sub-device), but volume keys are disabled. The user can also fix this manually in System Settings > Sound > Output.

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
- **5 fps, not 30:** Meeting recordings don't need smooth video. 5 fps reduces file size by ~6x. Slides and screen shares are static — 5 fps captures every transition.
- **CRF 28:** Lower quality than default (23) but fine for screen content. Further reduces file size.
- **ultrafast preset:** Minimal CPU usage during the meeting. Quality tradeoff is acceptable for screen recordings.
- **Two audio inputs merged:** System audio (BlackHole) + mic combined into one stereo track. Both sides of the conversation in one file.
- **faststart:** Moves the moov atom to the front for faster playback start.

### Stopping the recording

ffmpeg accepts `q` on stdin to stop cleanly and finalise the file. The recording loop:

1. Start ffmpeg as a subprocess with `stdin=PIPE`
2. Wait for user input (q or Ctrl+C)
3. Send `q` to ffmpeg stdin
4. Wait for ffmpeg to exit (up to 10 seconds, then SIGTERM)
5. Verify the output file exists and is non-empty

### Screen Recording permission

macOS requires Screen Recording permission for any process capturing the screen. On first use, the OS will prompt the user. If denied, ffmpeg produces a blank/black screen.

**For v1:** Print a pre-flight reminder before starting: "Make sure Terminal has Screen Recording permission (System Settings > Privacy & Security > Screen Recording)."

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
slurpai record --setup                # one-time setup
slurpai record --restore              # recover audio from crashed session
```

**Backwards compatibility:** Use Click's `invoke_without_command=True` and `result_callback` pattern so that bare `slurpai file.opus` still works without the `process` subcommand.

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
  --setup              One-time setup: install Multi-Output Device
  --restore            Restore audio from a crashed previous session
  --dry-run            Show what would happen without recording
```

## Known Limitations (from real-world reports)

These are issues reported by real users in public forums, not theoretical concerns.

### Volume control disabled during recording

macOS does not support changing the volume of a Multi-Output Device. When the default output is switched to "SlurpAI Multi-Output" during recording, the volume slider greys out and keyboard volume keys stop working. This is by design in macOS, not a bug.

**Mitigation:** The output is only switched to the Multi-Output Device during active recording. Before and after, the user's normal output device is active with full volume control. If a recording crashes without cleanup, the user can fix this manually or via `slurpai record --restore`.

**References:** [BlackHole wiki](https://github.com/ExistentialAudio/BlackHole/wiki/Multi-Output-Device), [Apple Community](https://discussions.apple.com/thread/7598666), [BlackHole #16](https://github.com/ExistentialAudio/BlackHole/issues/16)

### BlackHole can disappear after sleep

Some users report BlackHole vanishing from Audio MIDI Setup after sleep/wake cycles, reappearing after restart. If BlackHole disappears, the Multi-Output Device may stop routing system audio to the recording (though audio will still play through speakers).

**Mitigation:** The pre-flight check before recording verifies that BlackHole is still present. If it's gone, print a clear message: "BlackHole 2ch not detected. Try restarting your Mac, or reinstall: `brew reinstall --cask blackhole-2ch`."

**References:** [BlackHole #508](https://github.com/ExistentialAudio/BlackHole/issues/508), [BlackHole #239](https://github.com/ExistentialAudio/BlackHole/issues/239)

### Bluetooth / AirPods incompatibility

Bluetooth audio devices use different sample rates (especially in SCO mode for mic input) which cause aggregate devices to produce garbled audio or fail entirely. Sonoma 14.2 introduced additional breakage for Bluetooth aggregates.

**Mitigation:** This plan does not include Bluetooth devices in the Multi-Output Device. The Multi-Output Device always uses Built-in Output + BlackHole. If the user is listening through AirPods, system audio still plays through AirPods (the default output is the Multi-Output Device, whose Built-in Output sub-device is playing), but the recording captures from BlackHole. However, this specific interaction needs testing — it may not work as expected with Bluetooth active.

**References:** [BlackHole #758](https://github.com/ExistentialAudio/BlackHole/issues/758)

### macOS updates can break the Multi-Output Device

Major macOS updates occasionally reset or corrupt audio device configuration. The Multi-Output Device may stop working after an update.

**Mitigation:** `slurpai record --setup` is idempotent. If the device breaks, run setup again. The pre-flight check before recording detects if the device is missing and directs the user to re-run setup.

### Device ordering matters

Built-in Output must be the top (clock) device in the Multi-Output Device. If BlackHole is listed first, audio routing silently fails.

**Mitigation:** The Swift helper creates the device with the correct ordering. This is hardcoded, not user-configurable.

**Reference:** [BlackHole wiki](https://github.com/ExistentialAudio/BlackHole/wiki/Multi-Output-Device)

## Testing Plan

### Manual testing (before first real use)

1. **Setup flow:** `slurpai record --setup` on a clean Mac — verify BlackHole detection, Swift compilation, device creation, device appears in Audio MIDI Setup
2. **Setup idempotency:** Run `--setup` again — verify "already set up" message, no duplicate device
3. **Basic recording:** `slurpai record --name test` — record 30 seconds of a YouTube video, verify playback has screen + both audio channels
4. **Volume during recording:** While recording, verify volume keys are disabled (expected). After recording stops, verify volume keys work again.
5. **Ctrl+C stop:** Start recording, Ctrl+C after 10 seconds. Verify: audio restored, file playable
6. **Kill -9 recovery:** `kill -9 <pid>` from another terminal. Verify: audio still plays (through Multi-Output Device), `slurpai record --restore` switches back, next `slurpai record` auto-recovers via startup check
7. **Pipeline integration:** Full recording → verify transcript.txt and frames/ are generated
8. **No BlackHole:** Uninstall BlackHole, attempt `--setup`, verify clear error with install command
9. **Headphones:** Start recording with wired headphones plugged in. Verify behaviour and document.
10. **Sleep/wake:** Start recording, close lid briefly, reopen. Observe what happens.

### Automated tests

- Test snapshot write/read/delete cycle
- Test `--restore` with stale snapshot file
- Test `--restore` with no snapshot file
- Test `--setup` idempotency (mock device list)
- Test pre-flight checks (mock missing dependencies)
- Test backwards compatibility: `slurpai file.opus` still works after Click group conversion

## Scope Boundaries

### In scope (v1)

- macOS only (avfoundation + CoreAudio are macOS-specific)
- Main screen capture (no multi-monitor selection)
- Default mic (no mic selection)
- BlackHole as the only supported virtual audio driver
- SwitchAudioSource for device switching
- Click group conversion with backwards compatibility
- One-time setup via `--setup`
- Per-recording audio switch + restore with snapshot-based safety

### Out of scope (future)

- Linux/Windows recording support
- Multiple screen selection (`--screen` option)
- Mic selection (`--mic` option)
- Audio-only recording (no screen)
- Live streaming
- Webcam overlay
- Recording pause/resume
- Alternative virtual audio drivers (Soundflower, Loopback)
- Volume control during recording (macOS limitation)
