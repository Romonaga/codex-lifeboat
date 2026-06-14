from __future__ import annotations

from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from textual.widgets import DataTable, Input, Markdown, Select, Static

from codex_lifeboat.tui import LifeboatTui


class TooltipTests(IsolatedAsyncioTestCase):
    async def test_main_widgets_have_hover_text(self) -> None:
        with TemporaryDirectory() as tmp:
            env = {
                "AGENT_LIFEBOAT_CONFIG": f"{tmp}/config/config.json",
                "AGENT_LIFEBOAT_OUTPUT_DIR": f"{tmp}/output",
                "CODEX_HOME": f"{tmp}/codex",
                "CLAUDE_HOME": f"{tmp}/claude",
            }
            with patch.dict("os.environ", env, clear=False):
                app = LifeboatTui()
                async with app.run_test(size=(120, 32)) as pilot:
                    await pilot.pause()

                    expected = {
                        "#agent": (Select, "Choose which local agent session store to browse"),
                        "#group": (Select, "Pinned shows only pinned sessions"),
                        "#target": (Select, "Choose the agent you plan to resume in"),
                        "#scrub": (Select, "Shareable is the normal redacted default"),
                        "#search": (Input, "Filter by text"),
                        "#sessions": (DataTable, "Click a row or press Enter for actions"),
                        "#details": (Markdown, "Selected session details"),
                        "#status": (Static, "Last action result or warning"),
                    }

                    for selector, (widget_type, text) in expected.items():
                        widget = app.query_one(selector, widget_type)
                        self.assertIn(text, str(widget.tooltip), selector)
