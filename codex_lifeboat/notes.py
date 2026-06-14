from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig


@dataclass(frozen=True)
class SessionNote:
    text: str
    updated_at: str


class NotesStore:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    @property
    def path(self) -> Path:
        return self.config.config_dir / "notes.json"

    def key(self, agent_key: str, session_id: str) -> str:
        return f"{agent_key}:{session_id}"

    def load(self) -> dict[str, SessionNote]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, dict):
            return {}
        notes: dict[str, SessionNote] = {}
        for key, value in data.items():
            if not isinstance(value, dict):
                continue
            text = str(value.get("text") or "").strip()
            updated_at = str(value.get("updated_at") or "")
            if text:
                notes[str(key)] = SessionNote(text=text, updated_at=updated_at)
        return notes

    def save(self, notes: dict[str, SessionNote]) -> None:
        payload = {
            key: {"text": note.text, "updated_at": note.updated_at}
            for key, note in sorted(notes.items())
            if note.text.strip()
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def get(self, agent_key: str, session_id: str) -> SessionNote | None:
        return self.load().get(self.key(agent_key, session_id))

    def set(self, agent_key: str, session_id: str, text: str) -> SessionNote | None:
        notes = self.load()
        key = self.key(agent_key, session_id)
        text = text.strip()
        if not text:
            notes.pop(key, None)
            self.save(notes)
            return None
        note = SessionNote(text=text, updated_at=dt.datetime.now(dt.timezone.utc).isoformat())
        notes[key] = note
        self.save(notes)
        return note

    def clear(self, agent_key: str, session_id: str) -> None:
        notes = self.load()
        notes.pop(self.key(agent_key, session_id), None)
        self.save(notes)
