"""Simple dual logger — writes to stdout and a process.log file."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


class ProcessLog:
    """Logger that writes timestamped messages to both stdout and a file."""

    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, message: str) -> None:
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        print(line)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def skip(self, message: str) -> None:
        self.log(f"[skip] {message}")
