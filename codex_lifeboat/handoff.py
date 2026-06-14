from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import AppConfig
from .claude import iter_claude_messages
from .sessions import iso_from_epoch
from .text import (
    SECRET_PATTERNS,
    SENSITIVE_ASSIGNMENT,
    add_unique,
    clean_text,
    collect_blockers,
    collect_commands,
    collect_paths,
    content_to_text,
    format_block,
    human_size,
    is_internal_user_message,
    is_lifeboat_injection,
    iter_jsonl,
)


@dataclass(frozen=True)
class HandoffOptions:
    include_tools: bool = False
    tool_chars: int = 2000
    message_chars: int = 12000
    keep_system: bool = False
    redact: bool = True
    raw_tail: int = 0


@dataclass(frozen=True)
class WriteResult:
    path: Path
    messages: int
    tool_calls: int
    tool_outputs: int
    split_parts: list[Path]


def default_output_path(config: AppConfig, session_id: str, *, summary: bool, agent_key: str = "codex") -> Path:
    suffix = "summary" if summary else "handoff"
    prefix = "" if agent_key == "codex" else f"{agent_key}-"
    return config.output_dir / f"{prefix}{session_id}-{suffix}.md"


def write_bullets(out: Any, title: str, values: list[str], *, empty: str = "None captured.") -> None:
    out.write(f"### {title}\n\n")
    if not values:
        out.write(f"{empty}\n\n")
        return
    for value in values:
        out.write("- ")
        out.write(format_block(value).replace("\n", "\n  "))
        out.write("\n")
    out.write("\n")


def snapshot_command_text(payload: dict[str, Any]) -> str:
    args = payload.get("arguments", "")
    if not isinstance(args, str):
        return ""
    try:
        parsed = json.loads(args)
    except json.JSONDecodeError:
        return ""
    if not isinstance(parsed, dict):
        return ""
    command = parsed.get("cmd") or parsed.get("command")
    if not command:
        return ""
    text = str(command)
    if parsed.get("workdir"):
        text += f"\n  cwd: {parsed['workdir']}"
    return text


def collect_continuation_snapshot(*, rollout_path: Path, message_chars: int, do_redact: bool) -> dict[str, list[str]]:
    user_requests: list[str] = []
    assistant_results: list[str] = []
    commands: list[str] = []
    paths: list[str] = []
    blockers: list[str] = []

    for _line_no, obj, _raw in iter_jsonl(rollout_path):
        if is_lifeboat_injection(obj):
            continue
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
            cleaned = clean_text(text, max_chars=message_chars, do_redact=do_redact)
            if role == "user":
                add_unique(user_requests, cleaned, limit=8, max_chars=1000)
            elif role == "assistant":
                add_unique(assistant_results, cleaned, limit=8, max_chars=1000)
            collect_paths(cleaned, paths, limit=30)
            collect_commands(cleaned, commands, limit=12)
            collect_blockers(cleaned, blockers, limit=20)
        elif item_type == "function_call":
            text = clean_text(snapshot_command_text(payload), max_chars=2000, do_redact=do_redact)
            if not text:
                continue
            add_unique(commands, text, limit=12, max_chars=1000)
            collect_paths(text, paths, limit=30)
            collect_commands(text, commands, limit=12)
            collect_blockers(text, blockers, limit=20)
    return {
        "user_requests": user_requests,
        "assistant_results": assistant_results,
        "commands": commands,
        "paths": paths,
        "blockers": blockers,
    }


def write_handoff(
    *,
    session_id: str,
    rollout_path: Path,
    metadata: dict[str, Any],
    output_path: Path,
    options: HandoffOptions,
    split_chars: int = 0,
) -> WriteResult:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    counts = {"messages": 0, "tool_calls": 0, "tool_outputs": 0}
    tail_lines: list[str] = []
    snapshot = collect_continuation_snapshot(
        rollout_path=rollout_path,
        message_chars=options.message_chars,
        do_redact=options.redact,
    )
    with output_path.open("w", encoding="utf-8") as out:
        out.write("# Codex Session Handoff\n\n")
        out.write("Paste this into a new Codex session to restore the useful context.\n\n")
        out.write("## Session\n\n")
        out.write(f"- Session ID: `{session_id}`\n")
        out.write(f"- Session file: `{rollout_path}`\n")
        out.write(f"- File size: `{rollout_path.stat().st_size:,}` bytes\n")
        if metadata:
            out.write(f"- Title: {metadata.get('title') or ''}\n")
            out.write(f"- CWD: `{metadata.get('cwd') or ''}`\n")
            out.write(f"- Model: `{metadata.get('model') or ''}`\n")
            out.write(f"- Reasoning effort: `{metadata.get('reasoning_effort') or ''}`\n")
            updated = iso_from_epoch(metadata.get("updated_at"))
            if updated:
                out.write(f"- Updated: `{updated}`\n")
        out.write("\n## Continuation Snapshot\n\n")
        out.write("Read this first. It is extracted from the session file so a resumed session can recover the latest working state before scanning the full chronological conversation.\n\n")
        write_bullets(out, "Latest User Requests", snapshot["user_requests"])
        write_bullets(out, "Latest Assistant Results", snapshot["assistant_results"])
        write_bullets(out, "Recent Commands", snapshot["commands"])
        write_bullets(out, "Important Paths", snapshot["paths"])
        write_bullets(out, "Blockers And Next Steps", snapshot["blockers"])
        out.write("\n## Restart Prompt\n\n")
        out.write("I am continuing from a previous Codex session. Use the handoff below as context. Start with the Continuation Snapshot, then use the full conversation only as needed. Preserve the decisions, constraints, commands, paths, and unresolved next steps.\n\n")
        out.write("## Conversation\n\n")

        for line_no, obj, raw in iter_jsonl(rollout_path):
            if is_lifeboat_injection(obj):
                continue
            if options.raw_tail:
                tail_lines.append(raw)
                if len(tail_lines) > options.raw_tail:
                    tail_lines.pop(0)
            payload = obj.get("payload") if isinstance(obj, dict) else None
            if not isinstance(payload, dict):
                continue
            if obj.get("type") == "session_meta":
                out.write("### Session Metadata\n\n")
                out.write(f"- Codex session id: `{payload.get('id')}`\n")
                out.write(f"- Created: `{payload.get('timestamp')}`\n")
                out.write(f"- CWD: `{payload.get('cwd')}`\n")
                out.write(f"- CLI version: `{payload.get('cli_version')}`\n\n")
                continue
            if obj.get("type") != "response_item":
                continue
            item_type = payload.get("type")
            if item_type == "message":
                role = payload.get("role", "unknown")
                if role in {"system", "developer"} and not options.keep_system:
                    continue
                text = content_to_text(payload.get("content"))
                if not text.strip():
                    continue
                label = str(role)
                if payload.get("phase"):
                    label += f" / {payload.get('phase')}"
                text = clean_text(text, max_chars=options.message_chars, do_redact=options.redact)
                out.write(f"### {label} (line {line_no})\n\n")
                out.write(format_block(text))
                out.write("\n\n")
                counts["messages"] += 1
            elif item_type == "function_call":
                args = clean_text(str(payload.get("arguments", "")), max_chars=options.message_chars, do_redact=options.redact)
                out.write(f"### tool call: {payload.get('name', 'tool')} (line {line_no})\n\n")
                if payload.get("call_id"):
                    out.write(f"- Call ID: `{payload.get('call_id')}`\n\n")
                out.write("```json\n")
                out.write(format_block(args))
                out.write("\n```\n\n")
                counts["tool_calls"] += 1
            elif item_type == "function_call_output":
                counts["tool_outputs"] += 1
                if not options.include_tools:
                    continue
                text = clean_text(str(payload.get("output", "")), max_chars=options.tool_chars, do_redact=options.redact)
                out.write(f"### tool output (line {line_no})\n\n")
                if payload.get("call_id"):
                    out.write(f"- Call ID: `{payload.get('call_id')}`\n\n")
                out.write("```text\n")
                out.write(format_block(text))
                out.write("\n```\n\n")

        if options.raw_tail and tail_lines:
            out.write("## Raw Tail\n\n```jsonl\n")
            for line in tail_lines:
                out.write(format_block(clean_text(line, max_chars=options.message_chars, do_redact=options.redact)))
                out.write("\n")
            out.write("```\n")
    return WriteResult(output_path, counts["messages"], counts["tool_calls"], counts["tool_outputs"], split_markdown(output_path, split_chars))


def function_arguments_text(payload: dict[str, Any]) -> str:
    args = payload.get("arguments", "")
    if not isinstance(args, str):
        return str(args)
    try:
        parsed = json.loads(args)
    except json.JSONDecodeError:
        return args
    if isinstance(parsed, dict):
        useful = []
        for key in ("cmd", "command", "workdir", "path", "file", "query", "ref_id"):
            if parsed.get(key):
                useful.append(f"{key}: {parsed[key]}")
        return "\n".join(useful) if useful else json.dumps(parsed, ensure_ascii=False)
    return args


def write_summary(
    *,
    session_id: str,
    rollout_path: Path,
    metadata: dict[str, Any],
    output_path: Path,
    message_chars: int = 12000,
    redact: bool = True,
    split_chars: int = 0,
) -> WriteResult:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    user_goals: list[str] = []
    assistant_notes: list[str] = []
    commands: list[str] = []
    paths: list[str] = []
    blockers: list[str] = []
    recent_turns: list[str] = []
    counts = {"messages": 0, "tool_calls": 0, "tool_outputs": 0}

    for line_no, obj, _raw in iter_jsonl(rollout_path):
        if is_lifeboat_injection(obj):
            continue
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
            cleaned = clean_text(text, max_chars=message_chars, do_redact=redact)
            if role == "user":
                add_unique(user_goals, cleaned, limit=30, max_chars=900)
            elif role == "assistant":
                add_unique(assistant_notes, cleaned, limit=20, max_chars=900)
            add_unique(recent_turns, f"{role} line {line_no}: {cleaned}", limit=24, max_chars=900)
            collect_paths(cleaned, paths, limit=60)
            collect_commands(cleaned, commands, limit=60)
            collect_blockers(cleaned, blockers, limit=40)
            counts["messages"] += 1
        elif item_type == "function_call":
            name = str(payload.get("name") or "tool")
            text = clean_text(function_arguments_text(payload), max_chars=3000, do_redact=redact)
            add_unique(recent_turns, f"tool call {name} line {line_no}: {text}", limit=24, max_chars=900)
            collect_paths(text, paths, limit=60)
            collect_commands(text, commands, limit=60)
            collect_blockers(text, blockers, limit=40)
            counts["tool_calls"] += 1
        elif item_type == "function_call_output":
            text = clean_text(str(payload.get("output", "")), max_chars=3000, do_redact=redact)
            collect_paths(text, paths, limit=60)
            collect_commands(text, commands, limit=60)
            collect_blockers(text, blockers, limit=40)
            counts["tool_outputs"] += 1

    with output_path.open("w", encoding="utf-8") as out:
        out.write("# Codex Recovery Summary\n\nPaste this into a new Codex session when the original session is too large to resume.\n\n")
        out.write("## Restart Prompt\n\n")
        out.write("I am recovering from a previous Codex session. Use this summary as working context. Continue from the listed goals, preserve the file paths and constraints, and resolve the remaining blockers first.\n\n")
        out.write("## Session\n\n")
        out.write(f"- Session ID: `{session_id}`\n")
        out.write(f"- Session file: `{rollout_path}`\n")
        out.write(f"- File size: `{human_size(rollout_path.stat().st_size) if rollout_path.exists() else 'missing'}`\n")
        if metadata:
            out.write(f"- Title: {metadata.get('title') or ''}\n")
            out.write(f"- CWD: `{metadata.get('cwd') or ''}`\n")
            if iso_from_epoch(metadata.get("updated_at")):
                out.write(f"- Updated: `{iso_from_epoch(metadata.get('updated_at'))}`\n")
        out.write("\n")
        sections = [
            ("User Goals And Requests", user_goals),
            ("Recent Assistant Context", assistant_notes),
            ("Commands Seen", commands),
            ("Important Paths", paths),
            ("Blockers And Next Steps", blockers),
            ("Recent Turns", recent_turns),
        ]
        for title, values in sections:
            out.write(f"## {title}\n\n")
            if not values:
                out.write("None captured.\n\n")
                continue
            for value in values:
                out.write("- ")
                out.write(format_block(value).replace("\n", "\n  "))
                out.write("\n")
            out.write("\n")
    return WriteResult(output_path, counts["messages"], counts["tool_calls"], counts["tool_outputs"], split_markdown(output_path, split_chars))


def collect_claude_snapshot(*, session_file_path: Path, message_chars: int, do_redact: bool) -> dict[str, list[str]]:
    user_requests: list[str] = []
    assistant_results: list[str] = []
    commands: list[str] = []
    paths: list[str] = []
    blockers: list[str] = []

    for _line_no, role, text, _obj, _raw in iter_claude_messages(session_file_path):
        if not text.strip():
            continue
        cleaned = clean_text(text, max_chars=message_chars, do_redact=do_redact)
        if role == "user":
            add_unique(user_requests, cleaned, limit=8, max_chars=1000)
        elif role == "assistant":
            if cleaned.startswith("tool call:"):
                add_unique(commands, cleaned, limit=12, max_chars=1000)
            else:
                add_unique(assistant_results, cleaned, limit=8, max_chars=1000)
        collect_paths(cleaned, paths, limit=30)
        collect_commands(cleaned, commands, limit=12)
        collect_blockers(cleaned, blockers, limit=20)
    return {
        "user_requests": user_requests,
        "assistant_results": assistant_results,
        "commands": commands,
        "paths": paths,
        "blockers": blockers,
    }


def write_claude_handoff(
    *,
    session_id: str,
    session_file_path: Path,
    metadata: dict[str, Any],
    output_path: Path,
    options: HandoffOptions,
    split_chars: int = 0,
) -> WriteResult:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    counts = {"messages": 0, "tool_calls": 0, "tool_outputs": 0}
    tail_lines: list[str] = []
    snapshot = collect_claude_snapshot(
        session_file_path=session_file_path,
        message_chars=options.message_chars,
        do_redact=options.redact,
    )
    with output_path.open("w", encoding="utf-8") as out:
        out.write("# Claude Session Handoff\n\n")
        out.write("Paste this into a new AI session to restore the useful context.\n\n")
        out.write("## Session\n\n")
        out.write(f"- Agent: `Claude`\n")
        out.write(f"- Session ID: `{session_id}`\n")
        out.write(f"- Session file: `{session_file_path}`\n")
        out.write(f"- File size: `{session_file_path.stat().st_size:,}` bytes\n")
        if metadata:
            out.write(f"- Title: {metadata.get('title') or ''}\n")
            out.write(f"- CWD: `{metadata.get('cwd') or ''}`\n")
            out.write(f"- Model: `{metadata.get('model') or ''}`\n")
            out.write(f"- Claude Code version: `{metadata.get('version') or ''}`\n")
            updated = iso_from_epoch(metadata.get("updated_at"))
            if updated:
                out.write(f"- Updated: `{updated}`\n")
        out.write("\n## Continuation Snapshot\n\n")
        out.write("Read this first. It is extracted from the Claude session file so a resumed session can recover the latest working state before scanning the full chronological conversation.\n\n")
        write_bullets(out, "Latest User Requests", snapshot["user_requests"])
        write_bullets(out, "Latest Assistant Results", snapshot["assistant_results"])
        write_bullets(out, "Recent Commands", snapshot["commands"])
        write_bullets(out, "Important Paths", snapshot["paths"])
        write_bullets(out, "Blockers And Next Steps", snapshot["blockers"])
        out.write("\n## Restart Prompt\n\n")
        out.write("I am continuing from a previous Claude session. Use the handoff below as context. Start with the Continuation Snapshot, then use the full conversation only as needed. Preserve the decisions, constraints, commands, paths, and unresolved next steps.\n\n")
        out.write("## Conversation\n\n")

        for line_no, role, text, _obj, raw in iter_claude_messages(session_file_path):
            if options.raw_tail:
                tail_lines.append(raw)
                if len(tail_lines) > options.raw_tail:
                    tail_lines.pop(0)
            if not text.strip():
                continue
            cleaned = clean_text(text, max_chars=options.tool_chars if text.startswith("tool call:") else options.message_chars, do_redact=options.redact)
            if text.startswith("tool call:"):
                counts["tool_calls"] += 1
                if not options.include_tools:
                    continue
                out.write(f"### tool call (line {line_no})\n\n")
            elif role == "user" and "tool_result" in raw:
                counts["tool_outputs"] += 1
                if not options.include_tools:
                    continue
                out.write(f"### tool output (line {line_no})\n\n")
            else:
                counts["messages"] += 1
                out.write(f"### {role} (line {line_no})\n\n")
            out.write(format_block(cleaned))
            out.write("\n\n")

        if options.raw_tail and tail_lines:
            out.write("## Raw Tail\n\n```jsonl\n")
            for line in tail_lines:
                out.write(format_block(clean_text(line, max_chars=options.message_chars, do_redact=options.redact)))
                out.write("\n")
            out.write("```\n")
    return WriteResult(output_path, counts["messages"], counts["tool_calls"], counts["tool_outputs"], split_markdown(output_path, split_chars))


def write_claude_summary(
    *,
    session_id: str,
    session_file_path: Path,
    metadata: dict[str, Any],
    output_path: Path,
    message_chars: int = 12000,
    redact: bool = True,
    split_chars: int = 0,
) -> WriteResult:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    user_goals: list[str] = []
    assistant_notes: list[str] = []
    commands: list[str] = []
    paths: list[str] = []
    blockers: list[str] = []
    recent_turns: list[str] = []
    counts = {"messages": 0, "tool_calls": 0, "tool_outputs": 0}

    for line_no, role, text, _obj, raw in iter_claude_messages(session_file_path):
        if not text.strip():
            continue
        cleaned = clean_text(text, max_chars=message_chars, do_redact=redact)
        if text.startswith("tool call:"):
            add_unique(commands, cleaned, limit=60, max_chars=900)
            counts["tool_calls"] += 1
        elif role == "user" and "tool_result" in raw:
            counts["tool_outputs"] += 1
        elif role == "user":
            add_unique(user_goals, cleaned, limit=30, max_chars=900)
            counts["messages"] += 1
        elif role == "assistant":
            add_unique(assistant_notes, cleaned, limit=20, max_chars=900)
            counts["messages"] += 1
        add_unique(recent_turns, f"{role} line {line_no}: {cleaned}", limit=24, max_chars=900)
        collect_paths(cleaned, paths, limit=60)
        collect_commands(cleaned, commands, limit=60)
        collect_blockers(cleaned, blockers, limit=40)

    with output_path.open("w", encoding="utf-8") as out:
        out.write("# Claude Recovery Summary\n\nPaste this into a new AI session when the original Claude session is too large to resume.\n\n")
        out.write("## Restart Prompt\n\n")
        out.write("I am recovering from a previous Claude session. Use this summary as working context. Continue from the listed goals, preserve the file paths and constraints, and resolve the remaining blockers first.\n\n")
        out.write("## Session\n\n")
        out.write(f"- Agent: `Claude`\n")
        out.write(f"- Session ID: `{session_id}`\n")
        out.write(f"- Session file: `{session_file_path}`\n")
        out.write(f"- File size: `{human_size(session_file_path.stat().st_size) if session_file_path.exists() else 'missing'}`\n")
        if metadata:
            out.write(f"- Title: {metadata.get('title') or ''}\n")
            out.write(f"- CWD: `{metadata.get('cwd') or ''}`\n")
            if iso_from_epoch(metadata.get("updated_at")):
                out.write(f"- Updated: `{iso_from_epoch(metadata.get('updated_at'))}`\n")
        out.write("\n")
        sections = [
            ("User Goals And Requests", user_goals),
            ("Recent Assistant Context", assistant_notes),
            ("Commands Seen", commands),
            ("Important Paths", paths),
            ("Blockers And Next Steps", blockers),
            ("Recent Turns", recent_turns),
        ]
        for title, values in sections:
            out.write(f"## {title}\n\n")
            if not values:
                out.write("None captured.\n\n")
                continue
            for value in values:
                out.write("- ")
                out.write(format_block(value).replace("\n", "\n  "))
                out.write("\n")
            out.write("\n")
    return WriteResult(output_path, counts["messages"], counts["tool_calls"], counts["tool_outputs"], split_markdown(output_path, split_chars))


def split_markdown(path: Path, chunk_size: int) -> list[Path]:
    if chunk_size <= 0 or not path.exists() or path.stat().st_size <= chunk_size:
        return []
    parts: list[Path] = []
    part_no = 1
    current_size = 0
    current_path = path.with_name(f"{path.stem}.part-{part_no:03d}{path.suffix}")
    current = current_path.open("w", encoding="utf-8")
    parts.append(current_path)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as source:
            for line in source:
                encoded_size = len(line.encode("utf-8"))
                if current_size and current_size + encoded_size > chunk_size:
                    current.close()
                    part_no += 1
                    current_path = path.with_name(f"{path.stem}.part-{part_no:03d}{path.suffix}")
                    current = current_path.open("w", encoding="utf-8")
                    parts.append(current_path)
                    current_size = 0
                current.write(line)
                current_size += encoded_size
    finally:
        current.close()
    return parts


def scan_secrets(path: Path) -> list[str]:
    if not path.exists():
        raise SystemExit(f"File not found: {path}")
    findings: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, 1):
            for idx, pattern in enumerate(SECRET_PATTERNS, 1):
                if pattern.search(line):
                    findings.append(f"{path}:{line_no}: possible secret pattern #{idx}")
            if SENSITIVE_ASSIGNMENT.search(line):
                findings.append(f"{path}:{line_no}: possible sensitive assignment")
    return findings
