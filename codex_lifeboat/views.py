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
    health = detail.health
    preview = detail.preview
    tokens = int(row.get("tokens_used") or 0)
    pinned = "yes" if detail.pinned else "no"
    note = detail.note.text if detail.note else ""
    return f"""# {row.get("title") or row.get("preview") or "Untitled"}

- **Agent:** `{store_display_name}`
- **Session:** `{sid}`
- **Pinned:** `{pinned}`
- **Readiness:** `{readiness.label}`
- **Health:** `{health.label}` `{health.score}/100`
- **Project:** `{project_key(row)}`
- **Session file status:** `{detail.file_status}`
- **Artifacts:** `{artifacts.label()}`
- **Size:** `{human_size(detail.state["size"])}`
- **Backups:** `{detail.backup_count}`
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

## Note

{note or "No local note."}

## Health

{bullets(health.reasons)}

## Health Next Actions

{bullets(health.next_actions)}

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
- `m` make this session safe by writing handoff, summary, and archive
- `s` write compact summary
- `a` archive session file
- `e` export resume package
- `y` copy selected session id to clipboard
- `o` open a terminal in the session cwd and resume the selected agent session
- `i` open source/target injection picker, optionally combine same-project sources, then inject after backup
- `c` compare selected sessions
- `g` show health details
- `t` show project timeline
- `j` show project dashboard
- `n` edit local session note
- `k` browse backups and restore a selected backup
- `w` show recovery wizard
- `f` run safe doctor fixes
- `b` show bulk cleanup plan for visible sessions
- `v` toggle ID-first table view
- `Esc` cancel pending injection, compare, purge confirmation, or clear search
- `p` toggle pin
- `x` dry-run purge
- `ctrl+x` purge after two-step confirmation
- `ctrl+z` purge all unpinned visible sessions after two-step confirmation
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


def compare_markdown(left: dict[str, Any], right: dict[str, Any], *, left_state: Any, right_state: Any, left_health: Any = None, right_health: Any = None, left_preview: Any = None, right_preview: Any = None) -> str:
    def line(label: str, key: str) -> str:
        return f"| {label} | `{left.get(key) or ''}` | `{right.get(key) or ''}` |"

    left_id = str(left.get("id") or "")
    right_id = str(right.get("id") or "")
    left_score = f"{left_health.label} {left_health.score}/100" if left_health else ""
    right_score = f"{right_health.label} {right_health.score}/100" if right_health else ""
    left_counts = transcript_counts(left_preview)
    right_counts = transcript_counts(right_preview)
    return "\n".join(
        [
            "# Session Compare",
            "",
            "| Field | Base | Selected |",
            "| --- | --- | --- |",
            f"| Session | `{left_id}` | `{right_id}` |",
            f"| Readiness | `{left_state.readiness.label}` | `{right_state.readiness.label}` |",
            f"| Health | `{left_score}` | `{right_score}` |",
            f"| Artifacts | `{left_state.artifacts.label()}` | `{right_state.artifacts.label()}` |",
            f"| Size | `{human_size(left_state.size)}` | `{human_size(right_state.size)}` |",
            f"| Transcript counts | `{left_counts}` | `{right_counts}` |",
            f"| Project | `{project_key(left)}` | `{project_key(right)}` |",
            line("Updated", "updated_at"),
            line("CWD", "cwd"),
            line("Model", "model"),
            line("Title", "title"),
            line("Session file", "rollout_path"),
        ]
    )


def transcript_counts(preview: Any) -> str:
    if not preview:
        return ""
    return f"{preview.message_count} msg, {preview.tool_call_count} calls, {preview.tool_output_count} outputs"


def health_markdown(detail: SessionDetail) -> str:
    health = detail.health
    return (
        "# Session Health\n\n"
        f"- Label: `{health.label}`\n"
        f"- Score: `{health.score}/100`\n"
        f"- Session: `{detail.row.get('id') or ''}`\n"
        f"- Readiness: `{detail.state['readiness'].label}`\n"
        f"- Artifacts: `{detail.state['artifacts'].label()}`\n"
        f"- Backups: `{detail.backup_count}`\n\n"
        "## Reasons\n\n"
        f"{bullets(health.reasons)}\n\n"
        "## Next Actions\n\n"
        f"{bullets(health.next_actions)}"
    )


def project_dashboard_markdown(summaries: list[Any]) -> str:
    if not summaries:
        return "# Project Dashboard\n\nNo visible projects."
    lines = [
        "# Project Dashboard",
        "",
        "| Project | Sessions | Health | Missing Handoff | Archived | Pinned | Notes | Size | Latest | Best Session |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for summary in summaries[:80]:
        health = f"Rd{summary.ready} Rc{summary.recoverable} Rs{summary.risky} Bk{summary.broken}"
        latest = iso_from_epoch(summary.latest_updated_at)[:19]
        best = f"`{summary.best_session_id}`"
        if summary.best_title:
            best += f" {summary.best_title[:42]}"
        lines.append(
            f"| {summary.label} | {summary.sessions} | `{health}` | {summary.missing_handoffs} | "
            f"{summary.archived} | {summary.pinned} | {summary.noted} | {human_size(summary.total_size)} | "
            f"`{latest}` | {best} |"
        )
    lines.append("")
    lines.append("Health codes: `Rd` Ready, `Rc` Recoverable, `Rs` Risky, `Bk` Broken.")
    return "\n".join(lines)


def project_timeline_markdown(project: str, entries: list[Any]) -> str:
    if not entries:
        return f"# Project Timeline\n\nNo visible sessions for `{project}`."
    lines = [
        "# Project Timeline",
        "",
        f"Project: `{project}`",
        "",
        "| Updated | Health | Ready | Artifacts | Size | Session | Note | Title |",
        "| --- | --- | --- | --- | ---: | --- | --- | --- |",
    ]
    for entry in entries[-120:]:
        note = "yes" if entry.note else ""
        title = entry.title.replace("|", "\\|")[:70]
        lines.append(
            f"| `{iso_from_epoch(entry.updated_at)[:19]}` | `{entry.health} {entry.health_score}` | "
            f"`{entry.readiness}` | `{entry.artifacts}` | {human_size(entry.size)} | "
            f"`{entry.session_id}` | {note} | {title} |"
        )
    return "\n".join(lines)


def safe_bundle_markdown(result: Any) -> str:
    return (
        "# Make Safe Complete\n\n"
        f"- Handoff: `{result.handoff.path}`\n"
        f"- Summary: `{result.summary.path}`\n"
        f"- Archive: `{result.archive_path}`\n\n"
        "The selected session now has the core recovery artifacts."
    )


def session_note_markdown(session_id: str, note: Any) -> str:
    if not note:
        return f"# Session Note\n\nNo note saved for `{session_id}`."
    return (
        "# Session Note\n\n"
        f"- Session: `{session_id}`\n"
        f"- Updated: `{note.updated_at}`\n\n"
        f"{note.text}"
    )


def recovery_wizard_markdown(detail: SessionDetail) -> str:
    health = detail.health
    readiness = detail.state["readiness"]
    artifacts = detail.state["artifacts"]
    lines = [
        "# Recovery Wizard",
        "",
        f"- Session: `{detail.row.get('id') or ''}`",
        f"- Health: `{health.label}` `{health.score}/100`",
        f"- Readiness: `{readiness.label}`",
        f"- Artifacts: `{artifacts.label()}`",
        "",
        "## Recommended Flow",
        "",
    ]
    if health.label == "Broken":
        lines.extend(["1. Open Backup Browser (`k`) and restore a backup if one exists.", "2. If no backup exists, use indexed metadata/details only."])
    elif not artifacts.has_handoff or not artifacts.has_archive:
        lines.extend(["1. Run Make Safe (`m`) to write handoff, summary, and archive.", "2. Add a session note (`n`) if this is an important branch.", "3. Resume directly (`o`) or export a package (`e`)."])
    else:
        lines.extend(["1. Add or review the session note (`n`).", "2. Resume directly (`o`), export (`e`), inject (`i`), or purge only when intended."])
    lines.extend(["", "## Health Actions", "", bullets(health.next_actions)])
    return "\n".join(lines)


def doctor_fixes_markdown(lines: list[str]) -> str:
    return "# Doctor Fixes\n\n" + "\n".join(f"- {line}" for line in lines)


def bulk_cleanup_markdown(lines: list[str]) -> str:
    if not lines:
        return "# Bulk Cleanup Plan\n\nNo visible sessions."
    body = "# Bulk Cleanup Plan\n\nThis is a review plan only. Use handoff, archive, and purge actions on selected sessions.\n\n"
    return body + "\n".join(f"- `{line}`" for line in lines[:200])


def bulk_purge_preview_markdown(result: Any) -> str:
    if result.candidate_count == 0:
        return (
            "# Bulk Purge Preview\n\n"
            "No unpinned visible sessions are eligible for bulk purge.\n\n"
            f"- Visible sessions: `{result.visible_count}`\n"
            f"- Pinned sessions skipped: `{result.pinned_skipped}`"
        )
    body = (
        "# Bulk Purge Preview\n\n"
        "Press `ctrl+z` again to purge every unpinned visible session listed here. "
        "Readable sessions will get a recovery handoff first.\n\n"
    )
    return body + bulk_purge_lines_markdown(result)


def bulk_purge_complete_markdown(result: Any) -> str:
    body = (
        "# Bulk Purge Complete\n\n"
        f"- Purged sessions: `{result.purged_count}`\n"
        f"- Recovery handoffs written: `{len(result.handoff_paths)}`\n"
        f"- Pinned sessions skipped: `{result.pinned_skipped}`\n"
        f"- Errors: `{len(result.errors)}`\n\n"
    )
    return body + bulk_purge_lines_markdown(result)


def bulk_purge_lines_markdown(result: Any) -> str:
    lines = [f"- `{line}`" for line in list(result.lines)[:400]]
    if len(result.lines) > 400:
        lines.append(f"- `... truncated {len(result.lines) - 400} additional lines ...`")
    if result.errors:
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- `{error}`" for error in result.errors[:80])
        if len(result.errors) > 80:
            lines.append(f"- `... truncated {len(result.errors) - 80} additional errors ...`")
    return "\n".join(lines)


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
    handoff_line = (
        f"- Recovery handoff: `{handoff_path}`"
        if handoff_path
        else "- Recovery handoff: not written; session file was missing"
    )
    return "# Purge Complete\n\n" + handoff_line + "\n" + "\n".join(f"- {line}" for line in lines)


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
