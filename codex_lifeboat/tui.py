from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, Input, Markdown, Select, Static

from codex_lifeboat.agents import build_store, default_agent, detect_agents
from codex_lifeboat.config import load_config
from codex_lifeboat.doctor import report as doctor_report
from codex_lifeboat.handoff import (
    HandoffOptions,
    default_output_path,
    write_claude_handoff,
    write_claude_summary,
    write_handoff,
    write_summary,
)
from codex_lifeboat.operations import archive_session, purge_session
from codex_lifeboat.pins import PinStore
from codex_lifeboat.sessions import iso_from_epoch
from codex_lifeboat.text import human_size


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
        width: 56%;
        min-width: 58;
        border: round #58616d;
        padding: 1;
    }

    #right {
        width: 44%;
        border: round #58616d;
        padding: 1;
    }

    #search {
        margin-bottom: 1;
    }

    #agent {
        margin-bottom: 1;
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
        Binding("p", "toggle_pin", "Pin"),
        Binding("d", "doctor", "Doctor"),
        Binding("x", "purge_preview", "Dry purge"),
        Binding("ctrl+x", "purge_confirm", "Purge"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.config = load_config(create=True)
        self.agent_choices = detect_agents(self.config)
        self.agent_key = default_agent(self.config)
        self.store = build_store(self.config, self.agent_key)
        self.pins = PinStore(self.config)
        self.rows: list[dict] = []
        self.selected_session_id: str | None = None
        self.pending_purge: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Static("Sessions", classes="title")
                yield Select(
                    [(self.agent_label(choice.key), choice.key) for choice in self.agent_choices],
                    value=self.agent_key,
                    allow_blank=False,
                    id="agent",
                )
                yield Input(placeholder="Filter sessions by id, title, path, or cwd", id="search")
                yield DataTable(id="sessions", cursor_type="row", zebra_stripes=True)
            with Vertical(id="right"):
                yield Static("Session Details", classes="title")
                yield Markdown("", id="details")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Agent Lifeboat"
        self.refresh_rows()
        self.table.focus()
        self.set_status(f"Ready on {self.store.display_name}. Use arrows to move, / to search, h for handoff, s for summary, d for doctor.")

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
    def agent_select(self) -> Select:
        return self.query_one("#agent", Select)

    @property
    def status(self) -> Static:
        return self.query_one("#status", Static)

    def agent_label(self, key: str) -> str:
        for choice in self.agent_choices:
            if choice.key == key:
                suffix = "" if choice.available else " (not found)"
                return f"{choice.display_name}{suffix}"
        return key

    def pin_key(self, session_id: str) -> str:
        return f"{self.agent_key}:{session_id}"

    def set_status(self, message: str) -> None:
        self.status.update(message)

    def refresh_rows(self) -> None:
        query = self.search.value.strip() if self.is_mounted else ""
        self.rows = self.store.search(query, scan_content=False) if query else self.store.all()
        visible_ids = {str(row.get("id") or "") for row in self.rows[:500]}
        if self.selected_session_id not in visible_ids:
            self.selected_session_id = str(self.rows[0].get("id") or "") if self.rows else None
        self.render_table()
        self.render_details()

    def render_table(self) -> None:
        table = self.table
        table.clear(columns=True)
        table.add_columns("Pin", "File", "Size", "Updated", "Title", "Session")
        pinned = self.pins.load()
        for row in self.rows[:500]:
            sid = str(row.get("id") or "")
            title = row.get("title") or row.get("preview") or ""
            table.add_row(
                "*" if self.pin_key(sid) in pinned else "",
                self.store.file_status(row),
                human_size(self.store.size(row)),
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

    def current_file_session(self) -> tuple[str, Path, dict] | None:
        row = self.current_row()
        if not row:
            return None
        session_id = str(row.get("id") or "")
        path = self.store.session_file_path(row)
        if not path:
            self.set_status("No session file path is recorded. Only indexed metadata is recoverable.")
            return None
        if not path.is_file():
            self.set_status("Session file is missing. Lifeboat can show indexed metadata, but cannot read the transcript.")
            return None
        return session_id, path, row

    def render_details(self) -> None:
        row = self.current_row()
        if not row:
            self.details.update("No session selected.")
            return
        sid = str(row.get("id") or "")
        pinned = "yes" if self.pin_key(sid) in self.pins.load() else "no"
        file_status = self.store.file_status(row)
        has_file = self.store.has_session_file(row)
        tokens = int(row.get("tokens_used") or 0)
        transcript_state = "available" if has_file else "not recoverable without the session file"
        action_state = (
            "Full handoff, summary, archive, and purge are available."
            if has_file
            else "Full handoff, summary, archive, and purge need the session file."
        )
        body = f"""# {row.get("title") or row.get("preview") or "Untitled"}

- **Agent:** `{self.store.display_name}`
- **Session:** `{sid}`
- **Pinned:** `{pinned}`
- **Session file status:** `{file_status}`
- **Size:** `{human_size(self.store.size(row))}`
- **Updated:** `{iso_from_epoch(row.get("updated_at"))}`
- **CWD:** `{row.get("cwd") or ""}`
- **Model:** `{row.get("model") or ""}`
- **Tokens used:** `{tokens:,}`
- **Session file:** `{row.get("session_file_path") or row.get("rollout_path") or ""}`

## Recoverable

- Indexed metadata: `title`, `preview`, `cwd`, timestamps, token counter, session id, and last known session file path.
- Transcript and tool output: `{transcript_state}`.
- Actions: {action_state}

## Actions

- `h` write full handoff
- `s` write compact summary
- `a` archive session file
- `p` toggle pin
- `x` dry-run purge
- `ctrl+x` purge after two-step confirmation
- `d` show doctor report
"""
        self.details.update(body)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "agent":
            return
        new_agent = str(event.value)
        if new_agent == self.agent_key:
            return
        self.agent_key = new_agent
        self.store = build_store(self.config, self.agent_key)
        self.selected_session_id = None
        self.pending_purge = None
        self.refresh_rows()
        self.table.focus()
        self.set_status(f"Switched to {self.store.display_name}.")

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
        self.details.update(doctor_report(self.config, self.store, self.pins, agent_key=self.agent_key))
        self.set_status("Doctor report loaded.")

    def action_handoff(self) -> None:
        selected = self.current_file_session()
        if not selected:
            return
        session_id, session_file_path, metadata = selected
        if self.agent_key == "claude":
            result = write_claude_handoff(
                session_id=session_id,
                session_file_path=session_file_path,
                metadata=metadata,
                output_path=default_output_path(self.config, session_id, summary=False, agent_key=self.agent_key),
                options=HandoffOptions(),
            )
        else:
            result = write_handoff(
                session_id=session_id,
                rollout_path=session_file_path,
                metadata=metadata,
                output_path=default_output_path(self.config, session_id, summary=False, agent_key=self.agent_key),
                options=HandoffOptions(),
            )
        self.set_status(f"Wrote handoff: {result.path}")

    def action_summary(self) -> None:
        selected = self.current_file_session()
        if not selected:
            return
        session_id, session_file_path, metadata = selected
        if self.agent_key == "claude":
            result = write_claude_summary(
                session_id=session_id,
                session_file_path=session_file_path,
                metadata=metadata,
                output_path=default_output_path(self.config, session_id, summary=True, agent_key=self.agent_key),
            )
        else:
            result = write_summary(
                session_id=session_id,
                rollout_path=session_file_path,
                metadata=metadata,
                output_path=default_output_path(self.config, session_id, summary=True, agent_key=self.agent_key),
            )
        self.set_status(f"Wrote summary: {result.path}")

    def action_archive(self) -> None:
        selected = self.current_file_session()
        if not selected:
            return
        session_id, session_file_path, metadata = selected
        archive_path = archive_session(session_id, session_file_path, {"agent": self.agent_key, **metadata}, self.config.output_dir / "archives")
        self.set_status(f"Archived: {archive_path}")

    def action_toggle_pin(self) -> None:
        row = self.current_row()
        if not row:
            return
        sid = str(row.get("id") or "")
        key = self.pin_key(sid)
        if self.pins.is_pinned(key):
            self.pins.unpin(key)
            self.set_status(f"Unpinned: {sid}")
        else:
            self.pins.pin(key)
            self.set_status(f"Pinned: {sid}")
        self.refresh_rows()

    def purge_lines(self, session_id: str, session_file_path: Path, *, dry_run: bool) -> list[str]:
        if self.agent_key == "claude":
            actions = [
                f"session file: {session_file_path}",
                "state db: none",
                "log dbs: 0",
            ]
            if dry_run:
                return ["Dry run only. Nothing was deleted.", *actions]
            if session_file_path.exists():
                session_file_path.unlink()
            return [*actions, "removed indexed thread rows: 0", "removed log rows: 0"]
        return purge_session(self.config, session_id, session_file_path, dry_run=dry_run)

    def action_purge_preview(self) -> None:
        selected = self.current_file_session()
        if not selected:
            return
        session_id, session_file_path, _metadata = selected
        lines = self.purge_lines(session_id, session_file_path, dry_run=True)
        self.details.update("# Purge Preview\n\n" + "\n".join(f"- {line}" for line in lines))
        self.set_status("Dry-run purge preview only. Nothing was deleted.")

    def action_purge_confirm(self) -> None:
        selected = self.current_file_session()
        if not selected:
            return
        session_id, session_file_path, metadata = selected
        if self.pending_purge != session_id:
            self.pending_purge = session_id
            self.set_status(f"Press ctrl+x again to purge {session_id}. A recovery handoff will be written first.")
            return
        if self.agent_key == "claude":
            result = write_claude_handoff(
                session_id=session_id,
                session_file_path=session_file_path,
                metadata=metadata,
                output_path=default_output_path(self.config, session_id, summary=False, agent_key=self.agent_key),
                options=HandoffOptions(),
            )
        else:
            result = write_handoff(
                session_id=session_id,
                rollout_path=session_file_path,
                metadata=metadata,
                output_path=default_output_path(self.config, session_id, summary=False, agent_key=self.agent_key),
                options=HandoffOptions(),
            )
        lines = self.purge_lines(session_id, session_file_path, dry_run=False)
        self.pending_purge = None
        self.refresh_rows()
        self.details.update(
            "# Purge Complete\n\n"
            f"- Recovery handoff: `{result.path}`\n"
            + "\n".join(f"- {line}" for line in lines)
        )
        self.set_status(f"Purged {session_id}. Recovery handoff written first.")


def main() -> int:
    LifeboatTui().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
