# slurpai

Convert voice notes, videos, and audio files into AI-ready text and images.

Consultants, researchers, and anyone who works with AI tools faces the same problem: clients and colleagues send voice notes, screen recordings, and video walkthroughs — but your AI workflow needs text and images. SlurpAI bridges that gap with a single command.

## Quick start

```bash
pip install slurpai
export OPENAI_API_KEY=sk-...
slurpai client-feedback.opus
```

That's it. You get a folder with `transcript.txt` and you're ready to feed it into whatever AI tool you're using.

## Install

```bash
pip install slurpai
```

You also need [ffmpeg](https://ffmpeg.org/) on your PATH:

| OS | Command |
|----|---------|
| macOS | `brew install ffmpeg` |
| Ubuntu/Debian | `sudo apt install ffmpeg` |
| Windows | `choco install ffmpeg` or download from [ffmpeg.org](https://ffmpeg.org/download.html) |

## Usage

```bash
# Transcribe a voice note
slurpai recording.opus

# Process a video (transcript + frame grabs every 15 seconds)
slurpai feedback.mp4

# Batch process everything in a folder
slurpai *.opus *.mp4

# Grab frames more frequently
slurpai --frame-interval 5 demo.mp4

# Use local Whisper instead of OpenAI API
pip install slurpai[local]
slurpai --backend faster-whisper recording.opus

# Preview what would be processed
slurpai --dry-run *.opus
```

## Output

Each file produces a folder alongside it:

```
recording/
├── transcript.txt    # Plain text transcription
├── frames/           # Video frame grabs (video only)
│   ├── frame_001.jpg
│   ├── frame_002.jpg
│   └── ...
└── process.log       # Timestamped processing log
```

Re-running the same command skips already-completed files (idempotent).

## Privacy notice

**By default, slurpai sends your audio to [OpenAI's Whisper API](https://platform.openai.com/docs/guides/speech-to-text) for transcription.** Your audio is transmitted to OpenAI's servers. Review [OpenAI's data usage policy](https://openai.com/policies/api-data-usage-policies) to understand how your data is handled.

If you need fully local, private transcription — no data leaves your machine:

```bash
pip install slurpai[local]
slurpai --backend faster-whisper recording.opus
```

This uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) running entirely on your CPU. It's slower but nothing leaves your computer.

## Configuration

Set `OPENAI_API_KEY` in your environment or a `.env` file in the current directory.

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | Required for OpenAI backend |
| `SLURPAI_BACKEND` | `openai` | Default backend (`openai` or `faster-whisper`) |
| `OPENAI_WHISPER_MODEL` | `whisper-1` | OpenAI model to use |
| `SLURPAI_WHISPER_MODEL` | `base` | Local Whisper model size (`base`, `small`, `medium`, `large`) |

## Supported formats

**Audio:** `.opus`, `.m4a`, `.ogg`, `.mp3`, `.wav`

**Video:** `.mp4`, `.mkv`, `.mov`, `.webm`

All formats are normalised to MP3 before transcription — this ensures consistent behaviour regardless of input format.

## Requirements

- Python 3.10+
- [ffmpeg](https://ffmpeg.org/) on your PATH

## Contributing

Found a bug or want to add a format? See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
