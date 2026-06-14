from __future__ import annotations

from pathlib import Path

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Header, Input, Label, ListItem, ListView, Markdown, Select, Static

from codex_lifeboat import __version__
from codex_lifeboat.controller import LifeboatController
from codex_lifeboat.doctor import report as doctor_report
from codex_lifeboat.intelligence import project_key, project_label
from codex_lifeboat.recovery import RecoveryContext
from codex_lifeboat.sessions import iso_from_epoch
from codex_lifeboat.text import human_size
from codex_lifeboat.views import (
    bulk_cleanup_markdown,
    compare_markdown,
    doctor_fixes_markdown,
    health_markdown,
    injection_markdown,
    project_dashboard_markdown,
    project_timeline_markdown,
    purge_complete_markdown,
    purge_preview_markdown,
    recovery_wizard_markdown,
    restore_complete_markdown,
    restore_preview_markdown,
    safe_bundle_markdown,
    session_note_markdown,
    session_details_markdown,
)


CONTEXT_SECTIONS = [
    (
        "Open",
        [
            ("launch_resume", "Open/resume in terminal", "o"),
            ("copy_session_id", "Copy session ID", "y"),
        ],
    ),
    (
        "Recover",
        [
            ("make_safe", "Make safe", "m"),
            ("handoff", "Write full handoff", "h"),
            ("project_handoff", "Write combined handoff", "H"),
            ("summary", "Write compact summary", "s"),
            ("export_resume", "Export resume package", "e"),
            ("inject_handoff", "Inject handoff", "i"),
            ("recovery_wizard", "Recovery wizard", "w"),
        ],
    ),
    (
        "Manage",
        [
            ("session_note", "Edit note", "n"),
            ("toggle_pin", "Toggle pin", "p"),
            ("backup_browser", "Browse backups", "k"),
            ("archive", "Archive session file", "a"),
            ("restore_preview", "Preview backup restore", "u"),
            ("purge_preview", "Dry-run purge", "x"),
        ],
    ),
    (
        "Inspect",
        [
            ("health", "Health details", "g"),
            ("project_timeline", "Project timeline", "t"),
            ("project_dashboard", "Project dashboard", "j"),
            ("compare", "Compare sessions", "c"),
            ("doctor", "Doctor report", "d"),
            ("doctor_fixes", "Doctor fixes", "f"),
            ("bulk_cleanup", "Bulk cleanup plan", "b"),
        ],
    ),
    (
        "View",
        [
            ("toggle_id_view", "Toggle ID view", "v"),
            ("refresh", "Refresh sessions", "r"),
        ],
    ),
]
CONTEXT_ACTIONS = [action for _section, actions in CONTEXT_SECTIONS for action in actions]
CONTEXT_ACTION_BY_KEY = {key: action for action, _label, key in CONTEXT_ACTIONS}


STANDARD_COLUMNS = ("pin", "ready", "project", "file", "artifacts", "size", "updated", "title", "session")
ID_COLUMNS = ("pin", "session", "ready", "file", "size", "updated", "title")
COLUMN_LABELS = {
    "pin": "Pin",
    "ready": "Ready",
    "project": "Project",
    "file": "File",
    "artifacts": "Artifacts",
    "size": "Size",
    "updated": "Updated",
    "title": "Title",
    "session": "Session ID",
}
DEFAULT_DESCENDING_SORTS = {"artifacts", "ready", "size", "updated"}


class SessionContextMenu(ModalScreen[str | None]):
    """Action menu for the selected session."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
    ]

    def __init__(self, row: dict | None) -> None:
        super().__init__()
        self.row = row

    def compose(self) -> ComposeResult:
        with Container(id="context-menu"):
            yield Static(self.context_title(), id="context-menu-title")
            yield ListView(*self.context_items(), id="context-actions")

    def context_title(self) -> str:
        if not self.row:
            return "Session Actions"
        session_id = str(self.row.get("id") or "")
        title = str(self.row.get("title") or self.row.get("preview") or "").replace("\n", " ")
        heading = title[:72] if title else session_id
        project = project_label(self.row, max_chars=48)
        updated = iso_from_epoch(self.row.get("updated_at"))[:19] or "unknown"
        return f"{heading}\nProject: {project}\nUpdated: {updated}"

    def context_items(self) -> list[ListItem]:
        items: list[ListItem] = []
        for section, actions in CONTEXT_SECTIONS:
            items.append(
                ListItem(
                    Label(section.upper(), classes="context-section-label", markup=False),
                    classes="context-section",
                    disabled=True,
                )
            )
            for action, label, key in actions:
                items.append(
                    ListItem(
                        Label(self.context_action_label(label, key), classes="context-action-label"),
                        id=action,
                        classes="context-action",
                    )
                )
        return items

    def context_action_label(self, label: str, key: str) -> str:
        first, separator, rest = label.partition(" ")
        suffix = f"{separator}{rest}" if rest else ""
        return f"  {first}([bold #ffcc66]{key}[/]){suffix}"

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item.disabled:
            return
        self.dismiss(event.item.id)

    def on_key(self, event: events.Key) -> None:
        action = CONTEXT_ACTION_BY_KEY.get(event.character or event.key)
        if not action:
            return
        event.prevent_default()
        event.stop()
        self.dismiss(action)

    def action_close(self) -> None:
        self.dismiss(None)


class CombinedHandoffPicker(ModalScreen[tuple[str, ...] | None]):
    """Picker for selecting the exact sessions to combine into one handoff."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
    ]

    def __init__(self, rows: list[dict], selected_session_id: str | None) -> None:
        super().__init__()
        self.rows = rows[:500]
        selected_row = self.row_by_id(selected_session_id)
        selected_project = project_key(selected_row) if selected_row else None
        self.selected_ids = {
            str(row.get("id") or "")
            for row in self.rows
            if str(row.get("id") or "") and (selected_project is None or project_key(row) == selected_project)
        }

    def compose(self) -> ComposeResult:
        with Container(id="combine-picker"):
            yield Static("Combined Handoff", id="combine-title")
            yield ListView(*self.list_items(), id="combine-sessions")
            yield Static("", id="combine-status")
            with Horizontal(id="combine-buttons"):
                yield Button("Cancel", id="combine-cancel")
                yield Button("Write Handoff", id="combine-confirm", variant="primary")

    def on_mount(self) -> None:
        self.refresh_status()
        self.query_one("#combine-sessions", ListView).focus()

    def row_by_id(self, session_id: str | None) -> dict | None:
        if not session_id:
            return None
        return next((row for row in self.rows if str(row.get("id") or "") == session_id), None)

    def list_items(self) -> list[ListItem]:
        return [
            ListItem(Label(self.row_label(row), markup=False), id=f"combine-{row.get('id')}")
            for row in self.rows
            if row.get("id")
        ]

    def row_label(self, row: dict) -> str:
        session_id = str(row.get("id") or "")
        checked = "x" if session_id in self.selected_ids else " "
        project = project_label(row, max_chars=18)
        updated = iso_from_epoch(row.get("updated_at"))[:10]
        title = str(row.get("title") or row.get("preview") or "").replace("\n", " ")
        return f"[{checked}] {project:<18} {updated:<10} {session_id[:8]} {title[:48]}"

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        _prefix, _separator, session_id = item_id.partition("-")
        if not session_id:
            return
        if session_id in self.selected_ids:
            self.selected_ids.remove(session_id)
        else:
            self.selected_ids.add(session_id)
        row = self.row_by_id(session_id)
        if row:
            event.item.query_one(Label).update(self.row_label(row))
        self.refresh_status()

    def refresh_status(self) -> None:
        count = len(self.selected_ids)
        self.query_one("#combine-status", Static).update(f"{count} session{'s' if count != 1 else ''} selected.")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "combine-cancel":
            self.dismiss(None)
            return
        if event.button.id == "combine-confirm":
            self.action_confirm()

    def action_confirm(self) -> None:
        if not self.selected_ids:
            self.refresh_status()
            return
        ordered = tuple(str(row.get("id") or "") for row in self.rows if str(row.get("id") or "") in self.selected_ids)
        self.dismiss(ordered)

    def action_close(self) -> None:
        self.dismiss(None)


class InjectionPicker(ModalScreen[tuple[tuple[str, ...], str] | None]):
    """Two-column source/target picker for handoff injection."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
    ]

    def __init__(self, rows: list[dict], selected_session_id: str | None) -> None:
        super().__init__()
        self.rows = rows[:500]
        self.selected_source_id = selected_session_id or self.first_session_id()
        self.selected_target_id = self.first_session_id(excluding=self.selected_source_id)
        self.combine_project = False

    def compose(self) -> ComposeResult:
        with Container(id="inject-picker"):
            yield Static("Inject Handoff", id="inject-title")
            with Horizontal(id="inject-columns"):
                with Vertical(classes="inject-column"):
                    yield Static("Source", classes="inject-column-title")
                    yield ListView(*self.list_items("source"), id="inject-source")
                with Vertical(classes="inject-column"):
                    yield Static("Target", classes="inject-column-title")
                    yield ListView(*self.list_items("target"), id="inject-target")
            yield Checkbox("Combine same project as source", id="inject-combine-project")
            yield Static("", id="inject-status")
            with Horizontal(id="inject-buttons"):
                yield Button("Cancel", id="inject-cancel")
                yield Button("Inject", id="inject-confirm", variant="primary")

    def on_mount(self) -> None:
        self.refresh_status()
        self.query_one("#inject-source", ListView).focus()

    def first_session_id(self, *, excluding: str | None = None) -> str | None:
        for row in self.rows:
            session_id = str(row.get("id") or "")
            if session_id and session_id != excluding:
                return session_id
        return None

    def row_by_id(self, session_id: str | None) -> dict | None:
        if not session_id:
            return None
        return next((row for row in self.rows if str(row.get("id") or "") == session_id), None)

    def source_ids_for_action(self) -> tuple[str, ...]:
        source_row = self.row_by_id(self.selected_source_id)
        if not source_row:
            return ()
        if not self.combine_project:
            return (self.selected_source_id,) if self.selected_source_id else ()
        source_project = project_key(source_row)
        return tuple(
            str(row.get("id") or "")
            for row in self.rows
            if str(row.get("id") or "") and project_key(row) == source_project and str(row.get("id") or "") != self.selected_target_id
        )

    def list_items(self, side: str) -> list[ListItem]:
        selected = self.selected_source_id if side == "source" else self.selected_target_id
        items: list[ListItem] = []
        for row in self.rows:
            session_id = str(row.get("id") or "")
            if not session_id:
                continue
            marker = ">" if session_id == selected else " "
            items.append(ListItem(Label(f"{marker} {self.row_label(row)}"), id=f"{side}-{session_id}"))
        return items

    def row_label(self, row: dict) -> str:
        session_id = str(row.get("id") or "")
        title = str(row.get("title") or row.get("preview") or "").replace("\n", " ")
        project = project_label(row, max_chars=18)
        return f"{project:<18} {session_id[:8]} {title[:52]}"

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        side, _, session_id = item_id.partition("-")
        if not session_id:
            return
        if side == "source":
            self.selected_source_id = session_id
            if self.selected_target_id == session_id:
                self.selected_target_id = self.first_session_id(excluding=session_id)
            self.refresh_list_labels("source")
            self.refresh_list_labels("target")
            self.refresh_status()
            self.query_one("#inject-target", ListView).focus()
            return
        if side == "target":
            self.selected_target_id = session_id
            self.refresh_list_labels("target")
            self.refresh_status()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id != "inject-combine-project":
            return
        self.combine_project = bool(event.value)
        self.refresh_status()

    def refresh_list_labels(self, side: str) -> None:
        widget_id = "#inject-source" if side == "source" else "#inject-target"
        list_view = self.query_one(widget_id, ListView)
        selected = self.selected_source_id if side == "source" else self.selected_target_id
        rows_by_id = {str(row.get("id") or ""): row for row in self.rows}
        for item in list_view.children:
            item_id = item.id or ""
            _, _, session_id = item_id.partition("-")
            row = rows_by_id.get(session_id)
            if not row:
                continue
            marker = ">" if session_id == selected else " "
            item.query_one(Label).update(f"{marker} {self.row_label(row)}")

    def refresh_status(self) -> None:
        status = self.query_one("#inject-status", Static)
        if not self.selected_source_id:
            status.update("Select a source session.")
            return
        if not self.selected_target_id:
            status.update("Select a different target session.")
            return
        if self.selected_source_id == self.selected_target_id:
            status.update("Source and target must be different sessions.")
            return
        source_ids = self.source_ids_for_action()
        if self.combine_project:
            status.update(f"Combining {len(source_ids)} source sessions -> target {self.selected_target_id}")
            return
        status.update(f"Source {self.selected_source_id} -> target {self.selected_target_id}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "inject-cancel":
            self.dismiss(None)
            return
        if event.button.id == "inject-confirm":
            self.action_inject()

    def action_inject(self) -> None:
        source_ids = self.source_ids_for_action()
        if not source_ids or not self.selected_target_id:
            self.refresh_status()
            return
        if self.selected_target_id in source_ids:
            self.refresh_status()
            return
        self.dismiss((source_ids, self.selected_target_id))

    def action_close(self) -> None:
        self.dismiss(None)


class BackupPicker(ModalScreen[str | None]):
    """Picker for restoring a specific session backup."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
    ]

    def __init__(self, session_id: str, backups: list) -> None:
        super().__init__()
        self.session_id = session_id
        self.backups = backups
        self.selected_index = 0 if backups else None

    def compose(self) -> ComposeResult:
        with Container(id="backup-picker"):
            yield Static(f"Backups for {self.session_id}", id="backup-title")
            yield ListView(*self.list_items(), id="backup-list")
            yield Static("", id="backup-status")
            with Horizontal(id="backup-buttons"):
                yield Button("Cancel", id="backup-cancel")
                yield Button("Restore Selected", id="backup-confirm", variant="primary")

    def on_mount(self) -> None:
        self.refresh_status()
        self.query_one("#backup-list", ListView).focus()

    def list_items(self) -> list[ListItem]:
        items: list[ListItem] = []
        for index, backup in enumerate(self.backups):
            items.append(ListItem(Label(self.backup_label(index, backup), markup=False), id=f"backup-{index}"))
        return items

    def backup_label(self, index: int, backup: object) -> str:
        marker = ">" if index == self.selected_index else " "
        return f"{marker} {iso_from_epoch(backup.updated_at)[:19]} {human_size(backup.size):>8} {backup.path.name}"

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        _prefix, _separator, index_text = item_id.partition("-")
        if not index_text.isdigit():
            return
        self.selected_index = int(index_text)
        self.refresh_list_labels()
        self.refresh_status()

    def refresh_list_labels(self) -> None:
        for item in self.query_one("#backup-list", ListView).children:
            item_id = item.id or ""
            _prefix, _separator, index_text = item_id.partition("-")
            if not index_text.isdigit():
                continue
            index = int(index_text)
            if 0 <= index < len(self.backups):
                item.query_one(Label).update(self.backup_label(index, self.backups[index]))

    def refresh_status(self) -> None:
        if not self.backups:
            self.query_one("#backup-status", Static).update("No backups available.")
            return
        selected = self.backups[self.selected_index or 0]
        self.query_one("#backup-status", Static).update(f"Selected backup: {selected.path}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "backup-cancel":
            self.dismiss(None)
            return
        if event.button.id == "backup-confirm":
            if self.selected_index is None:
                self.dismiss(None)
                return
            self.dismiss(str(self.backups[self.selected_index].path))

    def action_close(self) -> None:
        self.dismiss(None)


class NoteEditor(ModalScreen[tuple[str, str] | None]):
    """Single-line local note editor for the selected session."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
    ]

    def __init__(self, session_id: str, current_text: str) -> None:
        super().__init__()
        self.session_id = session_id
        self.current_text = current_text

    def compose(self) -> ComposeResult:
        with Container(id="note-editor"):
            yield Static(f"Note for {self.session_id}", id="note-title")
            yield Input(value=self.current_text, placeholder="Why this session matters", id="note-input")
            yield Static("Keep it short: good branch, bad attempt, resume target, etc.", id="note-help")
            with Horizontal(id="note-buttons"):
                yield Button("Cancel", id="note-cancel")
                yield Button("Clear", id="note-clear")
                yield Button("Save", id="note-save", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#note-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "note-cancel":
            self.dismiss(None)
            return
        if event.button.id == "note-clear":
            self.dismiss(("clear", ""))
            return
        if event.button.id == "note-save":
            text = self.query_one("#note-input", Input).value
            self.dismiss(("save", text))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(("save", event.value))

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

    #toolbar,
    #search {
        margin-bottom: 1;
    }

    #toolbar {
        height: 1;
    }

    .compact-select {
        width: 1fr;
        margin-right: 1;
    }

    #agent {
        width: 2fr;
    }

    #group {
        width: 1fr;
    }

    #target {
        width: 1fr;
    }

    #scrub {
        width: 1fr;
        margin-right: 0;
    }

    #search {
        height: 1;
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

    InjectionPicker {
        align: center middle;
    }

    CombinedHandoffPicker {
        align: center middle;
    }

    BackupPicker {
        align: center middle;
    }

    NoteEditor {
        align: center middle;
    }

    #context-menu {
        width: 58;
        max-height: 30;
        border: round #3f8cff;
        background: #161c22;
        padding: 1;
    }

    #context-menu-title {
        height: 3;
        text-style: bold;
        color: #7cc7ff;
        margin-bottom: 1;
    }

    #context-actions {
        height: 1fr;
    }

    .context-section {
        height: 1;
        color: #7cc7ff;
        background: #101418;
    }

    .context-section-label {
        text-style: bold;
        color: #7cc7ff;
    }

    .context-action {
        height: 1;
    }

    .context-action-label {
        color: #e8edf2;
    }

    #combine-picker {
        width: 92%;
        height: 82%;
        border: round #3f8cff;
        background: #161c22;
        padding: 1;
    }

    #combine-title {
        height: 1;
        text-style: bold;
        color: #7cc7ff;
        margin-bottom: 1;
    }

    #combine-sessions {
        height: 1fr;
        border: round #58616d;
    }

    #combine-status {
        height: 3;
        color: #e8edf2;
        padding: 0 1;
    }

    #combine-buttons {
        height: 3;
        align-horizontal: right;
    }

    #combine-cancel,
    #combine-confirm {
        margin-left: 1;
    }

    #inject-picker {
        width: 90%;
        height: 82%;
        border: round #3f8cff;
        background: #161c22;
        padding: 1;
    }

    #inject-title {
        height: 1;
        text-style: bold;
        color: #7cc7ff;
        margin-bottom: 1;
    }

    #inject-columns {
        height: 1fr;
    }

    .inject-column {
        width: 1fr;
        margin-right: 1;
    }

    .inject-column-title {
        height: 1;
        text-style: bold;
        color: #e8edf2;
    }

    #inject-source,
    #inject-target {
        height: 1fr;
        border: round #58616d;
    }

    #inject-combine-project {
        height: 1;
        margin-top: 1;
    }

    #inject-status {
        height: 3;
        color: #e8edf2;
        padding: 0 1;
    }

    #inject-buttons {
        height: 3;
        align-horizontal: right;
    }

    #inject-cancel,
    #inject-confirm {
        margin-left: 1;
    }

    #backup-picker {
        width: 86%;
        height: 70%;
        border: round #3f8cff;
        background: #161c22;
        padding: 1;
    }

    #backup-title,
    #note-title {
        height: 1;
        text-style: bold;
        color: #7cc7ff;
        margin-bottom: 1;
    }

    #backup-list {
        height: 1fr;
        border: round #58616d;
    }

    #backup-status,
    #note-help {
        height: 3;
        color: #e8edf2;
        padding: 0 1;
    }

    #backup-buttons,
    #note-buttons {
        height: 3;
        align-horizontal: right;
    }

    #backup-cancel,
    #backup-confirm,
    #note-cancel,
    #note-clear,
    #note-save {
        margin-left: 1;
    }

    #note-editor {
        width: 78%;
        height: 14;
        border: round #3f8cff;
        background: #161c22;
        padding: 1;
    }

    #note-input {
        height: 3;
    }

    .title {
        width: auto;
        text-style: bold;
        color: #7cc7ff;
        margin-right: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("v", "toggle_id_view", "ID view"),
        Binding("/", "focus_search", "Search"),
        Binding("escape", "clear_search", "Clear"),
        Binding("m", "make_safe", "Make safe"),
        Binding("h", "handoff", "Handoff"),
        Binding("H", "project_handoff", "Combined handoff"),
        Binding("s", "summary", "Summary"),
        Binding("a", "archive", "Archive"),
        Binding("e", "export_resume", "Export"),
        Binding("y", "copy_session_id", "Copy ID"),
        Binding("o", "launch_resume", "Open"),
        Binding("i", "inject_handoff", "Inject"),
        Binding("w", "recovery_wizard", "Wizard"),
        Binding("c", "compare", "Compare"),
        Binding("g", "health", "Health"),
        Binding("t", "project_timeline", "Timeline"),
        Binding("j", "project_dashboard", "Projects"),
        Binding("n", "session_note", "Note"),
        Binding("k", "backup_browser", "Backups"),
        Binding("b", "bulk_cleanup", "Bulk plan"),
        Binding("p", "toggle_pin", "Pin"),
        Binding("d", "doctor", "Doctor"),
        Binding("f", "doctor_fixes", "Fix"),
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
        self.sort_column: str | None = None
        self.sort_descending = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main"):
            with Vertical(id="left"):
                with Horizontal(id="toolbar"):
                    yield Static("Sessions", classes="title")
                    yield Select(
                        [(self.controller.agent_label(choice.key), choice.key) for choice in self.controller.agent_choices],
                        value=self.controller.agent_key,
                        allow_blank=False,
                        id="agent",
                        classes="compact-select",
                        compact=True,
                    )
                    yield Select(
                        [("Recent", "recent"), ("Project", "project"), ("Readiness", "readiness"), ("Pinned", "pinned")],
                        value="recent",
                        allow_blank=False,
                        id="group",
                        classes="compact-select",
                        compact=True,
                    )
                    yield Select(
                        [("Same", "same"), ("Codex", "codex"), ("Claude", "claude")],
                        value="same",
                        allow_blank=False,
                        id="target",
                        classes="compact-select",
                        compact=True,
                    )
                    yield Select(
                        [("Private", "private"), ("Shareable", "shareable"), ("Public", "public")],
                        value="shareable",
                        allow_blank=False,
                        id="scrub",
                        classes="compact-select",
                        compact=True,
                    )
                yield Input(placeholder="Filter text or agent:/project:/cwd:/model:/status:/file:/artifact:", id="search", compact=True)
                yield DataTable(id="sessions", cursor_type="row", zebra_stripes=True)
            with Vertical(id="right"):
                yield Static("Session Details", classes="title")
                yield Markdown("", id="details")
        yield Static("", id="status")

    def on_mount(self) -> None:
        self.title = f"Agent Lifeboat {__version__}"
        self.install_tooltips()
        self.refresh_rows()
        self.table.focus()
        self.set_status(
            f"Ready on {self.controller.store.display_name}. Use arrows to move, click or press Enter for actions, / to search."
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
            "Recent shows newest sessions first. Project groups sessions by cwd/repo. Pinned shows only pinned sessions. "
            "Readiness sorts by recovery state such as Ready, Partial, Needs handoff, or Missing."
        )
        self.query_one("#target").tooltip = "Choose the agent you plan to resume in. Cross-agent handoffs add target-specific restart notes."
        self.query_one("#scrub").tooltip = (
            "Private keeps more recovery detail, Shareable is the normal redacted default, Public trims more aggressively."
        )
        self.search.tooltip = "Filter by text, or use agent:, project:, cwd:, model:, status:, file:, and artifact: prefixes."
        self.table.tooltip = (
            "Use arrow keys to select a session. Click column headers to sort. Click a row or press Enter for actions. Press v to toggle an ID-first table view."
        )
        self.details.tooltip = "Selected session details, artifact history, transcript preview, readiness reasons, and available actions."
        self.status.tooltip = "Last action result or warning. Injection and purge write backups or recovery context first."

    def open_context_menu(self) -> None:
        row = self.current_row()
        if not row:
            self.set_status("No session selected.")
            return
        self.push_screen(SessionContextMenu(row), self.handle_context_action)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.widget is self.table and event.button != 1:
            event.prevent_default()
            event.stop()

    def handle_context_action(self, action: str | None) -> None:
        if not action:
            self.table.focus()
            return
        handlers = {
            "launch_resume": self.action_launch_resume,
            "copy_session_id": self.action_copy_session_id,
            "make_safe": self.action_make_safe,
            "handoff": self.action_handoff,
            "project_handoff": self.action_project_handoff,
            "summary": self.action_summary,
            "archive": self.action_archive,
            "export_resume": self.action_export_resume,
            "inject_handoff": self.action_inject_handoff,
            "recovery_wizard": self.action_recovery_wizard,
            "compare": self.action_compare,
            "health": self.action_health,
            "project_timeline": self.action_project_timeline,
            "project_dashboard": self.action_project_dashboard,
            "session_note": self.action_session_note,
            "backup_browser": self.action_backup_browser,
            "toggle_pin": self.action_toggle_pin,
            "restore_preview": self.action_restore_preview,
            "purge_preview": self.action_purge_preview,
            "doctor": self.action_doctor,
            "doctor_fixes": self.action_doctor_fixes,
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
        return f"Selected {self.selected_session_id}. Press Enter for actions or v to toggle ID view."

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
        table.add_columns(*[self.column_label(column) for column in self.table_columns()])
        pinned = self.controller.pins.load()
        for row in self.sorted_rows()[:500]:
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

    def table_columns(self) -> tuple[str, ...]:
        return ID_COLUMNS if self.show_session_ids else STANDARD_COLUMNS

    def column_label(self, column: str) -> str:
        label = COLUMN_LABELS[column]
        if column != self.sort_column:
            return label
        return f"{label} {'v' if self.sort_descending else '^'}"

    def sorted_rows(self) -> list[dict]:
        if not self.sort_column:
            return list(self.rows)
        return sorted(
            self.rows,
            key=self.sort_key_for(self.sort_column),
            reverse=self.sort_descending,
        )

    def sort_key_for(self, column: str):
        pinned = self.controller.pins.load()

        def key(row: dict) -> tuple:
            sid = str(row.get("id") or "")
            state = self.controller.state_for(row)
            title = str(row.get("title") or row.get("preview") or "")
            values = {
                "pin": 1 if self.controller.pin_key(sid) in pinned else 0,
                "ready": state.readiness.rank,
                "project": project_label(row, max_chars=80).lower(),
                "file": self.controller.store.file_status(row).lower(),
                "artifacts": (
                    len(state.artifacts.handoffs)
                    + len(state.artifacts.summaries)
                    + len(state.artifacts.archives)
                    + len(state.artifacts.resume_packages)
                ),
                "size": state.size,
                "updated": int(row.get("updated_at") or 0),
                "title": title.lower(),
                "session": sid,
            }
            value = values.get(column, "")
            return (value is None, value, sid)

        return key

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        columns = self.table_columns()
        if event.column_index < 0 or event.column_index >= len(columns):
            return
        column = columns[event.column_index]
        if column == self.sort_column:
            self.sort_descending = not self.sort_descending
        else:
            self.sort_column = column
            self.sort_descending = column in DEFAULT_DESCENDING_SORTS
        self.render_table()
        self.table.focus()
        direction = "descending" if self.sort_descending else "ascending"
        self.set_status(f"Sorted by {COLUMN_LABELS[column]} ({direction}).")

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
        self.open_context_menu()

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

    def action_doctor_fixes(self) -> None:
        lines = self.controller.doctor_fix_lines()
        self.details.update(doctor_fixes_markdown(lines))
        self.set_status("Safe doctor fixes applied.")

    def action_health(self) -> None:
        row = self.current_row()
        if not row:
            return
        detail = self.controller.detail_for(row)
        self.details.update(health_markdown(detail))
        self.set_status(f"Health loaded: {detail.health.label} {detail.health.score}/100.")

    def action_project_dashboard(self) -> None:
        summaries = self.controller.project_dashboard(self.rows[:500])
        self.details.update(project_dashboard_markdown(summaries))
        self.set_status(f"Project dashboard loaded for {len(summaries)} visible projects.")

    def action_project_timeline(self) -> None:
        row = self.current_row()
        if not row:
            return
        entries = self.controller.project_timeline(row, self.rows[:500])
        self.details.update(project_timeline_markdown(project_key(row), entries))
        self.set_status(f"Project timeline loaded with {len(entries)} visible sessions.")

    def action_recovery_wizard(self) -> None:
        row = self.current_row()
        if not row:
            return
        self.details.update(recovery_wizard_markdown(self.controller.detail_for(row)))
        self.set_status("Recovery wizard loaded.")

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

    def action_project_handoff(self) -> None:
        row = self.current_row()
        if not row:
            return
        self.push_screen(CombinedHandoffPicker(self.rows, self.selected_session_id), self.handle_combined_handoff_selection)

    def handle_combined_handoff_selection(self, session_ids: tuple[str, ...] | None) -> None:
        self.table.focus()
        if not session_ids:
            self.set_status("Combined handoff cancelled.")
            return
        selected = set(session_ids)
        rows = [row for row in self.rows if str(row.get("id") or "") in selected]
        result, error = self.controller.write_combined_handoff(
            rows,
            scrub_profile=self.scrub_profile,
            target_agent=self.target_agent,
        )
        if error:
            self.set_status(error)
            return
        self.refresh_rows()
        self.set_status(f"Wrote combined handoff from {len(rows)} sessions: {result.path}")

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

    def action_make_safe(self) -> None:
        row = self.current_row()
        if not row:
            return
        result, error = self.controller.make_safe(row, scrub_profile=self.scrub_profile, target_agent=self.target_agent)
        if error:
            self.set_status(error)
            return
        self.refresh_rows()
        self.details.update(safe_bundle_markdown(result))
        self.set_status(f"Made session safe: {result.handoff.path}")

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

    def action_session_note(self) -> None:
        row = self.current_row()
        if not row:
            self.set_status("No session selected.")
            return
        session_id = str(row.get("id") or "")
        note = self.controller.note_for(row)
        self.push_screen(NoteEditor(session_id, note.text if note else ""), self.handle_note_result)

    def handle_note_result(self, result: tuple[str, str] | None) -> None:
        self.table.focus()
        row = self.current_row()
        if not row:
            return
        session_id = str(row.get("id") or "")
        if not result:
            self.set_status("Note edit cancelled.")
            return
        mode, text = result
        if mode == "clear":
            self.controller.clear_note(row)
            self.refresh_rows()
            self.details.update(session_note_markdown(session_id, None))
            self.set_status(f"Cleared note for {session_id}.")
            return
        note = self.controller.set_note(row, text)
        self.refresh_rows()
        self.details.update(session_note_markdown(session_id, note))
        self.set_status(f"Saved note for {session_id}." if note else f"Cleared note for {session_id}.")

    def action_backup_browser(self) -> None:
        row = self.current_row()
        if not row:
            return
        backups, error = self.controller.backups_for(row)
        if error:
            self.set_status(error)
            return
        if not backups:
            context, context_error = self.controller.recovery_context(row)
            if not context:
                self.set_status(context_error or "Selected session cannot be restored.")
                return
            self.details.update(restore_preview_markdown(context.session_file_path, backups))
            self.set_status(f"No backups found for {context.session_id}.")
            return
        self.push_screen(BackupPicker(str(row.get("id") or ""), backups), self.handle_backup_selection)

    def handle_backup_selection(self, backup_path: str | None) -> None:
        self.table.focus()
        row = self.current_row()
        if not row:
            return
        session_id = str(row.get("id") or "")
        if not backup_path:
            self.set_status("Backup restore cancelled.")
            return
        result, error = self.controller.restore_backup(row, Path(backup_path))
        if error:
            self.set_status(error)
            return
        self.pending_restore = None
        self.refresh_rows()
        self.details.update(restore_complete_markdown(result))
        self.set_status(f"Restored {session_id} from {result.backup_path}.")

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
        if len(self.rows) < 2:
            self.set_status("At least two visible sessions are required for injection.")
            return

        self.push_screen(InjectionPicker(self.rows, self.selected_session_id), self.handle_injection_selection)

    def handle_injection_selection(self, selection: tuple[tuple[str, ...], str] | None) -> None:
        self.table.focus()
        if not selection:
            self.set_status("Injection cancelled.")
            return
        source_ids, target_id = selection
        source_rows = [row for row in self.rows if str(row.get("id") or "") in source_ids]
        target_row = next((row for row in self.rows if str(row.get("id") or "") == target_id), None)
        if not source_rows or not target_row:
            self.set_status("Injection selection is no longer visible. Refresh and try again.")
            return
        source_contexts: list[RecoveryContext] = []
        for source_row in source_rows:
            source_context, context_error = self.controller.recovery_context(source_row)
            if not source_context:
                self.set_status(context_error or "Selected source session cannot be used for injection.")
                return
            source_contexts.append(source_context)
        result, error = self.controller.inject_sources_into(
            source_contexts,
            target_row,
            scrub_profile=self.scrub_profile,
            target_agent=self.target_agent,
        )
        if error:
            self.set_status(error)
            return
        self.selected_session_id = target_id
        self.refresh_rows()
        self.details.update(injection_markdown(result))
        source_label = source_ids[0] if len(source_ids) == 1 else f"{len(source_ids)} sessions"
        self.set_status(f"Injected {source_label} into {target_id}. Backup: {result.backup_path}")

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
                left_health=self.controller.health_for(left),
                right_health=self.controller.health_for(row),
                left_preview=self.controller.preview_for(self.controller.store.session_file_path(left)),
                right_preview=self.controller.preview_for(self.controller.store.session_file_path(row)),
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
