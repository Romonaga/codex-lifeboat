from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    try:
        import PyInstaller.__main__
    except ImportError:
        print("PyInstaller is not installed. Run: .venv/bin/python -m pip install '.[standalone]'", file=sys.stderr)
        return 2

    entrypoint = Path(__file__).with_name("__main__.py")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
