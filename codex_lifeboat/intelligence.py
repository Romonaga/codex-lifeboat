from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import ArtifactHistory
from .claude import iter_claude_messages
from .sessions import iso_from_epoch
from .text import (
    add_unique,
    clean_text,
    collect_blockers,
    collect_commands,
    collect_paths,
    content_to_text,
    human_size,
    is_internal_user_message,
    iter_jsonl,
)


@dataclass(frozen=True)
class TranscriptPreview:
    latest_user: str = ""
    latest_assistant: str = ""
    commands: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    message_count: int = 0
    tool_call_count: int = 0
    tool_output_count: int = 0


@dataclass(frozen=True)
class RecoveryReadiness:
    label: str
    rank: int
    reasons: tuple[str, ...]
    next_actions: tuple[str, ...]


FILTER_RE = re.compile(r"(?P<key>agent|project|cwd|model|status|file|artifact|after|before):(?P<value>\S+)", re.I)


def project_key(row: dict[str, Any]) -> str:
    cwd = str(row.get("cwd") or "").strip()
    if cwd:
        return cwd
    path = str(row.get("session_file_path") or row.get("rollout_path") or "").strip()
    if not path:
        return "(unknown project)"
    candidate = Path(path).expanduser()
    for parent in candidate.parents:
        if parent.name in {"projects", "sessions"}:
            break
        if parent.name:
            return str(parent)
    return str(candidate.parent) if candidate.parent else "(unknown project)"


def project_label(row: dict[str, Any], *, max_chars: int = 36) -> str:
    value = project_key(row)
    if value == "(unknown project)":
        return value
    name = Path(value).name if "/" in value else value
    if not name:
        name = value
    return name[: max_chars - 3] + "..." if len(name) > max_chars else name


def analyze_transcript(agent_key: str, session_file_path: Path | None) -> TranscriptPreview:
    if not session_file_path or not session_file_path.is_file():
        return TranscriptPreview()
    if agent_key == "claude":
        return analyze_claude_transcript(session_file_path)
    return analyze_codex_transcript(session_file_path)


def analyze_codex_transcript(path: Path) -> TranscriptPreview:
    latest_user = ""
    latest_assistant = ""
    commands: list[str] = []
    paths: list[str] = []
    blockers: list[str] = []
    message_count = 0
    tool_call_count = 0
    tool_output_count = 0
    for _line_no, obj, _raw in iter_jsonl(path):
        payload = obj.get("payload") if isinstance(obj, dict) else None
        if not isinstance(payload, dict) or obj.get("type") != "response_item":
            continue
        item_type = payload.get("type")
        if item_type == "message":
            role = str(payload.get("role") or "unknown")
            if role in {"system", "developer"}:
                continue
            text = content_to_text(payload.get("content")).strip()
            if not text or (role == "user" and is_internal_user_message(text)):
                continue
            cleaned = clean_text(text, max_chars=1200, do_redact=True)
            message_count += 1
            if role == "user":
                latest_user = cleaned
            elif role == "assistant":
                latest_assistant = cleaned
            collect_paths(cleaned, paths, limit=12)
            collect_commands(cleaned, commands, limit=10)
            collect_blockers(cleaned, blockers, limit=10)
        elif item_type == "function_call":
            tool_call_count += 1
            collect_commands(str(payload.get("arguments") or ""), commands, limit=10)
        elif item_type == "function_call_output":
            tool_output_count += 1
    return TranscriptPreview(
        latest_user=latest_user,
        latest_assistant=latest_assistant,
        commands=tuple(commands),
        paths=tuple(paths),
        blockers=tuple(blockers),
        message_count=message_count,
        tool_call_count=tool_call_count,
        tool_output_count=tool_output_count,
    )


def analyze_claude_transcript(path: Path) -> TranscriptPreview:
    latest_user = ""
    latest_assistant = ""
    commands: list[str] = []
    paths: list[str] = []
    blockers: list[str] = []
    message_count = 0
    tool_call_count = 0
    tool_output_count = 0
    for _line_no, role, text, _obj, raw in iter_claude_messages(path):
        if not text.strip():
            continue
        cleaned = clean_text(text, max_chars=1200, do_redact=True)
        if text.startswith("tool call:"):
            tool_call_count += 1
            add_unique(commands, cleaned, limit=10, max_chars=500)
        elif role == "user" and "tool_result" in raw:
            tool_output_count += 1
        else:
            message_count += 1
            if role == "user":
                latest_user = cleaned
            elif role == "assistant":
                latest_assistant = cleaned
        collect_paths(cleaned, paths, limit=12)
        collect_commands(cleaned, commands, limit=10)
        collect_blockers(cleaned, blockers, limit=10)
    return TranscriptPreview(
        latest_user=latest_user,
        latest_assistant=latest_assistant,
        commands=tuple(commands),
        paths=tuple(paths),
        blockers=tuple(blockers),
        message_count=message_count,
        tool_call_count=tool_call_count,
        tool_output_count=tool_output_count,
    )


def recovery_readiness(
    *,
    row: dict[str, Any],
    has_session_file: bool,
    file_status: str,
    size: int,
    artifacts: ArtifactHistory,
    pinned: bool,
) -> RecoveryReadiness:
    reasons: list[str] = []
    actions: list[str] = []
    tokens = int(row.get("tokens_used") or 0)
    if not has_session_file:
        reasons.append(f"session file {file_status.lower()}")
        actions.append("recover or restore the session JSONL before handoff/archive")
        return RecoveryReadiness("Missing", 0, tuple(reasons), tuple(actions))
    if artifacts.has_handoff:
        reasons.append("handoff exists")
    else:
        reasons.append("handoff not generated yet")
        actions.append("write a full handoff")
    if artifacts.has_archive:
        reasons.append("archive exists")
    else:
        actions.append("archive before purge if long-term recovery matters")
    if size >= 100 * 1024 * 1024:
        reasons.append(f"very large session file ({human_size(size)})")
        actions.append("prefer compact summary or resume package")
    elif size >= 25 * 1024 * 1024:
        reasons.append(f"large session file ({human_size(size)})")
    if tokens >= 1_000_000:
        reasons.append(f"high token counter ({tokens:,})")
    if pinned:
        reasons.append("pinned")
    if artifacts.has_handoff and artifacts.has_archive:
        return RecoveryReadiness("Ready", 3, tuple(reasons), tuple(actions or ["safe to keep or purge when intended"]))
    if artifacts.has_handoff or artifacts.has_summary:
        return RecoveryReadiness("Partial", 2, tuple(reasons), tuple(actions))
    return RecoveryReadiness("Needs handoff", 1, tuple(reasons), tuple(actions))


def parse_filters(query: str) -> tuple[dict[str, str], str]:
    filters: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        filters[match.group("key").lower()] = match.group("value").lower()
        return " "

    text = FILTER_RE.sub(replace, query).strip().lower()
    return filters, text


def row_matches_filters(
    row: dict[str, Any],
    *,
    agent_key: str,
    readiness: RecoveryReadiness,
    artifacts: ArtifactHistory,
    filters: dict[str, str],
    text_query: str,
) -> bool:
    fields = {
        "agent": agent_key,
        "project": project_key(row).lower(),
        "cwd": str(row.get("cwd") or "").lower(),
        "model": str(row.get("model") or "").lower(),
        "status": readiness.label.lower(),
        "file": str(row.get("session_file_path") or row.get("rollout_path") or "").lower(),
        "artifact": artifacts.label().lower(),
        "updated": iso_from_epoch(row.get("updated_at")).lower(),
    }
    for key, value in filters.items():
        if key == "artifact":
            wanted = value[:1]
            if wanted not in fields["artifact"]:
                return False
            continue
        if value not in fields.get(key, ""):
            return False
    if not text_query:
        return True
    haystack = "\n".join(
        str(row.get(key) or "")
        for key in ("id", "title", "preview", "cwd", "session_file_path", "rollout_path", "model", "version")
    ).lower()
    haystack += "\n" + fields["project"] + "\n" + readiness.label.lower()
    return all(part in haystack for part in text_query.split())
