# ingestible

Convert voice notes, videos, and audio files into AI-ready text and images.

## Install

```bash
pip install ingestible[openai]
```

## Usage

```bash
# Transcribe a voice note
ingest recording.opus

# Process a video (transcript + frame grabs)
ingest feedback.mp4

# Batch process
ingest *.opus *.mp4

# Use local Whisper instead of OpenAI API
ingest --backend faster-whisper recording.opus
```

## Output

Each file produces a folder alongside it:

```
recording/
├── transcript.txt    # Plain text transcription
├── frames/           # Video frame grabs (video only)
│   ├── frame_001.jpg
│   └── ...
└── process.log       # Timestamped processing log
```

## Configuration

Set `OPENAI_API_KEY` in your environment or a `.env` file in the current directory.

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | Required for OpenAI backend |
| `INGESTIBLE_BACKEND` | `openai` | Default backend (`openai` or `faster-whisper`) |
| `OPENAI_WHISPER_MODEL` | `whisper-1` | OpenAI model to use |
| `INGESTIBLE_WHISPER_MODEL` | `base` | Local Whisper model size |

## Supported formats

**Audio:** `.opus`, `.m4a`, `.ogg`, `.mp3`, `.wav`

**Video:** `.mp4`, `.mkv`, `.mov`, `.webm`

## Requirements

- Python 3.10+
- [ffmpeg](https://ffmpeg.org/) on your PATH

## License

MIT
