from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator

SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9_]{16,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{16,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}\b"),
    re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{16,}"),
]
SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|authorization)\b"
    r"(\s*[:=]\s*)(\S+)"
)
PATH_PATTERN = re.compile(r"(?<![\w.-])(?:/[\w.@%+=:,~/-]+|~[/\w.@%+=:,~-]+)")
COMMAND_PATTERN = re.compile(
    r"(?m)^\s*(?:(?:cd|git|gh|python3?|pipx?|npm|pnpm|yarn|cargo|go|docker|sudo|pytest|make|verlyn)(?:\s|$)|\./)[^\n]*"
)
BLOCKER_PATTERN = re.compile(
    r"(?i)\b(blocked|blocker|failed|failure|timeout|timed out|error|auth|permission|denied|next step|todo|remaining)\b"
)


def human_size(size: int) -> str:
    units = ["B", "K", "M", "G", "T"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024
    return f"{size}B"


def ellipsize(text: Any, width: int) -> str:
    value = str(text or "").replace("\n", " ").strip()
    if width <= 0:
        return ""
    if len(value) <= width:
        return value
    if width <= 3:
        return value[:width]
    return value[: width - 3] + "..."


def truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return f"{text[:max_chars]}\n\n[... truncated {omitted} characters ...]"


def redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(lambda match: (match.group(1) if match.lastindex else "") + "[REDACTED]", text)
    return SENSITIVE_ASSIGNMENT.sub(r"\1\2[REDACTED]", text)


def clean_text(text: str, *, max_chars: int, do_redact: bool) -> str:
    if do_redact:
        text = redact(text)
    return truncate(text.rstrip(), max_chars)


def content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "\n".join(parts)


def format_block(text: str) -> str:
    return text.replace("\n```", "\n` ` `")


def iter_jsonl(path: Path) -> Iterator[tuple[int, dict[str, Any], str]]:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, 1):
            raw = line.rstrip("\n")
            if not raw:
                continue
            try:
                yield line_no, json.loads(raw), raw
            except json.JSONDecodeError as exc:
                yield line_no, {"type": "parse_error", "error": str(exc), "raw": raw[:500]}, raw


def is_internal_user_message(text: str) -> bool:
    return any(marker in text for marker in ("<environment_context>", "<turn_aborted>"))


def is_lifeboat_injection(obj: dict[str, Any] | None, text: str = "") -> bool:
    if not isinstance(obj, dict):
        return text.lstrip().startswith("Injected Agent Lifeboat recovery note.")
    if obj.get("agent_lifeboat_injection"):
        return True
    payload = obj.get("payload")
    if isinstance(payload, dict) and payload.get("agent_lifeboat_injection"):
        return True
    return text.lstrip().startswith("Injected Agent Lifeboat recovery note.")


def add_unique(items: list[str], value: str, *, limit: int, max_chars: int = 600) -> None:
    value = clean_text(value, max_chars=max_chars, do_redact=True).strip()
    if not value or value in items:
        return
    items.append(value)
    if len(items) > limit:
        del items[0 : len(items) - limit]


def collect_paths(text: str, paths: list[str], *, limit: int) -> None:
    for match in PATH_PATTERN.finditer(text):
        value = match.group(0).strip(".,);]}'\"")
        if value.startswith("//") or value == "/tmp" or value.startswith(("/tmp/", "/proc/", "/tmp/systemd-private-")):
            continue
        if value.count("/") == 1:
            continue
        if re.fullmatch(r"/[0-9 =.,:-]+", value):
            continue
        if len(value) >= 3:
            add_unique(paths, value, limit=limit, max_chars=220)


def collect_commands(text: str, commands: list[str], *, limit: int) -> None:
    for match in COMMAND_PATTERN.finditer(text):
        command = match.group(0).strip()
        if re.match(r"^\w+_(?:sha|branch|url|path|id|name)\b", command):
            continue
        add_unique(commands, command, limit=limit, max_chars=500)


def collect_blockers(text: str, blockers: list[str], *, limit: int) -> None:
    for line in text.splitlines():
        if line.lstrip().startswith("feedback_log_body ="):
            continue
        if BLOCKER_PATTERN.search(line):
            add_unique(blockers, line.strip(), limit=limit, max_chars=500)
