from __future__ import annotations

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Header, Input, Label, ListItem, ListView, Markdown, Select, Static

from codex_lifeboat.controller import LifeboatController
from codex_lifeboat.doctor import report as doctor_report
from codex_lifeboat.intelligence import project_label
from codex_lifeboat.recovery import RecoveryContext
from codex_lifeboat.sessions import iso_from_epoch
from codex_lifeboat.text import human_size
from codex_lifeboat.views import (
    bulk_cleanup_markdown,
    compare_markdown,
    injection_markdown,
    purge_complete_markdown,
    purge_preview_markdown,
    restore_complete_markdown,
    restore_preview_markdown,
    session_details_markdown,
)


CONTEXT_ACTIONS = [
    ("launch_resume", "Open/resume in terminal", "o"),
    ("copy_session_id", "Copy session ID", "y"),
    ("handoff", "Write full handoff", "h"),
    ("summary", "Write compact summary", "s"),
    ("archive", "Archive session file", "a"),
    ("export_resume", "Export resume package", "e"),
    ("inject_handoff", "Inject handoff", "i"),
    ("compare", "Compare sessions", "c"),
    ("toggle_pin", "Toggle pin", "p"),
    ("restore_preview", "Preview backup restore", "u"),
    ("purge_preview", "Dry-run purge", "x"),
    ("doctor", "Doctor report", "d"),
    ("bulk_cleanup", "Bulk cleanup plan", "b"),
    ("toggle_id_view", "Toggle ID view", "v"),
    ("refresh", "Refresh sessions", "r"),
]


class SessionContextMenu(ModalScreen[str | None]):
    """Right-click action menu for the selected session."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
    ]

    def __init__(self, session_id: str | None) -> None:
        super().__init__()
        self.session_id = session_id

    def compose(self) -> ComposeResult:
        title = f"Session Actions: {self.session_id}" if self.session_id else "Session Actions"
        with Container(id="context-menu"):
            yield Static(title, id="context-menu-title")
            yield ListView(
                *[
                    ListItem(Label(f"{label}  [{key}]"), id=action)
                    for action, label, key in CONTEXT_ACTIONS
                ],
                id="context-actions",
            )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.dismiss(event.item.id)

    def action_close(self) -> None:
        self.dismiss(None)


class LifeboatTui(App[None]):
    """Terminal app for browsing and recovering AI agent sessions."""

    CSS = """
    Screen {
        background: #101418;
        color: #e8edf2;
    }

    #main {
        height: 1fr;
    }

    #left {
        width: 58%;
        min-width: 46;
        border: round #58616d;
        padding: 1;
    }

    #right {
        width: 42%;
        min-width: 30;
        border: round #58616d;
        padding: 1;
    }

    #agent,
    #search,
    #controls {
        margin-bottom: 1;
    }

    #controls {
        height: 3;
    }

    .compact-select {
        width: 1fr;
        margin-right: 1;
    }

    #sessions {
        height: 1fr;
    }

    #details {
        height: 1fr;
        overflow-y: auto;
    }

    #status {
        height: 3;
        border: round #3f8cff;
        padding: 0 1;
    }

    SessionContextMenu {
        align: center middle;
    }

    #context-menu {
        width: 52;
        max-height: 22;
        border: round #3f8cff;
        background: #161c22;
        padding: 1;
    }

    #context-menu-title {
        text-style: bold;
        color: #7cc7ff;
        margin-bottom: 1;
    }

    #context-actions {
        height: 1fr;
    }

    .title {
        text-style: bold;
        color: #7cc7ff;
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("v", "toggle_id_view", "ID view"),
        Binding("/", "focus_search", "Search"),
        Binding("escape", "clear_search", "Clear"),
        Binding("h", "handoff", "Handoff"),
        Binding("s", "summary", "Summary"),
        Binding("a", "archive", "Archive"),
        Binding("e", "export_resume", "Export"),
        Binding("y", "copy_session_id", "Copy ID"),
        Binding("o", "launch_resume", "Open"),
        Binding("i", "inject_handoff", "Inject"),
        Binding("c", "compare", "Compare"),
        Binding("b", "bulk_cleanup", "Bulk plan"),
        Binding("p", "toggle_pin", "Pin"),
        Binding("d", "doctor", "Doctor"),
        Binding("x", "purge_preview", "Dry purge"),
        Binding("ctrl+x", "purge_confirm", "Purge"),
        Binding("u", "restore_preview", "Restore"),
        Binding("ctrl+u", "restore_confirm", "Do restore"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.controller = LifeboatController()
        self.rows: list[dict] = []
        self.selected_session_id: str | None = None
        self.compare_session_id: str | None = None
        self.pending_purge: str | None = None
        self.pending_restore: str | None = None
        self.show_session_ids = False
        self.inject_source_context: RecoveryContext | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Static("Sessions", classes="title")
                yield Select(
                    [(self.controller.agent_label(choice.key), choice.key) for choice in self.controller.agent_choices],
                    value=self.controller.agent_key,
                    allow_blank=False,
                    id="agent",
                )
                with Horizontal(id="controls"):
                    yield Select(
                        [("Recent", "recent"), ("Project", "project"), ("Readiness", "readiness")],
                        value="recent",
                        allow_blank=False,
                        id="group",
                        classes="compact-select",
                    )
                    yield Select(
                        [("Same target", "same"), ("Target Codex", "codex"), ("Target Claude", "claude")],
                        value="same",
                        allow_blank=False,
                        id="target",
                        classes="compact-select",
                    )
                    yield Select(
                        [("Private", "private"), ("Shareable", "shareable"), ("Public", "public")],
                        value="shareable",
                        allow_blank=False,
                        id="scrub",
                        classes="compact-select",
                    )
                yield Input(placeholder="Filter text or agent:/project:/cwd:/model:/status:/file:/artifact:", id="search")
                yield DataTable(id="sessions", cursor_type="row", zebra_stripes=True)
            with Vertical(id="right"):
                yield Static("Session Details", classes="title")
                yield Markdown("", id="details")
        yield Static("", id="status")

    def on_mount(self) -> None:
        self.title = "Agent Lifeboat"
        self.install_tooltips()
        self.refresh_rows()
        self.table.focus()
        self.set_status(
            f"Ready on {self.controller.store.display_name}. Use arrows to move, right-click for actions, / to search."
        )

    @property
    def table(self) -> DataTable:
        return self.query_one("#sessions", DataTable)

    @property
    def details(self) -> Markdown:
        return self.query_one("#details", Markdown)

    @property
    def search(self) -> Input:
        return self.query_one("#search", Input)

    @property
    def group_select(self) -> Select:
        return self.query_one("#group", Select)

    @property
    def target_select(self) -> Select:
        return self.query_one("#target", Select)

    @property
    def scrub_select(self) -> Select:
        return self.query_one("#scrub", Select)

    @property
    def status(self) -> Static:
        return self.query_one("#status", Static)

    def install_tooltips(self) -> None:
        self.query_one("#agent").tooltip = "Choose which local agent session store to browse: Codex or Claude Code."
        self.query_one("#group").tooltip = (
            "Recent shows newest sessions first. Project groups sessions by cwd/repo. "
            "Readiness sorts by recovery state such as Ready, Partial, Needs handoff, or Missing."
        )
        self.query_one("#target").tooltip = "Choose the agent you plan to resume in. Cross-agent handoffs add target-specific restart notes."
        self.query_one("#scrub").tooltip = (
            "Private keeps more recovery detail, Shareable is the normal redacted default, Public trims more aggressively."
        )
        self.search.tooltip = "Filter by text, or use agent:, project:, cwd:, model:, status:, file:, and artifact: prefixes."
        self.table.tooltip = (
            "Use arrow keys to select a session. Right-click for actions. Press v to toggle an ID-first table view."
        )
        self.details.tooltip = "Selected session details, artifact history, transcript preview, readiness reasons, and available actions."
        self.status.tooltip = "Last action result or warning. Injection and purge write backups or recovery context first."

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button != 3:
            return
        event.prevent_default()
        event.stop()
        self.select_hovered_table_row()
        self.open_context_menu()

    def select_hovered_table_row(self) -> None:
        table = self.table
        hover_row = table.hover_row
        if hover_row is None or not table.is_valid_row_index(hover_row):
            return
        try:
            values = table.get_row_at(hover_row)
        except Exception:
            return
        if not values:
            return
        session_id = str(values[1] if self.show_session_ids and len(values) > 1 else values[-1])
        if not session_id:
            return
        self.selected_session_id = session_id
        self.pending_purge = None
        self.pending_restore = None
        self.render_details()

    def open_context_menu(self) -> None:
        if not self.current_row():
            self.set_status("No session selected.")
            return
        self.push_screen(SessionContextMenu(self.selected_session_id), self.handle_context_action)

    def handle_context_action(self, action: str | None) -> None:
        if not action:
            self.table.focus()
            return
        handlers = {
            "launch_resume": self.action_launch_resume,
            "copy_session_id": self.action_copy_session_id,
            "handoff": self.action_handoff,
            "summary": self.action_summary,
            "archive": self.action_archive,
            "export_resume": self.action_export_resume,
            "inject_handoff": self.action_inject_handoff,
            "compare": self.action_compare,
            "toggle_pin": self.action_toggle_pin,
            "restore_preview": self.action_restore_preview,
            "purge_preview": self.action_purge_preview,
            "doctor": self.action_doctor,
            "bulk_cleanup": self.action_bulk_cleanup,
            "toggle_id_view": self.action_toggle_id_view,
            "refresh": self.action_refresh,
        }
        handler = handlers.get(action)
        if handler:
            handler()
        self.table.focus()

    def selected_value(self, widget: Select, fallback: str) -> str:
        return fallback if widget.value is Select.BLANK else str(widget.value)

    def set_status(self, message: str) -> None:
        self.status.update(message)

    def selected_status_message(self) -> str:
        if self.inject_source_context:
            return (
                f"Injection source {self.inject_source_context.session_id} armed. "
                f"Select target {self.selected_session_id or ''} and press i, or return to source and press i to clear."
            )
        return f"Selected {self.selected_session_id}. Press v to toggle ID view."

    def refresh_rows(self) -> None:
        self.rows = self.controller.refresh(
            query=self.search.value.strip() if self.is_mounted else "",
            group_mode=self.selected_value(self.group_select, "recent") if self.is_mounted else "recent",
        )
        visible_ids = {str(row.get("id") or "") for row in self.rows[:500]}
        if self.selected_session_id not in visible_ids:
            self.selected_session_id = str(self.rows[0].get("id") or "") if self.rows else None
        self.render_table()
        self.render_details()

    def render_table(self) -> None:
        table = self.table
        table.clear(columns=True)
        if self.show_session_ids:
            table.add_columns("Pin", "Session ID", "Ready", "File", "Size", "Updated", "Title")
        else:
            table.add_columns("Pin", "Ready", "Project", "File", "Artifacts", "Size", "Updated", "Title", "Session")
        pinned = self.controller.pins.load()
        for row in self.rows[:500]:
            sid = str(row.get("id") or "")
            state = self.controller.state_for(row)
            title = row.get("title") or row.get("preview") or ""
            if self.show_session_ids:
                table.add_row(
                    "*" if self.controller.pin_key(sid) in pinned else "",
                    sid,
                    state.readiness.label,
                    self.controller.store.file_status(row),
                    human_size(state.size),
                    iso_from_epoch(row.get("updated_at"))[:19],
                    title.replace("\n", " ")[:80],
                    key=sid,
                )
            else:
                table.add_row(
                    "*" if self.controller.pin_key(sid) in pinned else "",
                    state.readiness.label,
                    project_label(row, max_chars=24),
                    self.controller.store.file_status(row),
                    state.artifacts.label(),
                    human_size(state.size),
                    iso_from_epoch(row.get("updated_at"))[:19],
                    title.replace("\n", " ")[:80],
                    sid,
                    key=sid,
                )

    def current_row(self) -> dict | None:
        if not self.rows:
            return None
        if self.selected_session_id:
            for row in self.rows:
                if str(row.get("id") or "") == self.selected_session_id:
                    return row
        return self.rows[0]

    def render_details(self) -> None:
        row = self.current_row()
        if not row:
            self.details.update("No session selected.")
            return
        detail = self.controller.detail_for(row)
        self.details.update(session_details_markdown(detail, store_display_name=self.controller.store.display_name))

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "agent":
            self.controller.switch_agent(str(event.value))
            self.selected_session_id = None
            self.compare_session_id = None
            self.pending_purge = None
            self.pending_restore = None
            self.refresh_rows()
            self.table.focus()
            self.set_status(f"Switched to {self.controller.store.display_name}.")
            return
        if event.select.id == "group":
            self.refresh_rows()
            self.set_status(f"Grouped by {self.selected_value(self.group_select, 'recent')}.")
            return
        if event.select.id in {"target", "scrub"}:
            self.render_details()
            self.set_status("Recovery options updated.")

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self.selected_session_id = str(event.row_key.value)
        self.pending_purge = None
        self.pending_restore = None
        self.render_details()
        self.set_status(self.selected_status_message())

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.selected_session_id = str(event.row_key.value)
        self.pending_purge = None
        self.pending_restore = None
        self.render_details()
        self.set_status(self.selected_status_message())

    def on_input_changed(self, _event: Input.Changed) -> None:
        self.pending_purge = None
        self.refresh_rows()

    def action_focus_search(self) -> None:
        self.search.focus()

    def action_clear_search(self) -> None:
        if self.cancel_pending_action():
            return
        if self.search.value:
            self.search.value = ""
            self.refresh_rows()
        self.table.focus()

    def cancel_pending_action(self) -> bool:
        cancelled: list[str] = []
        if self.inject_source_context:
            cancelled.append(f"injection source {self.inject_source_context.session_id}")
            self.inject_source_context = None
        if self.compare_session_id:
            cancelled.append(f"compare base {self.compare_session_id}")
            self.compare_session_id = None
        if self.pending_purge:
            cancelled.append(f"purge confirmation {self.pending_purge}")
            self.pending_purge = None
        if self.pending_restore:
            cancelled.append(f"restore confirmation {self.pending_restore}")
            self.pending_restore = None
        if not cancelled:
            return False
        self.set_status("Cancelled " + ", ".join(cancelled) + ".")
        return True

    def action_refresh(self) -> None:
        self.pending_purge = None
        self.pending_restore = None
        self.refresh_rows()
        self.set_status(f"Refreshed session list. Showing {len(self.rows)} sessions.")

    def action_toggle_id_view(self) -> None:
        self.show_session_ids = not self.show_session_ids
        self.render_table()
        self.table.focus()
        mode = "ID-first" if self.show_session_ids else "standard"
        self.set_status(f"Table view: {mode}. Showing {len(self.rows)} sessions.")

    def action_doctor(self) -> None:
        self.pending_purge = None
        self.details.update(doctor_report(self.controller.config, self.controller.store, self.controller.pins, agent_key=self.controller.agent_key))
        self.set_status("Doctor report loaded.")

    def action_handoff(self) -> None:
        row = self.current_row()
        if not row:
            return
        result, error = self.controller.write_handoff(row, scrub_profile=self.scrub_profile, target_agent=self.target_agent)
        if error:
            self.set_status(error)
            return
        self.refresh_rows()
        self.set_status(f"Wrote handoff: {result.path}")

    def action_summary(self) -> None:
        row = self.current_row()
        if not row:
            return
        result, error = self.controller.write_summary(row, scrub_profile=self.scrub_profile)
        if error:
            self.set_status(error)
            return
        self.refresh_rows()
        self.set_status(f"Wrote summary: {result.path}")

    def action_archive(self) -> None:
        row = self.current_row()
        if not row:
            return
        archive_path, error = self.controller.archive(row)
        if error:
            self.set_status(error)
            return
        self.refresh_rows()
        self.set_status(f"Archived: {archive_path}")

    def action_export_resume(self) -> None:
        row = self.current_row()
        if not row:
            return
        package_path, error = self.controller.export_resume(row, scrub_profile=self.scrub_profile, target_agent=self.target_agent)
        if error:
            self.set_status(error)
            return
        self.refresh_rows()
        self.set_status(f"Exported resume package: {package_path}")

    def action_copy_session_id(self) -> None:
        row = self.current_row()
        if not row:
            self.set_status("No session selected.")
            return
        session_id = str(row.get("id") or "")
        if not session_id:
            self.set_status("Selected session has no session id.")
            return
        self.copy_to_clipboard(session_id)
        self.set_status(f"Copied session id to clipboard: {session_id}")

    def action_launch_resume(self) -> None:
        row = self.current_row()
        if not row:
            self.set_status("No session selected.")
            return
        result, error = self.controller.launch_resume(row)
        if error:
            self.set_status(error)
            return
        message = f"Opened {result.terminal_name} in {result.cwd} and started: {result.command_text()}"
        if result.warning:
            message = f"{message}. {result.warning}"
        self.set_status(message)

    def action_inject_handoff(self) -> None:
        row = self.current_row()
        if not row:
            return
        target_context, context_error = self.controller.recovery_context(row)
        if not target_context:
            self.set_status(context_error or "Selected session cannot be used for injection.")
            return
        if not self.inject_source_context:
            self.inject_source_context = target_context
            self.set_status(f"Injection source set: {target_context.session_id}. Select target session and press i again.")
            return
        if self.inject_source_context.session_id == target_context.session_id:
            cleared = self.inject_source_context.session_id
            self.inject_source_context = None
            self.set_status(f"Injection source cleared: {cleared}.")
            return
        result, error = self.controller.inject_into(
            self.inject_source_context,
            row,
            scrub_profile=self.scrub_profile,
            target_agent=self.target_agent,
        )
        if error:
            self.set_status(error)
            return
        source_id = self.inject_source_context.session_id
        target_id = target_context.session_id
        self.inject_source_context = None
        self.refresh_rows()
        self.details.update(injection_markdown(result))
        self.set_status(f"Injected {source_id} into {target_id}. Backup: {result.backup_path}")

    def action_compare(self) -> None:
        row = self.current_row()
        if not row:
            return
        sid = str(row.get("id") or "")
        if not self.compare_session_id:
            self.compare_session_id = sid
            self.set_status(f"Compare base set to {sid}. Move to another session and press c again.")
            return
        if self.compare_session_id == sid:
            self.compare_session_id = None
            self.set_status("Compare selection cleared.")
            return
        left = next((candidate for candidate in self.rows if str(candidate.get("id") or "") == self.compare_session_id), None)
        if not left:
            self.compare_session_id = sid
            self.set_status(f"Previous compare base is no longer visible. Compare base set to {sid}.")
            return
        self.details.update(
            compare_markdown(
                left,
                row,
                left_state=self.controller.state_for(left),
                right_state=self.controller.state_for(row),
            )
        )
        self.set_status("Compare view loaded.")

    def action_bulk_cleanup(self) -> None:
        self.details.update(bulk_cleanup_markdown(self.controller.bulk_plan(self.rows[:500])))
        self.set_status("Bulk cleanup plan loaded for visible sessions.")

    def action_toggle_pin(self) -> None:
        row = self.current_row()
        if not row:
            return
        pinned, sid = self.controller.toggle_pin(row)
        self.refresh_rows()
        self.set_status(f"{'Pinned' if pinned else 'Unpinned'}: {sid}")

    def action_purge_preview(self) -> None:
        row = self.current_row()
        if not row:
            return
        lines, error = self.controller.purge_lines(row, dry_run=True)
        if error:
            self.set_status(error)
            return
        self.details.update(purge_preview_markdown(lines or []))
        self.set_status("Dry-run purge preview only. Nothing was deleted.")

    def action_purge_confirm(self) -> None:
        row = self.current_row()
        if not row:
            return
        session_id = str(row.get("id") or "")
        if self.pending_purge != session_id:
            self.pending_purge = session_id
            self.set_status(f"Press ctrl+x again to purge {session_id}. A recovery handoff will be written first.")
            return
        handoff, lines, error = self.controller.purge_after_handoff(row, scrub_profile=self.scrub_profile, target_agent=self.target_agent)
        if error:
            self.set_status(error)
            return
        self.pending_purge = None
        self.refresh_rows()
        self.details.update(purge_complete_markdown(handoff.path, lines or []))
        self.set_status(f"Purged {session_id}. Recovery handoff written first.")

    def action_restore_preview(self) -> None:
        row = self.current_row()
        if not row:
            return
        context, context_error = self.controller.recovery_context(row)
        if not context:
            self.set_status(context_error or "Selected session cannot be restored.")
            return
        backups, error = self.controller.backups_for(row)
        if error:
            self.set_status(error)
            return
        self.pending_restore = context.session_id if backups else None
        self.details.update(restore_preview_markdown(context.session_file_path, backups))
        if backups:
            self.set_status(f"Restore preview loaded for {context.session_id}. Press ctrl+u to restore latest backup.")
        else:
            self.set_status(f"No backups found for {context.session_id}.")

    def action_restore_confirm(self) -> None:
        row = self.current_row()
        if not row:
            return
        session_id = str(row.get("id") or "")
        if self.pending_restore != session_id:
            self.action_restore_preview()
            return
        result, error = self.controller.restore_latest_backup(row)
        if error:
            self.set_status(error)
            return
        self.pending_restore = None
        self.refresh_rows()
        self.details.update(restore_complete_markdown(result))
        self.set_status(f"Restored {session_id} from {result.backup_path}.")

    @property
    def scrub_profile(self) -> str:
        return self.selected_value(self.scrub_select, "shareable")

    @property
    def target_agent(self) -> str:
        return self.selected_value(self.target_select, "same")


def main() -> int:
    LifeboatTui().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
