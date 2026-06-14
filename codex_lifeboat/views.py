from __future__ import annotations

from typing import Any

from .controller import SessionDetail
from .intelligence import project_key
from .sessions import iso_from_epoch
from .text import human_size


def bullets(values: list[str] | tuple[str, ...]) -> str:
    if not values:
        return "None captured."
    return "\n".join(f"- {value}" for value in values)


def session_details_markdown(detail: SessionDetail, *, store_display_name: str) -> str:
    row = detail.row
    sid = str(row.get("id") or "")
    artifacts = detail.state["artifacts"]
    readiness = detail.state["readiness"]
    preview = detail.preview
    tokens = int(row.get("tokens_used") or 0)
    pinned = "yes" if detail.pinned else "no"
    return f"""# {row.get("title") or row.get("preview") or "Untitled"}

- **Agent:** `{store_display_name}`
- **Session:** `{sid}`
- **Pinned:** `{pinned}`
- **Readiness:** `{readiness.label}`
- **Project:** `{project_key(row)}`
- **Session file status:** `{detail.file_status}`
- **Artifacts:** `{artifacts.label()}`
- **Size:** `{human_size(detail.state["size"])}`
- **Updated:** `{iso_from_epoch(row.get("updated_at"))}`
- **CWD:** `{row.get("cwd") or ""}`
- **Model:** `{row.get("model") or ""}`
- **Tokens used:** `{tokens:,}`
- **Session file:** `{row.get("session_file_path") or row.get("rollout_path") or ""}`
- **Preview scan:** `{preview_scan_label(preview)}`

## Recoverable

- Indexed metadata: `title`, `preview`, `cwd`, timestamps, token counter, session id, and last known session file path.
- Transcript and tool output: `{detail.transcript_state}`.
- Actions: {detail.action_state}

## Readiness

{bullets(readiness.reasons)}

## Next Actions

{bullets(readiness.next_actions)}

## Handoff History

- Latest artifact: `{artifacts.latest or ""}`
- Handoffs: `{len(artifacts.handoffs)}`
- Summaries: `{len(artifacts.summaries)}`
- Archives: `{len(artifacts.archives)}`
- Resume packages: `{len(artifacts.resume_packages)}`

## Latest User Request

{preview.latest_user or "None captured."}

## Latest Assistant Result

{preview.latest_assistant or "None captured."}

## Commands Seen

{bullets(preview.commands)}

## Important Paths

{bullets(preview.paths)}

## Blockers

{bullets(preview.blockers)}

## Transcript Counts

- Messages: `{preview.message_count}`
- Tool calls: `{preview.tool_call_count}`
- Tool outputs: `{preview.tool_output_count}`

## Actions

- Click a session row or press Enter to open the action menu.
- Click a session table header to sort by that column; click it again to reverse direction.
- `h` write full handoff
- `H` select visible sessions to combine into one handoff; same-project sessions start checked
- `s` write compact summary
- `a` archive session file
- `e` export resume package
- `y` copy selected session id to clipboard
- `o` open a terminal in the session cwd and resume the selected agent session
- `i` open source/target injection picker, optionally combine same-project sources, then inject after backup
- `c` compare selected sessions
- `b` show bulk cleanup plan for visible sessions
- `v` toggle ID-first table view
- `Esc` cancel pending injection, compare, purge confirmation, or clear search
- `p` toggle pin
- `x` dry-run purge
- `ctrl+x` purge after two-step confirmation
- `u` preview latest backup restore
- `ctrl+u` restore latest backup after preview
- `d` show doctor report
"""


def preview_scan_label(preview: Any) -> str:
    if preview.partial:
        return f"tail preview, scanned {human_size(preview.scanned_bytes)}"
    if preview.scanned_bytes:
        return f"full preview, scanned {human_size(preview.scanned_bytes)}"
    return "not available"


def compare_markdown(left: dict[str, Any], right: dict[str, Any], *, left_state: Any, right_state: Any) -> str:
    def line(label: str, key: str) -> str:
        return f"| {label} | `{left.get(key) or ''}` | `{right.get(key) or ''}` |"

    left_id = str(left.get("id") or "")
    right_id = str(right.get("id") or "")
    return "\n".join(
        [
            "# Session Compare",
            "",
            "| Field | Base | Selected |",
            "| --- | --- | --- |",
            f"| Session | `{left_id}` | `{right_id}` |",
            f"| Readiness | `{left_state.readiness.label}` | `{right_state.readiness.label}` |",
            f"| Artifacts | `{left_state.artifacts.label()}` | `{right_state.artifacts.label()}` |",
            f"| Size | `{human_size(left_state.size)}` | `{human_size(right_state.size)}` |",
            f"| Project | `{project_key(left)}` | `{project_key(right)}` |",
            line("Updated", "updated_at"),
            line("CWD", "cwd"),
            line("Model", "model"),
            line("Title", "title"),
            line("Session file", "rollout_path"),
        ]
    )


def bulk_cleanup_markdown(lines: list[str]) -> str:
    if not lines:
        return "# Bulk Cleanup Plan\n\nNo visible sessions."
    body = "# Bulk Cleanup Plan\n\nThis is a review plan only. Use handoff, archive, and purge actions on selected sessions.\n\n"
    return body + "\n".join(f"- `{line}`" for line in lines[:200])


def injection_markdown(result: Any) -> str:
    return (
        "# Handoff Injected\n\n"
        f"- Target session file: `{result.session_file_path}`\n"
        f"- Backup: `{result.backup_path}`\n"
        f"- Source summary: `{result.source_path}`\n"
        f"- Injected characters: `{result.injected_chars:,}`\n\n"
        "The injected note is appended as a synthetic user message."
    )


def purge_preview_markdown(lines: list[str]) -> str:
    return "# Purge Preview\n\n" + "\n".join(f"- {line}" for line in lines)


def purge_complete_markdown(handoff_path: Any, lines: list[str]) -> str:
    return "# Purge Complete\n\n" f"- Recovery handoff: `{handoff_path}`\n" + "\n".join(f"- {line}" for line in lines)


def restore_preview_markdown(session_file: Any, backups: list[Any]) -> str:
    if not backups:
        return "# Restore Backup\n\nNo backups found for this session."
    latest = backups[0]
    body = (
        "# Restore Backup\n\n"
        "The latest backup will be restored if you press `ctrl+u` again.\n\n"
        f"- Session file: `{session_file}`\n"
        f"- Latest backup: `{latest.path}`\n"
        f"- Backup size: `{human_size(latest.size)}`\n"
        f"- Backup timestamp: `{iso_from_epoch(latest.updated_at)}`\n\n"
        "## Available Backups\n\n"
    )
    lines = [f"- `{backup.path}` `{human_size(backup.size)}` `{iso_from_epoch(backup.updated_at)}`" for backup in backups[:10]]
    return body + "\n".join(lines)


def restore_complete_markdown(result: Any) -> str:
    return (
        "# Restore Complete\n\n"
        f"- Restored session file: `{result.session_file_path}`\n"
        f"- Restored from backup: `{result.backup_path}`\n"
        f"- Previous current file saved as: `{result.replaced_backup_path}`\n"
        f"- Restored bytes: `{human_size(result.restored_bytes)}`\n"
    )
