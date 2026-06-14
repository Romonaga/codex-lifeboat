from __future__ import annotations

from pathlib import Path

from .config import AppConfig


def ensure_directory(path: Path, lines: list[str]) -> None:
    if path.exists():
        lines.append(f"exists: {path}")
        return
    path.mkdir(parents=True, exist_ok=True)
    lines.append(f"created: {path}")


def doctor_fixes(config: AppConfig) -> list[str]:
    lines: list[str] = []
    ensure_directory(config.config_dir, lines)
    ensure_directory(config.output_dir, lines)
    ensure_directory(config.output_dir / "archives", lines)
    ensure_directory(config.output_dir / "resume-packages", lines)
    return lines
