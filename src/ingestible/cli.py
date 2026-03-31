"""CLI entry point for ingestible."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv

from . import __version__


@click.command()
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True))
@click.option(
    "-b",
    "--backend",
    type=click.Choice(["openai", "faster-whisper"]),
    default=None,
    help="Transcription backend (default: env or openai)",
)
@click.option(
    "-f",
    "--frame-interval",
    type=int,
    default=15,
    help="Seconds between video frame grabs (default: 15)",
)
@click.option(
    "-o",
    "--output-dir",
    type=click.Path(),
    default=None,
    help="Base output directory (default: next to input file)",
)
@click.option(
    "-l",
    "--language",
    type=str,
    default="en",
    help="Language hint for transcription (default: en)",
)
@click.option("--dry-run", is_flag=True, help="Show what would be processed")
@click.version_option(version=__version__)
def ingest(
    files: tuple[str, ...],
    backend: str | None,
    frame_interval: int,
    output_dir: str | None,
    language: str,
    dry_run: bool,
) -> None:
    """Convert voice notes, audio files, and videos into text and images."""
    load_dotenv()

    backend = backend or os.getenv("INGESTIBLE_BACKEND", "openai")

    from .ffmpeg import check_ffmpeg
    from .process import SUPPORTED_EXTENSIONS, process_file

    if not check_ffmpeg():
        click.echo("Error: ffmpeg not found. Install it: brew install ffmpeg", err=True)
        sys.exit(1)

    output_base = Path(output_dir) if output_dir else None
    paths = [Path(f) for f in files]

    # Filter to supported formats
    supported = []
    for p in paths:
        if p.suffix.lower() in SUPPORTED_EXTENSIONS:
            supported.append(p)
        else:
            click.echo(f"Skipping unsupported format: {p.name}")

    if not supported:
        click.echo("No supported files to process.")
        sys.exit(1)

    if dry_run:
        click.echo(f"Would process {len(supported)} file(s) with backend={backend}:")
        for p in supported:
            click.echo(f"  {p}")
        return

    success = 0
    failed = 0
    for p in supported:
        try:
            result = process_file(
                p,
                backend=backend,
                frame_interval=frame_interval,
                output_dir=output_base,
                language=language,
            )
            click.echo(f"Done: {result}")
            success += 1
        except Exception as e:
            click.echo(f"Failed: {p.name} — {e}", err=True)
            failed += 1

    if len(supported) > 1:
        click.echo(f"\n{success} succeeded, {failed} failed out of {len(supported)}")
