from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agents import AgentChoice, SessionBackend, build_store, default_agent, detect_agents
from .artifacts import ArtifactHistory, artifact_history
from .config import AppConfig, load_config
from .intelligence import (
    RecoveryReadiness,
    TranscriptPreview,
    analyze_transcript,
    parse_filters,
    project_key,
    recovery_readiness,
    row_matches_filters,
)
from .launcher import LaunchResult, launch_resume_terminal
from .operations import archive_session, purge_session
from .pins import PinStore
from .recovery import (
    BackupInfo,
    InjectionResult,
    RecoveryContext,
    RestoreResult,
    bulk_cleanup_plan,
    inject_combined_handoff_note_into,
    inject_handoff_note,
    inject_handoff_note_into,
    list_session_backups,
    restore_session_backup,
    write_agent_handoff,
    write_agent_summary,
    write_combined_agent_handoff,
    write_resume_package,
)

DETAIL_PREVIEW_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class SessionDetail:
    row: dict[str, Any]
    state: dict[str, Any]
    preview: TranscriptPreview
    pinned: bool
    file_status: str
    has_session_file: bool
    transcript_state: str
    action_state: str


class LifeboatController:
    def __init__(self) -> None:
        self.config: AppConfig = load_config(create=True)
        self.agent_choices: list[AgentChoice] = detect_agents(self.config)
        self.agent_key: str = default_agent(self.config)
        self.store: SessionBackend = build_store(self.config, self.agent_key)
        self.pins = PinStore(self.config)
        self.rows: list[dict[str, Any]] = []
        self.row_states: dict[str, dict[str, Any]] = {}
        self.preview_cache: dict[tuple[str, str, int, int], TranscriptPreview] = {}

    def agent_label(self, key: str) -> str:
        for choice in self.agent_choices:
            if choice.key == key:
                suffix = "" if choice.available else " (not found)"
                return f"{choice.display_name}{suffix}"
        return key

    def switch_agent(self, agent_key: str) -> None:
        self.agent_key = agent_key
        self.store = build_store(self.config, self.agent_key)
        self.rows = []
        self.row_states = {}
        self.preview_cache = {}

    def pin_key(self, session_id: str) -> str:
        return f"{self.agent_key}:{session_id}"

    def refresh(self, *, query: str, group_mode: str) -> list[dict[str, Any]]:
        filters, text_query = parse_filters(query)
        rows = self.store.all()
        pinned = self.pins.load()
        self.row_states = {}
        filtered: list[dict[str, Any]] = []
        for row in rows:
            sid = str(row.get("id") or "")
            artifacts = artifact_history(self.config, sid, self.agent_key)
            size = self.store.size(row)
            readiness = recovery_readiness(
                row=row,
                has_session_file=self.store.has_session_file(row),
                file_status=self.store.file_status(row),
                size=size,
                artifacts=artifacts,
                pinned=self.pin_key(sid) in pinned,
            )
            state = {
                "artifacts": artifacts,
                "readiness": readiness,
                "size": size,
                "project": project_key(row),
            }
            self.row_states[sid] = state
            if row_matches_filters(
                row,
                agent_key=self.agent_key,
                readiness=readiness,
                artifacts=artifacts,
                filters=filters,
                text_query=text_query,
            ):
                filtered.append(row)
        if group_mode == "project":
            filtered.sort(key=lambda row: (project_key(row).lower(), -(int(row.get("updated_at") or 0))))
        elif group_mode == "readiness":
            filtered.sort(
                key=lambda row: (
                    -(self.state_for(row).readiness.rank),
                    -(int(row.get("updated_at") or 0)),
                )
            )
        else:
            filtered.sort(key=lambda row: row.get("updated_at") or 0, reverse=True)
        self.rows = filtered
        return self.rows

    def state_for(self, row: dict[str, Any]) -> "RowState":
        sid = str(row.get("id") or "")
        state = self.row_states.get(sid) or {}
        artifacts = state.get("artifacts")
        readiness = state.get("readiness")
        size = state.get("size")
        if not isinstance(artifacts, ArtifactHistory):
            artifacts = artifact_history(self.config, sid, self.agent_key)
        if not isinstance(readiness, RecoveryReadiness):
            size = self.store.size(row)
            readiness = recovery_readiness(
                row=row,
                has_session_file=self.store.has_session_file(row),
                file_status=self.store.file_status(row),
                size=size,
                artifacts=artifacts,
                pinned=self.pin_key(sid) in self.pins.load(),
            )
        return RowState(artifacts=artifacts, readiness=readiness, size=int(size or 0), project=project_key(row))

    def detail_for(self, row: dict[str, Any]) -> SessionDetail:
        path = self.store.session_file_path(row)
        has_file = self.store.has_session_file(row)
        transcript_state = "available" if has_file else "not recoverable without the session file"
        action_state = (
            "Full handoff, summary, archive, and purge are available."
            if has_file
            else "Full handoff, summary, archive, and purge need the session file."
        )
        return SessionDetail(
            row=row,
            state={
                "artifacts": self.state_for(row).artifacts,
                "readiness": self.state_for(row).readiness,
                "size": self.state_for(row).size,
                "project": self.state_for(row).project,
            },
            preview=self.preview_for(path),
            pinned=self.pin_key(str(row.get("id") or "")) in self.pins.load(),
            file_status=self.store.file_status(row),
            has_session_file=has_file,
            transcript_state=transcript_state,
            action_state=action_state,
        )

    def preview_for(self, path: Path | None) -> TranscriptPreview:
        if not path or not path.is_file():
            return TranscriptPreview()
        stat = path.stat()
        key = (self.agent_key, str(path), stat.st_mtime_ns, stat.st_size)
        cached = self.preview_cache.get(key)
        if cached:
            return cached
        preview = analyze_transcript(self.agent_key, path, max_bytes=DETAIL_PREVIEW_BYTES)
        self.preview_cache[key] = preview
        if len(self.preview_cache) > 128:
            self.preview_cache.pop(next(iter(self.preview_cache)))
        return preview

    def recovery_context(self, row: dict[str, Any]) -> tuple[RecoveryContext | None, str | None]:
        session_id = str(row.get("id") or "")
        path = self.store.session_file_path(row)
        if not path:
            return None, "No session file path is recorded. Only indexed metadata is recoverable."
        if not path.is_file():
            return None, "Session file is missing. Lifeboat can show indexed metadata, but cannot read the transcript."
        return RecoveryContext(self.agent_key, session_id, path, row), None

    def write_handoff(self, row: dict[str, Any], *, scrub_profile: str, target_agent: str):
        context, error = self.recovery_context(row)
        if not context:
            return None, error
        return write_agent_handoff(self.config, context, scrub_profile=scrub_profile, target_agent=target_agent), None

    def write_project_handoff(
        self,
        row: dict[str, Any],
        visible_rows: list[dict[str, Any]],
        *,
        scrub_profile: str,
        target_agent: str,
    ):
        contexts, error = self.same_project_contexts(row, visible_rows)
        if error:
            return None, error
        try:
            return write_combined_agent_handoff(
                self.config,
                contexts,
                scrub_profile=scrub_profile,
                target_agent=target_agent,
            ), None
        except ValueError as exc:
            return None, str(exc)

    def write_combined_handoff(
        self,
        rows: list[dict[str, Any]],
        *,
        scrub_profile: str,
        target_agent: str,
    ):
        contexts: list[RecoveryContext] = []
        for row in rows:
            context, error = self.recovery_context(row)
            if not context:
                session_id = str(row.get("id") or "unknown")
                return None, f"Selected session cannot be included ({session_id}): {error}"
            contexts.append(context)
        if not contexts:
            return None, "Select at least one session with a readable session file."
        try:
            return write_combined_agent_handoff(
                self.config,
                contexts,
                scrub_profile=scrub_profile,
                target_agent=target_agent,
            ), None
        except ValueError as exc:
            return None, str(exc)

    def write_summary(self, row: dict[str, Any], *, scrub_profile: str):
        context, error = self.recovery_context(row)
        if not context:
            return None, error
        return write_agent_summary(self.config, context, scrub_profile=scrub_profile), None

    def archive(self, row: dict[str, Any]) -> tuple[Path | None, str | None]:
        context, error = self.recovery_context(row)
        if not context:
            return None, error
        return archive_session(context.session_id, context.session_file_path, {"agent": self.agent_key, **context.metadata}, self.config.output_dir / "archives"), None

    def export_resume(self, row: dict[str, Any], *, scrub_profile: str, target_agent: str) -> tuple[Path | None, str | None]:
        context, error = self.recovery_context(row)
        if not context:
            return None, error
        return write_resume_package(self.config, context, scrub_profile=scrub_profile, target_agent=target_agent), None

    def launch_resume(self, row: dict[str, Any]) -> tuple[LaunchResult | None, str | None]:
        session_id = str(row.get("id") or "")
        return launch_resume_terminal(self.agent_key, session_id, row.get("cwd"))

    def inject(self, row: dict[str, Any], *, scrub_profile: str, target_agent: str) -> tuple[InjectionResult | None, str | None]:
        context, error = self.recovery_context(row)
        if not context:
            return None, error
        return inject_handoff_note(self.config, context, scrub_profile=scrub_profile, target_agent=target_agent), None

    def inject_into(
        self,
        source_context: RecoveryContext,
        target_row: dict[str, Any],
        *,
        scrub_profile: str,
        target_agent: str,
    ) -> tuple[InjectionResult | None, str | None]:
        target_context, error = self.recovery_context(target_row)
        if not target_context:
            return None, error
        if source_context.session_file_path == target_context.session_file_path:
            return None, "Select a different target session, or clear the injection source first."
        if not source_context.session_file_path.is_file():
            return None, "The injection source session file is no longer available."
        return (
            inject_handoff_note_into(
                self.config,
                source_context,
                target_context,
                scrub_profile=scrub_profile,
                target_agent=target_agent,
            ),
            None,
        )

    def inject_sources_into(
        self,
        source_contexts: list[RecoveryContext],
        target_row: dict[str, Any],
        *,
        scrub_profile: str,
        target_agent: str,
    ) -> tuple[InjectionResult | None, str | None]:
        target_context, error = self.recovery_context(target_row)
        if not target_context:
            return None, error
        source_contexts = [context for context in source_contexts if context.session_file_path != target_context.session_file_path]
        if not source_contexts:
            return None, "Select at least one source session that is different from the target."
        missing = [context.session_id for context in source_contexts if not context.session_file_path.is_file()]
        if missing:
            return None, f"Source session file is no longer available: {missing[0]}"
        if len(source_contexts) == 1:
            return (
                inject_handoff_note_into(
                    self.config,
                    source_contexts[0],
                    target_context,
                    scrub_profile=scrub_profile,
                    target_agent=target_agent,
                ),
                None,
            )
        try:
            return (
                inject_combined_handoff_note_into(
                    self.config,
                    source_contexts,
                    target_context,
                    scrub_profile=scrub_profile,
                    target_agent=target_agent,
                ),
                None,
            )
        except ValueError as exc:
            return None, str(exc)

    def same_project_rows(self, row: dict[str, Any], visible_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        project = project_key(row)
        return [candidate for candidate in visible_rows if project_key(candidate) == project]

    def same_project_contexts(
        self,
        row: dict[str, Any],
        visible_rows: list[dict[str, Any]],
    ) -> tuple[list[RecoveryContext], str | None]:
        contexts: list[RecoveryContext] = []
        for candidate in self.same_project_rows(row, visible_rows):
            context, _error = self.recovery_context(candidate)
            if context:
                contexts.append(context)
        if not contexts:
            return [], "No readable session files are available for this project."
        return contexts, None

    def toggle_pin(self, row: dict[str, Any]) -> tuple[bool, str]:
        sid = str(row.get("id") or "")
        key = self.pin_key(sid)
        if self.pins.is_pinned(key):
            self.pins.unpin(key)
            return False, sid
        self.pins.pin(key)
        return True, sid

    def purge_lines(self, row: dict[str, Any], *, dry_run: bool) -> tuple[list[str] | None, str | None]:
        context, error = self.recovery_context(row)
        if not context:
            return None, error
        if self.agent_key == "claude":
            actions = [
                f"session file: {context.session_file_path}",
                "state db: none",
                "log dbs: 0",
            ]
            if dry_run:
                return ["Dry run only. Nothing was deleted.", *actions], None
            if context.session_file_path.exists():
                context.session_file_path.unlink()
            return [*actions, "removed indexed thread rows: 0", "removed log rows: 0"], None
        return purge_session(self.config, context.session_id, context.session_file_path, dry_run=dry_run), None

    def purge_after_handoff(
        self,
        row: dict[str, Any],
        *,
        scrub_profile: str,
        target_agent: str,
    ):
        context, error = self.recovery_context(row)
        if not context:
            return None, None, error
        handoff = write_agent_handoff(self.config, context, scrub_profile=scrub_profile, target_agent=target_agent)
        lines, purge_error = self.purge_lines(row, dry_run=False)
        return handoff, lines, purge_error

    def bulk_plan(self, rows: list[dict[str, Any]]) -> list[str]:
        return bulk_cleanup_plan(rows, self.row_states)

    def backups_for(self, row: dict[str, Any]) -> tuple[list[BackupInfo], str | None]:
        context, error = self.recovery_context(row)
        if not context:
            return [], error
        return list_session_backups(context.session_file_path), None

    def restore_latest_backup(self, row: dict[str, Any]) -> tuple[RestoreResult | None, str | None]:
        context, error = self.recovery_context(row)
        if not context:
            return None, error
        backups = list_session_backups(context.session_file_path)
        if not backups:
            return None, "No backups were found for the selected session."
        try:
            result = restore_session_backup(context.session_file_path, backups[0].path)
        except OSError as exc:
            return None, f"Restore failed: {exc}"
        self.preview_cache = {}
        return result, None


@dataclass(frozen=True)
class RowState:
    artifacts: ArtifactHistory
    readiness: RecoveryReadiness
    size: int
    project: str
