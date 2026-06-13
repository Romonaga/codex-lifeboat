from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from .config import AppConfig
from .sessions import iso_from_epoch
from .text import clean_text, content_to_text, is_internal_user_message

UUID_RE = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.I)


def epoch_from_iso(value: Any) -> int:
    if not value:
        return 0
    try:
        text = str(value).replace("Z", "+00:00")
        return int(dt.datetime.fromisoformat(text).timestamp())
    except ValueError:
        return 0


def extract_session_id(path: Path) -> str:
    match = UUID_RE.search(path.name)
    return match.group(1) if match else path.stem


def project_dir_to_cwd(project_dir: Path) -> str:
    name = project_dir.name
    if not name.startswith("-"):
        return ""
    return name.replace("-", "/", 1).replace("-", "/")


def claude_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return content_to_text(content)

    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            parts.append(str(block))
            continue
        block_type = block.get("type")
        if block_type == "text":
            parts.append(str(block.get("text") or ""))
        elif block_type == "tool_use":
            name = block.get("name") or "tool"
            tool_input = block.get("input")
            if tool_input:
                parts.append(f"tool call: {name}\n{json.dumps(tool_input, ensure_ascii=False, indent=2)}")
            else:
                parts.append(f"tool call: {name}")
        elif block_type == "tool_result":
            result = block.get("content")
            if isinstance(result, str):
                parts.append(result)
            else:
                parts.append(content_to_text(result))
    return "\n".join(part for part in parts if part).strip()


def is_claude_internal_text(text: str) -> bool:
    stripped = text.strip()
    if is_internal_user_message(stripped):
        return True
    return stripped.startswith(("<local-command-", "<command-name>", "<system-reminder>"))


def iter_claude_jsonl(path: Path):
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield line_no, json.loads(line), line
            except json.JSONDecodeError:
                continue


def iter_claude_messages(path: Path):
    for line_no, obj, raw in iter_claude_jsonl(path):
        if obj.get("isMeta") or obj.get("type") in {"file-history-snapshot", "progress", "system"}:
            continue
        message = obj.get("message")
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or obj.get("type") or "unknown")
        text = claude_content_to_text(message.get("content"))
        if role == "user" and is_claude_internal_text(text):
            continue
        yield line_no, role, text, obj, raw


class ClaudeSessionStore:
    key = "claude"
    display_name = "Claude"
    home_label = "Claude home"
    session_file_label = "Session file"

    def __init__(self, config: AppConfig):
        self.config = config

    def session_files(self) -> list[Path]:
        return sorted(self.config.claude_home.glob("projects/*/*.jsonl"))

    def log_dbs(self) -> list[Path]:
        return []

    def all(self) -> list[dict[str, Any]]:
        rows = [self.row_from_path(path) for path in self.session_files()]
        rows.sort(key=lambda row: row.get("updated_at") or 0, reverse=True)
        return rows

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.all()[:limit]

    def row_from_path(self, path: Path) -> dict[str, Any]:
        session_id = extract_session_id(path)
        updated_at = int(path.stat().st_mtime)
        cwd = project_dir_to_cwd(path.parent)
        title = ""
        preview = ""
        tokens_used = 0
        model = ""
        version = ""
        slug = ""

        for _line_no, role, text, obj, _raw in iter_claude_messages(path):
            if obj.get("cwd"):
                cwd = str(obj.get("cwd") or cwd)
            if obj.get("timestamp"):
                updated_at = max(updated_at, epoch_from_iso(obj.get("timestamp")))
            if obj.get("version"):
                version = str(obj.get("version") or "")
            if obj.get("slug"):
                slug = str(obj.get("slug") or "")
            message = obj.get("message") if isinstance(obj.get("message"), dict) else {}
            if isinstance(message, dict):
                if message.get("model"):
                    model = str(message.get("model") or "")
                usage = message.get("usage")
                if isinstance(usage, dict):
                    tokens_used += int(usage.get("input_tokens") or 0)
                    tokens_used += int(usage.get("output_tokens") or 0)
                    tokens_used += int(usage.get("cache_creation_input_tokens") or 0)
                    tokens_used += int(usage.get("cache_read_input_tokens") or 0)
            if text and not preview:
                preview = clean_text(text, max_chars=240, do_redact=True).replace("\n", " ")
            if role == "user" and text and not title:
                title = clean_text(text, max_chars=100, do_redact=True).replace("\n", " ")

        return {
            "agent": self.key,
            "id": session_id,
            "session_file_path": str(path),
            "rollout_path": str(path),
            "updated_at": updated_at,
            "cwd": cwd,
            "title": title or slug or "(Claude session)",
            "preview": preview,
            "tokens_used": tokens_used,
            "model": model,
            "version": version,
        }

    def size(self, row: dict[str, Any]) -> int:
        path = self.session_file_path(row)
        return path.stat().st_size if path and path.is_file() else 0

    def session_file_path(self, row: dict[str, Any]) -> Path | None:
        raw = str(row.get("session_file_path") or row.get("rollout_path") or "").strip()
        return Path(raw).expanduser() if raw else None

    def has_session_file(self, row: dict[str, Any]) -> bool:
        path = self.session_file_path(row)
        return bool(path and path.is_file())

    def file_status(self, row: dict[str, Any]) -> str:
        path = self.session_file_path(row)
        if path and path.is_file():
            return "Available"
        if path:
            return "Missing"
        return "Unknown"

    def total_session_file_size(self) -> int:
        total = 0
        for path in self.session_files():
            try:
                total += path.stat().st_size
            except OSError:
                pass
        return total

    def total_rollout_size(self) -> int:
        return self.total_session_file_size()

    def search(self, marker: str, *, scan_content: bool = False, limit: int = 100) -> list[dict[str, Any]]:
        needle = marker.lower()
        matches = []
        for row in self.all():
            haystack = "\n".join(
                str(row.get(key) or "") for key in ("id", "title", "preview", "cwd", "session_file_path", "model", "version")
            ).lower()
            if needle in haystack:
                matches.append(row)
            elif scan_content:
                path = self.session_file_path(row)
                if path and path.is_file():
                    try:
                        if needle in path.read_text(encoding="utf-8", errors="replace").lower():
                            matches.append(row)
                    except OSError:
                        pass
            if len(matches) >= limit:
                break
        matches.sort(key=lambda row: row.get("updated_at") or 0, reverse=True)
        return matches[:limit]

    def find(self, session: str) -> tuple[str, Path, dict[str, Any]]:
        raw = Path(session).expanduser()
        if raw.is_file():
            row = self.row_from_path(raw)
            return str(row["id"]), raw, row
        matches = [row for row in self.all() if session in str(row.get("id") or "")]
        if len(matches) == 1:
            row = matches[0]
            path = self.session_file_path(row)
            if path and path.is_file():
                return str(row["id"]), path, row
        if len(matches) > 1:
            choices = "\n".join(f"  {row['id']}  {row['title']}" for row in matches[:20])
            raise SystemExit(f"Session fragment matched multiple Claude sessions:\n{choices}")
        raise SystemExit(f"Could not find Claude session: {session}")


def format_claude_updated(row: dict[str, Any]) -> str:
    return iso_from_epoch(row.get("updated_at"))
