# Agent Lifeboat

Agent Lifeboat is a local rescue tool for AI coding-agent sessions that have become too large, slow, or painful to resume.

It currently supports Codex and Claude Code sessions. It helps you browse sessions, inspect recovery readiness and health, add local notes, dump a paste-ready handoff, create a compact recovery summary, archive the raw session file, export a resume package, pin sessions you care about, and purge stale sessions only after you have something you can feed into a fresh AI session.

## What It Does

- Textual terminal application for normal use.
- Agent selector for Codex or Claude Code.
- Project, readiness, and pinned-session grouping.
- Recovery readiness labels for missing, partial, handoff-needed, and ready sessions.
- Health scores for ready, recoverable, risky, and broken sessions.
- Project dashboard and per-project timeline views.
- Local session notes stored beside app config.
- Handoff history detection for generated handoffs, summaries, archives, and resume packages.
- Rich transcript preview with latest user request, latest assistant result, commands, paths, blockers, and transcript counts.
- Compare view for two visible sessions.
- One-key Make Safe action that writes a handoff, summary, and archive.
- Full Markdown handoff for pasting into a fresh AI session.
- Compact recovery summary focused on goals, paths, commands, blockers, and recent context.
- Resume package export with handoff, summary, archive, and metadata.
- Click/Enter session action menu, with keyboard shortcuts still available for power use.
- One-key resume launcher that opens a terminal in the session cwd and starts Codex or Claude resume.
- Target-agent handoff notes for Codex-to-Codex, Codex-to-Claude, Claude-to-Claude, and Claude-to-Codex recovery.
- Scrub profiles for private, shareable, and public recovery artifacts.
- Guarded handoff injection picker that copies one or more compact recovery notes into another session file only after creating a backup.
- Backup browser for restoring a selected injection/restore backup.
- Recovery wizard view for the selected session.
- Doctor report and safe doctor fixes for local app directories.
- Filter search by text or `agent:`, `project:`, `cwd:`, `model:`, `status:`, `file:`, and `artifact:`.
- Pins to protect important sessions from bulk purge.
- Archive mode that stores session JSONL plus metadata in `tar.gz`.
- Safe purge with dry-run, confirmation, automatic handoff by default, and optional archive.
- Secret redaction by default, plus a scanner for generated handoff files.
- First-run configuration so paths are not hardcoded.
- Optional Markdown splitting for very large handoffs.

The app is built with Textual, so it stays in the terminal while still feeling like a proper program. Domain logic lives in reusable Python modules so the interface does not duplicate session, handoff, doctor, pin, archive, or purge behavior.

## Session Files

A session file is the local JSONL transcript for a conversation. Codex stores session files under `~/.codex`; Claude Code stores them under `~/.claude/projects`. If the session file is available, Lifeboat can build full handoffs, compact summaries, archives, and guarded purges from the transcript.

If a Codex session file is missing, Lifeboat can still show the metadata Codex left in its SQLite index: title, preview, cwd, timestamps, token counter, session id, and the last known session file path. It cannot reconstruct the full transcript, tool outputs, or a real handoff without that JSONL file. Claude Code does not expose the same SQLite index here, so Claude recovery depends on the JSONL session file being present.

## Install

Clone the repo:

```bash
git clone https://github.com/Romonaga/codex-lifeboat.git
cd codex-lifeboat
```

Quick local install:

```bash
./install.sh
```

The installer creates `.venv/`, installs the package with its Textual dependency, and writes an `agent-lifeboat` launcher to `~/.local/bin`.

For a manual development install:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

Then run:

```bash
agent-lifeboat
```

This launches the Textual terminal app.

## Program Layout

The code is split by domain:

- `codex_lifeboat/config.py`: app configuration and paths.
- `codex_lifeboat/agents.py`: agent detection and backend selection.
- `codex_lifeboat/sessions.py`: Codex session discovery, lookup, search, and size accounting.
- `codex_lifeboat/claude.py`: Claude Code session discovery and transcript normalization.
- `codex_lifeboat/intelligence.py`: transcript preview, project grouping, filters, and recovery readiness.
- `codex_lifeboat/health.py`: session health scoring and recommended next actions.
- `codex_lifeboat/projects.py`: project dashboard summaries and timelines.
- `codex_lifeboat/artifacts.py`: generated handoff, summary, archive, and resume-package history.
- `codex_lifeboat/handoff.py`: full handoffs, compact summaries, splitting, and secret scanning.
- `codex_lifeboat/recovery.py`: reusable recovery actions, scrub profiles, target-agent notes, resume export, and injection.
- `codex_lifeboat/safety.py`: one-key safe bundle creation.
- `codex_lifeboat/launcher.py`: external terminal and agent resume launching.
- `codex_lifeboat/doctor.py`: health reports and risk classification.
- `codex_lifeboat/maintenance.py`: safe local fix-ups for app directories.
- `codex_lifeboat/pins.py`: pinned session storage.
- `codex_lifeboat/notes.py`: local session note storage.
- `codex_lifeboat/operations.py`: archive and purge operations.
- `codex_lifeboat/controller.py`: app orchestration that keeps feature logic out of the UI.
- `codex_lifeboat/views.py`: Markdown rendering for details, compare, bulk plans, and action results.
- `codex_lifeboat/tui.py`: Textual widget and event hooks.

## First Run

Default config path:

```text
~/.config/agent-lifeboat/config.json
```

Environment overrides:

```text
AGENT_LIFEBOAT_CONFIG
AGENT_LIFEBOAT_OUTPUT_DIR
CODEX_HOME
CLAUDE_HOME
```

## App Mode

Run the program:

```bash
agent-lifeboat
```

The terminal app provides a bordered session explorer, an agent selector, project/readiness/pinned grouping, filtered search, pinned-session state, readiness and health status, artifact history, notes, project dashboard/timeline views, a click/Enter action menu, full handoff generation, compact summary generation, Make Safe, archive, resume export, direct terminal resume launching, guarded injection, selected-backup restore, guarded purge, recovery wizard, and doctor tools.

Click a session row or press Enter to open its action menu. Keyboard shortcuts still work, but the bottom command strip is hidden to keep the screen quieter.

Common keys:

```text
h        write full handoff
H        select visible sessions to combine into one handoff
m        make safe: write handoff, summary, and archive
s        write compact summary
a        archive session file
e        export resume package
y        copy selected session id to clipboard
o        open a terminal in the session cwd and resume the selected agent session
i        open source/target injection picker and inject after backup
c        compare two sessions
g        show health details
t        show timeline for the selected project
j        show project dashboard for visible sessions
n        edit local note for selected session
k        browse and restore a selected backup
w        show recovery wizard
b        show bulk cleanup plan
p        toggle pin
x        dry-run purge
ctrl+x   purge after two-step confirmation
u        preview latest backup restore
ctrl+u   restore latest backup after preview
d        doctor report
f        run safe doctor fixes
Esc      cancel pending injection, compare, purge/restore confirmation, or clear search
```

Injection is intentionally conservative. Press `i` to open a source/target picker. Lifeboat writes a compact recovery summary from the source, backs up the target JSONL beside the original file, and appends a clearly marked synthetic user message to the target. The picker can combine same-project source sessions into one injected summary. If an agent changes its session format, restore from the backup.

Resume launching tries `tilix` first, then falls back through `gnome-terminal`, `konsole`, `xfce4-terminal`, `kitty`, `alacritty`, and `xterm`.

Restore is also guarded. Press `u` on a session to preview the newest `.bak-*` file Lifeboat can find beside that session file, then press `ctrl+u` to restore it. Press `k` to browse backups and restore a specific one. Lifeboat saves the current session file as `.pre-restore-*` before replacing it.

Full handoffs start with a `Continuation Snapshot` before the chronological transcript. That front-loads the latest user requests, assistant results, commands, paths, and blockers without internal tool trace details, so a new session can recover current state even if a reader or tool only shows the beginning of the file.

Secret redaction is best-effort. Review generated files before sharing them.

## Development

Run checks:

```bash
python3 -m compileall codex_lifeboat
python3 -m unittest discover -s tests
```

Run from the repo:

```bash
python3 -m codex_lifeboat.tui
```

Build a standalone executable with PyInstaller:

```bash
scripts/build-standalone.sh
```

The standalone binary is written to `dist/agent-lifeboat`, with a versioned copy such as `dist/agent-lifeboat-0.3.0` and build metadata in `dist/build-info.json`. This is optional; the normal installed program remains `agent-lifeboat`.

## License

MIT
