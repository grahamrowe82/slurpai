# Contributing to slurpai

Thanks for wanting to help. Here's how to get set up.

## Development setup

```bash
git clone https://github.com/grahamrowe82/slurpai.git
cd slurpai
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

You'll also need [ffmpeg](https://ffmpeg.org/) installed.

## Running tests

```bash
pytest -v
```

Tests use ffmpeg to generate tiny test audio/video files — no API keys needed.

## Submitting changes

1. Fork the repo and create a branch
2. Make your changes
3. Run `pytest` and make sure everything passes
4. Open a pull request

## Reporting bugs

Open an issue at https://github.com/grahamrowe82/slurpai/issues with:
- What you ran (`slurpai ...`)
- What happened (error message or unexpected output)
- Your OS and Python version
