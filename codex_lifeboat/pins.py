from __future__ import annotations

import json
from pathlib import Path

from .config import AppConfig


class PinStore:
    def __init__(self, config: AppConfig):
        self.config = config

    @property
    def path(self) -> Path:
        return self.config.config_dir / "pins.json"

    def load(self) -> set[str]:
        if not self.path.exists():
            return set()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return set()
        if isinstance(data, list):
            return {str(item) for item in data}
        return set()

    def save(self, pins: set[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(sorted(pins), indent=2) + "\n", encoding="utf-8")

    def pin(self, session_id: str) -> None:
        pins = self.load()
        pins.add(session_id)
        self.save(pins)

    def unpin(self, session_id: str) -> None:
        pins = self.load()
        pins.discard(session_id)
        self.save(pins)

    def is_pinned(self, session_id: str) -> bool:
        return session_id in self.load()
