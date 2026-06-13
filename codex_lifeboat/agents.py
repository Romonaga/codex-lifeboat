from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .claude import ClaudeSessionStore
from .config import AppConfig
from .sessions import SessionStore


class SessionBackend(Protocol):
    key: str
    display_name: str
    home_label: str
    session_file_label: str

    def all(self) -> list[dict]: ...
    def search(self, marker: str, *, scan_content: bool = False, limit: int = 100) -> list[dict]: ...
    def size(self, row: dict) -> int: ...
    def session_file_path(self, row: dict): ...
    def has_session_file(self, row: dict) -> bool: ...
    def file_status(self, row: dict) -> str: ...
    def total_session_file_size(self) -> int: ...
    def log_dbs(self) -> list: ...


@dataclass(frozen=True)
class AgentChoice:
    key: str
    display_name: str
    available: bool
    detail: str


def build_store(config: AppConfig, key: str) -> SessionBackend:
    if key == "claude":
        return ClaudeSessionStore(config)
    return SessionStore(config)


def detect_agents(config: AppConfig) -> list[AgentChoice]:
    codex_available = config.codex_home.exists()
    claude_available = config.claude_home.exists()
    return [
        AgentChoice(
            key="codex",
            display_name="Codex",
            available=codex_available,
            detail=str(config.codex_home),
        ),
        AgentChoice(
            key="claude",
            display_name="Claude",
            available=claude_available,
            detail=str(config.claude_home),
        ),
    ]


def default_agent(config: AppConfig) -> str:
    choices = detect_agents(config)
    for choice in choices:
        if choice.available:
            return choice.key
    return "codex"
