from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from codex_lifeboat.controller import LifeboatController


def create_codex_state(codex_home: Path, session_id: str, rollout_path: Path) -> None:
    create_codex_state_rows(codex_home, [(session_id, rollout_path, "stale")])


def create_codex_state_rows(codex_home: Path, rows: list[tuple[str, Path, str]]) -> None:
    codex_home.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(codex_home / "state_5.sqlite") as conn:
        conn.execute(
            """
            create table threads (
                id text primary key,
                rollout_path text,
                updated_at integer,
                cwd text,
                title text,
                preview text,
                tokens_used integer
            )
            """
        )
        for index, (session_id, rollout_path, title) in enumerate(rows):
            conn.execute(
                """
                insert into threads (id, rollout_path, updated_at, cwd, title, preview, tokens_used)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, str(rollout_path), index + 1, "", title, "", 0),
            )
    with sqlite3.connect(codex_home / "logs_5.sqlite") as conn:
        conn.execute("create table logs (thread_id text, message text)")
        for session_id, _rollout_path, title in rows:
            conn.execute("insert into logs (thread_id, message) values (?, ?)", (session_id, f"{title} log"))


class PurgeTests(TestCase):
    def test_codex_missing_rollout_can_purge_stale_metadata_without_handoff(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_id = "aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb"
            codex_home = root / "codex"
            rollout_path = codex_home / "sessions" / "2026" / "06" / "rollout-missing.jsonl"
            create_codex_state(codex_home, session_id, rollout_path)
            env = {
                "AGENT_LIFEBOAT_CONFIG": str(root / "config" / "config.json"),
                "AGENT_LIFEBOAT_OUTPUT_DIR": str(root / "output"),
                "CODEX_HOME": str(codex_home),
                "CLAUDE_HOME": str(root / "claude"),
            }
            with patch.dict("os.environ", env, clear=False):
                controller = LifeboatController()
                row = controller.store.all()[0]

                lines, error = controller.purge_lines(row, dry_run=True)

                self.assertIsNone(error)
                self.assertIn("Dry run only. Nothing was deleted.", lines or [])

                handoff, lines, error = controller.purge_after_handoff(
                    row,
                    scrub_profile="shareable",
                    target_agent="codex",
                )

                self.assertIsNone(error)
                self.assertIsNone(handoff)
                self.assertIn("removed indexed thread rows: 1", lines or [])
                with sqlite3.connect(codex_home / "state_5.sqlite") as conn:
                    self.assertEqual(conn.execute("select count(*) from threads").fetchone()[0], 0)
                with sqlite3.connect(codex_home / "logs_5.sqlite") as conn:
                    self.assertEqual(conn.execute("select count(*) from logs").fetchone()[0], 0)

    def test_bulk_purge_skips_pinned_sessions_and_writes_handoff(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            purge_id = "aaaaaaaa-1111-2222-3333-000000000001"
            pinned_id = "aaaaaaaa-1111-2222-3333-000000000002"
            codex_home = root / "codex"
            purge_path = codex_home / "sessions" / "2026" / "06" / f"rollout-{purge_id}.jsonl"
            pinned_path = codex_home / "sessions" / "2026" / "06" / f"rollout-{pinned_id}.jsonl"
            purge_path.parent.mkdir(parents=True)
            message = {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "continue the cleanup"}],
                },
            }
            purge_path.write_text(json.dumps(message) + "\n", encoding="utf-8")
            pinned_path.write_text(json.dumps(message) + "\n", encoding="utf-8")
            create_codex_state_rows(
                codex_home,
                [
                    (purge_id, purge_path, "purge me"),
                    (pinned_id, pinned_path, "keep me"),
                ],
            )
            env = {
                "AGENT_LIFEBOAT_CONFIG": str(root / "config" / "config.json"),
                "AGENT_LIFEBOAT_OUTPUT_DIR": str(root / "output"),
                "CODEX_HOME": str(codex_home),
                "CLAUDE_HOME": str(root / "claude"),
            }
            with patch.dict("os.environ", env, clear=False):
                controller = LifeboatController()
                controller.refresh(query="", group_mode="recent")
                controller.pins.pin(controller.pin_key(pinned_id))
                rows = controller.refresh(query="", group_mode="recent")

                preview = controller.bulk_purge_preview(rows)

                self.assertEqual(preview.candidate_count, 1)
                self.assertEqual(preview.pinned_skipped, 1)
                self.assertTrue(any("Dry run only" in line for line in preview.lines))

                result = controller.bulk_purge_after_handoff(
                    rows,
                    scrub_profile="shareable",
                    target_agent="codex",
                )

                self.assertEqual(result.purged_count, 1)
                self.assertEqual(result.pinned_skipped, 1)
                self.assertEqual(result.errors, ())
                self.assertEqual(len(result.handoff_paths), 1)
                self.assertTrue(result.handoff_paths[0].is_file())
                self.assertFalse(purge_path.exists())
                self.assertTrue(pinned_path.exists())
                with sqlite3.connect(codex_home / "state_5.sqlite") as conn:
                    self.assertEqual(
                        conn.execute("select id from threads order by id").fetchall(),
                        [(pinned_id,)],
                    )
                with sqlite3.connect(codex_home / "logs_5.sqlite") as conn:
                    self.assertEqual(
                        conn.execute("select thread_id from logs order by thread_id").fetchall(),
                        [(pinned_id,)],
                    )
