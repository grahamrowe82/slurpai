"""CLI entry point for slurpai."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv

from . import __version__


class DefaultGroup(click.Group):
    """A Click group that falls back to a default command for bare file args.

    When the first CLI argument is not a registered subcommand name,
    the default command is prepended automatically. This lets
    ``slurpai file.opus`` keep working after the CLI becomes a group.
    """

    def __init__(self, *args, default_cmd_name=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_cmd_name = default_cmd_name

    def parse_args(self, ctx, args):
        # Prepend the default command when no known subcommand appears in args.
        # This lets ``slurpai file.opus`` and ``slurpai --dry-run file.opus``
        # both route to the default "process" subcommand, while
        # ``slurpai --help`` and ``slurpai --version`` still work on the group.
        if args and self.default_cmd_name:
            if not any(a in self.commands for a in args):
                # No subcommand found — but only inject default if there's at
                # least one non-flag argument (i.e. a file path).
                has_positional = any(not a.startswith("-") for a in args)
                if has_positional:
                    args = [self.default_cmd_name] + args
        return super().parse_args(ctx, args)


@click.group(cls=DefaultGroup, default_cmd_name="process")
@click.version_option(version=__version__)
def slurpai():
    """Convert voice notes, audio files, and videos into text and images."""


@slurpai.command()
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
def process(
    files: tuple[str, ...],
    backend: str | None,
    frame_interval: int,
    output_dir: str | None,
    language: str,
    dry_run: bool,
) -> None:
    """Process audio/video files into text and images."""
    load_dotenv()

    backend = backend or os.getenv("SLURPAI_BACKEND", "openai")

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


@slurpai.command()
@click.option("--setup", is_flag=True, help="One-time setup: create Multi-Output audio device")
@click.option("--restore", is_flag=True, help="Restore audio output from a crashed session")
@click.option("--name", "-n", type=str, default=None, help="Recording name (default: recording_YYYYMMDD_HHMMSS)")
@click.option("-o", "--output-dir", type=click.Path(), default=None, help="Output directory (default: current directory)")
@click.option("--no-process", is_flag=True, help="Record only, skip transcription and frame extraction")
@click.option(
    "-b",
    "--backend",
    type=click.Choice(["openai", "faster-whisper"]),
    default=None,
    help="Transcription backend for post-processing",
)
@click.option("-f", "--frame-interval", type=int, default=15, help="Frame grab interval for post-processing")
@click.option("-l", "--language", type=str, default="en", help="Language hint for post-processing transcription")
def record(
    setup: bool,
    restore: bool,
    name: str | None,
    output_dir: str | None,
    no_process: bool,
    backend: str | None,
    frame_interval: int,
    language: str,
) -> None:
    """Record screen, system audio, and microphone (macOS only)."""
    import platform

    if platform.system() != "Darwin":
        click.echo("Error: 'slurpai record' is only supported on macOS.", err=True)
        sys.exit(1)

    load_dotenv()
    backend = backend or os.getenv("SLURPAI_BACKEND", "openai")

    from .record import record_command, restore_audio, run_setup

    if setup:
        run_setup()
        return

    if restore:
        restore_audio()
        return

    if not name:
        from datetime import datetime

        name = f"recording_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    record_command(
        name=name,
        output_dir=output_dir,
        no_process=no_process,
        backend=backend,
        frame_interval=frame_interval,
        language=language,
    )
