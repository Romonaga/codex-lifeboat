from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class SessionIdContext(Protocol):
    session_id: str


@dataclass
class LifeboatUiState:
    selected_session_id: str | None = None
    compare_session_id: str | None = None
    pending_purge: str | None = None
    pending_bulk_purge: str | None = None
    pending_restore: str | None = None
    show_session_ids: bool = False
    inject_source_context: SessionIdContext | None = None
    sort_column: str | None = None
    sort_descending: bool = False
    restoring_table_cursor: bool = False

    def reset_for_agent_switch(self) -> None:
        self.selected_session_id = None
        self.compare_session_id = None
        self.pending_purge = None
        self.pending_bulk_purge = None
        self.pending_restore = None
        self.inject_source_context = None

    def select_session(self, session_id: str | None) -> None:
        self.selected_session_id = session_id
        self.pending_purge = None
        self.pending_bulk_purge = None
        self.pending_restore = None

    def restore_selected_session(self, session_id: str) -> None:
        self.selected_session_id = session_id
        self.clear_restore_and_purge()

    def clear_restore_and_purge(self) -> None:
        self.pending_purge = None
        self.pending_bulk_purge = None
        self.pending_restore = None

    def clear_pending_restore(self) -> None:
        self.pending_restore = None

    def arm_purge(self, session_id: str) -> bool:
        if self.pending_purge == session_id:
            return True
        self.pending_purge = session_id
        self.pending_bulk_purge = None
        self.pending_restore = None
        return False

    def complete_purge(self) -> None:
        self.pending_purge = None

    def arm_bulk_purge(self, fingerprint: str) -> bool:
        if self.pending_bulk_purge == fingerprint:
            return True
        self.pending_bulk_purge = fingerprint
        self.pending_purge = None
        self.pending_restore = None
        return False

    def complete_bulk_purge(self) -> None:
        self.pending_bulk_purge = None

    def arm_restore(self, session_id: str | None) -> None:
        self.pending_restore = session_id
        if session_id:
            self.pending_purge = None
            self.pending_bulk_purge = None

    def restore_is_armed(self, session_id: str) -> bool:
        return self.pending_restore == session_id

    def set_compare_base(self, session_id: str) -> None:
        self.compare_session_id = session_id

    def clear_compare(self) -> None:
        self.compare_session_id = None

    def cancel_pending_actions(self) -> list[str]:
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
        if self.pending_bulk_purge:
            cancelled.append("bulk purge confirmation")
            self.pending_bulk_purge = None
        if self.pending_restore:
            cancelled.append(f"restore confirmation {self.pending_restore}")
            self.pending_restore = None
        return cancelled

    def toggle_id_view(self) -> bool:
        self.show_session_ids = not self.show_session_ids
        return self.show_session_ids

    def apply_sort(self, column: str, *, default_descending: bool) -> None:
        if column == self.sort_column:
            self.sort_descending = not self.sort_descending
            return
        self.sort_column = column
        self.sort_descending = default_descending

    def begin_table_restore(self) -> None:
        self.restoring_table_cursor = True

    def end_table_restore(self) -> None:
        self.restoring_table_cursor = False
