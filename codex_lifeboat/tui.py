from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, Input, Markdown, Select, Static

from codex_lifeboat.controller import LifeboatController
from codex_lifeboat.doctor import report as doctor_report
from codex_lifeboat.intelligence import project_label
from codex_lifeboat.sessions import iso_from_epoch
from codex_lifeboat.text import human_size
from codex_lifeboat.views import (
    bulk_cleanup_markdown,
    compare_markdown,
    injection_markdown,
    purge_complete_markdown,
    purge_preview_markdown,
    session_details_markdown,
)


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

    .title {
        text-style: bold;
        color: #7cc7ff;
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("/", "focus_search", "Search"),
        Binding("escape", "clear_search", "Clear"),
        Binding("h", "handoff", "Handoff"),
        Binding("s", "summary", "Summary"),
        Binding("a", "archive", "Archive"),
        Binding("e", "export_resume", "Export"),
        Binding("i", "inject_handoff", "Inject"),
        Binding("c", "compare", "Compare"),
        Binding("b", "bulk_cleanup", "Bulk plan"),
        Binding("p", "toggle_pin", "Pin"),
        Binding("d", "doctor", "Doctor"),
        Binding("x", "purge_preview", "Dry purge"),
        Binding("ctrl+x", "purge_confirm", "Purge"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.controller = LifeboatController()
        self.rows: list[dict] = []
        self.selected_session_id: str | None = None
        self.compare_session_id: str | None = None
        self.pending_purge: str | None = None

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
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Agent Lifeboat"
        self.install_tooltips()
        self.refresh_rows()
        self.table.focus()
        self.set_status(
            f"Ready on {self.controller.store.display_name}. Use arrows to move, / to search, h for handoff, s for summary, d for doctor."
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
            "Use arrow keys to select a session. Readiness shows whether recovery artifacts exist and whether the transcript is available."
        )
        self.details.tooltip = "Selected session details, artifact history, transcript preview, readiness reasons, and available actions."
        self.status.tooltip = "Last action result or warning. Destructive actions require confirmation and write recovery context first."

    def selected_value(self, widget: Select, fallback: str) -> str:
        return fallback if widget.value is Select.BLANK else str(widget.value)

    def set_status(self, message: str) -> None:
        self.status.update(message)

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
        table.add_columns("Pin", "Ready", "Project", "File", "Artifacts", "Size", "Updated", "Title", "Session")
        pinned = self.controller.pins.load()
        for row in self.rows[:500]:
            sid = str(row.get("id") or "")
            state = self.controller.state_for(row)
            title = row.get("title") or row.get("preview") or ""
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
        self.render_details()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.selected_session_id = str(event.row_key.value)
        self.pending_purge = None
        self.render_details()

    def on_input_changed(self, _event: Input.Changed) -> None:
        self.pending_purge = None
        self.refresh_rows()

    def action_focus_search(self) -> None:
        self.search.focus()

    def action_clear_search(self) -> None:
        if self.search.value:
            self.search.value = ""
            self.refresh_rows()
        self.table.focus()

    def action_refresh(self) -> None:
        self.pending_purge = None
        self.refresh_rows()
        self.set_status("Refreshed session list.")

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

    def action_inject_handoff(self) -> None:
        row = self.current_row()
        if not row:
            return
        result, error = self.controller.inject(row, scrub_profile=self.scrub_profile, target_agent=self.target_agent)
        if error:
            self.set_status(error)
            return
        self.refresh_rows()
        self.details.update(injection_markdown(result))
        self.set_status(f"Injected recovery note. Backup: {result.backup_path}")

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
