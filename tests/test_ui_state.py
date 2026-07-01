from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from codex_lifeboat.ui_state import LifeboatUiState


class UiStateTests(TestCase):
    def test_select_session_clears_destructive_confirmations(self) -> None:
        state = LifeboatUiState(
            selected_session_id="old",
            pending_purge="old",
            pending_bulk_purge="visible",
            pending_restore="old",
        )

        state.select_session("new")

        self.assertEqual(state.selected_session_id, "new")
        self.assertIsNone(state.pending_purge)
        self.assertIsNone(state.pending_bulk_purge)
        self.assertIsNone(state.pending_restore)

    def test_purge_requires_same_session_twice(self) -> None:
        state = LifeboatUiState()

        self.assertFalse(state.arm_purge("abc"))
        self.assertEqual(state.pending_purge, "abc")
        self.assertTrue(state.arm_purge("abc"))

        state.complete_purge()

        self.assertIsNone(state.pending_purge)

    def test_bulk_purge_requires_same_visible_set_twice(self) -> None:
        state = LifeboatUiState()

        self.assertFalse(state.arm_bulk_purge("a|b"))
        self.assertEqual(state.pending_bulk_purge, "a|b")
        self.assertTrue(state.arm_bulk_purge("a|b"))

        state.complete_bulk_purge()

        self.assertIsNone(state.pending_bulk_purge)

    def test_restore_clears_purge_and_can_be_confirmed(self) -> None:
        state = LifeboatUiState(pending_purge="abc", pending_bulk_purge="a|b")

        state.arm_restore("abc")

        self.assertIsNone(state.pending_purge)
        self.assertIsNone(state.pending_bulk_purge)
        self.assertTrue(state.restore_is_armed("abc"))

    def test_cancel_pending_actions_returns_user_visible_labels(self) -> None:
        state = LifeboatUiState(
            compare_session_id="base",
            pending_purge="purge",
            pending_bulk_purge="a|b",
            pending_restore="restore",
            inject_source_context=SimpleNamespace(session_id="source"),
        )

        cancelled = state.cancel_pending_actions()

        self.assertEqual(
            cancelled,
            [
                "injection source source",
                "compare base base",
                "purge confirmation purge",
                "bulk purge confirmation",
                "restore confirmation restore",
            ],
        )
        self.assertIsNone(state.compare_session_id)
        self.assertIsNone(state.pending_purge)
        self.assertIsNone(state.pending_bulk_purge)
        self.assertIsNone(state.pending_restore)
        self.assertIsNone(state.inject_source_context)

    def test_apply_sort_uses_default_then_toggles(self) -> None:
        state = LifeboatUiState()

        state.apply_sort("updated", default_descending=True)
        self.assertEqual(state.sort_column, "updated")
        self.assertTrue(state.sort_descending)

        state.apply_sort("updated", default_descending=True)
        self.assertFalse(state.sort_descending)

        state.apply_sort("project", default_descending=False)
        self.assertEqual(state.sort_column, "project")
        self.assertFalse(state.sort_descending)
