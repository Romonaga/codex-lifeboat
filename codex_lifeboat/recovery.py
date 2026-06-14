from __future__ import annotations

import datetime as dt
import json
import shutil
import tarfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from .config import AppConfig
from .handoff import (
    HandoffOptions,
    WriteResult,
    default_output_path,
    write_claude_handoff,
    write_claude_summary,
    write_handoff,
    write_summary,
)
from .operations import archive_session


SCRUB_PROFILES = ("private", "shareable", "public")
TARGET_AGENTS = ("same", "codex", "claude")


@dataclass(frozen=True)
class RecoveryContext:
    agent_key: str
    session_id: str
    session_file_path: Path
    metadata: dict[str, Any]


@dataclass(frozen=True)
class InjectionResult:
    session_file_path: Path
    backup_path: Path
    source_path: Path
    injected_chars: int


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    size: int
    updated_at: float


@dataclass(frozen=True)
class RestoreResult:
    session_file_path: Path
    backup_path: Path
    replaced_backup_path: Path
    restored_bytes: int


def options_for_profile(profile: str) -> HandoffOptions:
    if profile == "private":
        return HandoffOptions(redact=True, include_tools=True, tool_chars=6000)
    if profile == "public":
        return HandoffOptions(redact=True, include_tools=False, message_chars=6000)
    return HandoffOptions(redact=True, include_tools=False)


def target_agent_name(source_agent: str, target_agent: str) -> str:
    if target_agent == "same":
        target_agent = source_agent
    return "Claude" if target_agent == "claude" else "Codex"


def write_agent_handoff(
    config: AppConfig,
    context: RecoveryContext,
    *,
    scrub_profile: str = "shareable",
    target_agent: str = "same",
) -> WriteResult:
    output_path = default_output_path(config, context.session_id, summary=False, agent_key=context.agent_key)
    options = options_for_profile(scrub_profile)
    if context.agent_key == "claude":
        result = write_claude_handoff(
            session_id=context.session_id,
            session_file_path=context.session_file_path,
            metadata={**context.metadata, "target_agent": target_agent_name(context.agent_key, target_agent)},
            output_path=output_path,
            options=options,
        )
    else:
        result = write_handoff(
            session_id=context.session_id,
            rollout_path=context.session_file_path,
            metadata={**context.metadata, "target_agent": target_agent_name(context.agent_key, target_agent)},
            output_path=output_path,
            options=options,
        )
    append_target_note(result.path, context.agent_key, target_agent, scrub_profile)
    return result


def write_agent_summary(config: AppConfig, context: RecoveryContext, *, scrub_profile: str = "shareable") -> WriteResult:
    output_path = default_output_path(config, context.session_id, summary=True, agent_key=context.agent_key)
    redact = scrub_profile in {"private", "shareable", "public"}
    if context.agent_key == "claude":
        return write_claude_summary(
            session_id=context.session_id,
            session_file_path=context.session_file_path,
            metadata=context.metadata,
            output_path=output_path,
            redact=redact,
        )
    return write_summary(
        session_id=context.session_id,
        rollout_path=context.session_file_path,
        metadata=context.metadata,
        output_path=output_path,
        redact=redact,
    )


def write_combined_agent_handoff(
    config: AppConfig,
    contexts: list[RecoveryContext],
    *,
    scrub_profile: str = "shareable",
    target_agent: str = "same",
) -> WriteResult:
    contexts = [context for context in contexts if context.session_file_path.is_file()]
    if not contexts:
        raise ValueError("No readable source sessions were selected.")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = config.output_dir / f"{contexts[0].agent_key}-combined-{contexts[0].session_id[:8]}-{stamp}-handoff.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    parts = [
        write_agent_handoff(config, context, scrub_profile=scrub_profile, target_agent=target_agent)
        for context in contexts
    ]
    with output_path.open("w", encoding="utf-8") as out:
        out.write("# Combined Agent Handoff\n\n")
        out.write("Use this to continue from multiple related sessions.\n\n")
        out.write("## Source Sessions\n\n")
        for context in contexts:
            out.write(f"- `{context.session_id}`: `{context.session_file_path}`\n")
        out.write("\n## Restart Prompt\n\n")
        out.write(
            "I am continuing from multiple related AI sessions. Merge the facts, constraints, current files, "
            "decisions, blockers, and next steps from each source section below. Prefer the newest source when "
            "two sessions conflict, unless an older source has more specific implementation detail.\n\n"
        )
        for context, part in zip(contexts, parts):
            out.write(f"\n## Source: {context.session_id}\n\n")
            out.write(part.path.read_text(encoding="utf-8", errors="replace"))
            out.write("\n")
    append_target_note(output_path, contexts[0].agent_key, target_agent, scrub_profile)
    return WriteResult(
        path=output_path,
        messages=sum(part.messages for part in parts),
        tool_calls=sum(part.tool_calls for part in parts),
        tool_outputs=sum(part.tool_outputs for part in parts),
        split_parts=[part.path for part in parts],
    )


def write_combined_agent_summary(
    config: AppConfig,
    contexts: list[RecoveryContext],
    *,
    scrub_profile: str = "shareable",
) -> WriteResult:
    contexts = [context for context in contexts if context.session_file_path.is_file()]
    if not contexts:
        raise ValueError("No readable source sessions were selected.")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = config.output_dir / f"{contexts[0].agent_key}-combined-{contexts[0].session_id[:8]}-{stamp}-summary.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    parts = [write_agent_summary(config, context, scrub_profile=scrub_profile) for context in contexts]
    with output_path.open("w", encoding="utf-8") as out:
        out.write("# Combined Agent Summary\n\n")
        out.write("This summary combines related source sessions for injection or restart.\n\n")
        out.write("## Source Sessions\n\n")
        for context in contexts:
            out.write(f"- `{context.session_id}`: `{context.session_file_path}`\n")
        for context, part in zip(contexts, parts):
            out.write(f"\n## Source: {context.session_id}\n\n")
            out.write(part.path.read_text(encoding="utf-8", errors="replace"))
            out.write("\n")
    return WriteResult(
        path=output_path,
        messages=sum(part.messages for part in parts),
        tool_calls=sum(part.tool_calls for part in parts),
        tool_outputs=sum(part.tool_outputs for part in parts),
        split_parts=[part.path for part in parts],
    )


def append_target_note(path: Path, source_agent: str, target_agent: str, scrub_profile: str) -> None:
    target = target_agent_name(source_agent, target_agent)
    note = (
        "\n## Target Agent\n\n"
        f"- Target agent: `{target}`\n"
        f"- Scrub profile: `{scrub_profile}`\n"
        "- Use the same facts and constraints, but adapt command names and session-specific assumptions to the target agent.\n"
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(note)


def write_resume_package(
    config: AppConfig,
    context: RecoveryContext,
    *,
    scrub_profile: str = "shareable",
    target_agent: str = "same",
) -> Path:
    handoff = write_agent_handoff(config, context, scrub_profile=scrub_profile, target_agent=target_agent)
    summary = write_agent_summary(config, context, scrub_profile=scrub_profile)
    archive_path = archive_session(
        context.session_id,
        context.session_file_path,
        {"agent": context.agent_key, **context.metadata},
        config.output_dir / "archives",
    )
    package_dir = config.output_dir / "resume-packages"
    package_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prefix = context.session_id if context.agent_key == "codex" else f"{context.agent_key}-{context.session_id}"
    package_path = package_dir / f"{prefix}-resume-{stamp}.tar.gz"
    metadata = {
        "agent": context.agent_key,
        "target_agent": target_agent_name(context.agent_key, target_agent),
        "session_id": context.session_id,
        "session_file_path": str(context.session_file_path),
        "created_at": stamp,
        "scrub_profile": scrub_profile,
        "handoff": str(handoff.path),
        "summary": str(summary.path),
        "archive": str(archive_path),
        "metadata": context.metadata,
    }
    with tarfile.open(package_path, "w:gz") as tar:
        for path in (handoff.path, summary.path, archive_path):
            if path.exists():
                tar.add(path, arcname=path.name)
        if context.session_file_path.exists() and scrub_profile == "private":
            tar.add(context.session_file_path, arcname=context.session_file_path.name)
        info = tarfile.TarInfo("metadata.json")
        body = json.dumps(metadata, indent=2).encode("utf-8")
        info.size = len(body)
        tar.addfile(info, fileobj=BytesIO(body))
    return package_path


def inject_handoff_note(
    config: AppConfig,
    context: RecoveryContext,
    *,
    scrub_profile: str = "shareable",
    target_agent: str = "same",
    max_chars: int = 8000,
) -> InjectionResult:
    summary = write_agent_summary(config, context, scrub_profile=scrub_profile)
    text = summary.path.read_text(encoding="utf-8", errors="replace")
    if len(text) > max_chars:
        omitted = len(text) - max_chars
        text = f"{text[:max_chars]}\n\n[... injection truncated {omitted} characters; full summary: {summary.path} ...]"
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = context.session_file_path.with_name(f"{context.session_file_path.name}.bak-{stamp}")
    shutil.copy2(context.session_file_path, backup_path)
    payload = build_injection_payload(context, text, target_agent=target_agent)
    with context.session_file_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False))
        handle.write("\n")
    return InjectionResult(
        session_file_path=context.session_file_path,
        backup_path=backup_path,
        source_path=summary.path,
        injected_chars=len(text),
    )


def inject_handoff_note_into(
    config: AppConfig,
    source_context: RecoveryContext,
    target_context: RecoveryContext,
    *,
    scrub_profile: str = "shareable",
    target_agent: str = "same",
    max_chars: int = 8000,
) -> InjectionResult:
    summary = write_agent_summary(config, source_context, scrub_profile=scrub_profile)
    text = summary.path.read_text(encoding="utf-8", errors="replace")
    if len(text) > max_chars:
        omitted = len(text) - max_chars
        text = f"{text[:max_chars]}\n\n[... injection truncated {omitted} characters; full summary: {summary.path} ...]"
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = target_context.session_file_path.with_name(f"{target_context.session_file_path.name}.bak-{stamp}")
    shutil.copy2(target_context.session_file_path, backup_path)
    payload = build_injection_payload(
        target_context,
        text,
        target_agent=target_agent,
        source_context=source_context,
    )
    with target_context.session_file_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False))
        handle.write("\n")
    return InjectionResult(
        session_file_path=target_context.session_file_path,
        backup_path=backup_path,
        source_path=summary.path,
        injected_chars=len(text),
    )


def inject_combined_handoff_note_into(
    config: AppConfig,
    source_contexts: list[RecoveryContext],
    target_context: RecoveryContext,
    *,
    scrub_profile: str = "shareable",
    target_agent: str = "same",
    max_chars: int = 12000,
) -> InjectionResult:
    summary = write_combined_agent_summary(config, source_contexts, scrub_profile=scrub_profile)
    text = summary.path.read_text(encoding="utf-8", errors="replace")
    if len(text) > max_chars:
        omitted = len(text) - max_chars
        text = f"{text[:max_chars]}\n\n[... combined injection truncated {omitted} characters; full summary: {summary.path} ...]"
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = target_context.session_file_path.with_name(f"{target_context.session_file_path.name}.bak-{stamp}")
    shutil.copy2(target_context.session_file_path, backup_path)
    payload = build_injection_payload(
        target_context,
        text,
        target_agent=target_agent,
        source_context=source_contexts[0],
    )
    with target_context.session_file_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False))
        handle.write("\n")
    return InjectionResult(
        session_file_path=target_context.session_file_path,
        backup_path=backup_path,
        source_path=summary.path,
        injected_chars=len(text),
    )


def build_injection_payload(
    context: RecoveryContext,
    text: str,
    *,
    target_agent: str,
    source_context: RecoveryContext | None = None,
) -> dict[str, Any]:
    stamp = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    source = source_context or context
    header = (
        "Injected Agent Lifeboat recovery note.\n\n"
        f"Source agent: {source.agent_key}\n"
        f"Source session: {source.session_id}\n"
        f"Target session: {context.session_id}\n"
        f"Target agent: {target_agent_name(context.agent_key, target_agent)}\n\n"
    )
    body = header + text
    if context.agent_key == "claude":
        return {
            "type": "user",
            "isMeta": False,
            "timestamp": stamp,
            "cwd": context.metadata.get("cwd") or "",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": body}],
            },
            "agent_lifeboat_injection": True,
        }
    return {
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": body}],
            "agent_lifeboat_injection": True,
            "timestamp": stamp,
        },
    }


def bulk_cleanup_plan(rows: list[dict[str, Any]], row_states: dict[str, dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        sid = str(row.get("id") or "")
        state = row_states.get(sid) or {}
        readiness = state.get("readiness")
        artifacts = state.get("artifacts")
        if not readiness:
            continue
        title = str(row.get("title") or row.get("preview") or "Untitled").replace("\n", " ")[:70]
        if readiness.label == "Missing":
            lines.append(f"{sid} | missing transcript | restore file before cleanup | {title}")
        elif artifacts and artifacts.has_handoff and artifacts.has_archive:
            lines.append(f"{sid} | ready | can purge when intended | {title}")
        elif artifacts and artifacts.has_handoff:
            lines.append(f"{sid} | partial | archive before purge | {title}")
        else:
            lines.append(f"{sid} | needs handoff | generate handoff first | {title}")
    return lines


def list_session_backups(session_file_path: Path) -> list[BackupInfo]:
    backups: list[BackupInfo] = []
    for path in session_file_path.parent.glob(f"{session_file_path.name}.bak-*"):
        try:
            stat = path.stat()
        except OSError:
            continue
        backups.append(BackupInfo(path=path, size=stat.st_size, updated_at=stat.st_mtime))
    backups.sort(key=lambda backup: backup.updated_at, reverse=True)
    return backups


def restore_session_backup(session_file_path: Path, backup_path: Path) -> RestoreResult:
    if not session_file_path.exists():
        raise FileNotFoundError(session_file_path)
    if not backup_path.exists():
        raise FileNotFoundError(backup_path)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    replaced_backup_path = session_file_path.with_name(f"{session_file_path.name}.pre-restore-{stamp}")
    shutil.copy2(session_file_path, replaced_backup_path)
    shutil.copy2(backup_path, session_file_path)
    return RestoreResult(
        session_file_path=session_file_path,
        backup_path=backup_path,
        replaced_backup_path=replaced_backup_path,
        restored_bytes=session_file_path.stat().st_size,
    )
