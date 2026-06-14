from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from codex_lifeboat import __version__


def git_value(repo_dir: Path, *args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=repo_dir, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def write_build_metadata(repo_dir: Path, executable: Path) -> Path:
    dist_dir = repo_dir / "dist"
    short_sha = git_value(repo_dir, "rev-parse", "--short", "HEAD") or "unknown"
    full_sha = git_value(repo_dir, "rev-parse", "HEAD") or "unknown"
    dirty = bool(git_value(repo_dir, "status", "--short"))
    versioned_executable = dist_dir / f"agent-lifeboat-{__version__}"
    shutil.copy2(executable, versioned_executable)
    metadata_path = dist_dir / "build-info.json"
    metadata = {
        "name": "agent-lifeboat",
        "version": __version__,
        "git_sha": full_sha,
        "git_short_sha": short_sha,
        "git_dirty": dirty,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "executable": str(executable),
        "versioned_executable": str(versioned_executable),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return versioned_executable


def main() -> int:
    try:
        import PyInstaller.__main__
    except ImportError:
        print("PyInstaller is not installed. Run: .venv/bin/python -m pip install '.[standalone]'", file=sys.stderr)
        return 2

    entrypoint = Path(__file__).with_name("__main__.py")
    repo_dir = entrypoint.parent.parent
    PyInstaller.__main__.run(
        [
            "--name",
            "agent-lifeboat",
            "--onefile",
            "--console",
            "--clean",
            str(entrypoint),
        ]
    )
    executable = repo_dir / "dist" / "agent-lifeboat"
    if executable.exists():
        versioned_executable = write_build_metadata(repo_dir, executable)
        print(f"Version: {__version__}")
        print(f"Versioned binary: {versioned_executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
