# Codex Lifeboat

Codex Lifeboat is a local rescue tool for Codex CLI sessions that have become too large, slow, or painful to resume.

It helps you pick a session, dump a paste-ready handoff, create a compact recovery summary, archive the raw rollout, pin sessions you care about, and purge stale sessions only after you have something you can feed into a new Codex session.

## What It Does

- Menu-first ASCII interface for normal use.
- Full Markdown handoff for pasting into a fresh Codex session.
- Compact recovery summary focused on goals, paths, commands, blockers, and recent context.
- Doctor report for local Codex session health.
- Largest-session view to find the sessions most likely to cause trouble.
- Session search by title, preview, cwd, session id, rollout path, or optional file contents.
- Pins to protect important sessions from bulk purge.
- Archive mode that stores rollout JSONL plus metadata in `tar.gz`.
- Safe purge with dry-run, confirmation, automatic handoff by default, and optional archive.
- Secret redaction by default, plus a scanner for generated handoff files.
- First-run configuration so paths are not hardcoded.
- Optional Markdown splitting for very large handoffs.

No third-party Python packages are required.

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

Or install as a Python command:

```bash
python3 -m pip install .
```

Then run:

```bash
codex-lifeboat
```

## First Run

Configure your Codex state directory and output directory:

```bash
codex-lifeboat --configure
```

Default config path:

```text
~/.config/codex-lifeboat/config.json
```

Environment overrides:

```text
CODEX_LIFEBOAT_CONFIG
CODEX_LIFEBOAT_OUTPUT_DIR
CODEX_HOME
```

Show the active config:

```bash
codex-lifeboat --show-config
```

## Menu Mode

Run with no arguments:

```bash
codex-lifeboat
```

The menu gives you:

```text
[D] Dump full handoff       [S] Compact summary
[A] Archive session         [P] Purge session with handoff
[L] Largest sessions        [F] Find sessions
[H] Doctor report           [N] Pins
[C] Configure               [Q] Quit
```

When selecting a session, you can enter a table number, a session id, an id fragment, or `/search text`.

Keyboard controls:

- Menu letters act immediately. Press `D`, `S`, `A`, `P`, `L`, `F`, `H`, `N`, `C`, or `Q`; Enter is not required.
- Session pickers with 9 or fewer choices accept `1` through `9` immediately.
- Larger pickers still use Enter so two-digit selections and ID fragments are possible.
- Menu screens redraw after actions, keeping completed prompts and reports from cluttering the next choice.
- `q`, `quit`, `exit`, `Esc`, and `Ctrl-C` cancel interactive prompts.

## Recovery Commands

Dump a full handoff:

```bash
codex-lifeboat SESSION_ID
```

Create a compact restart summary:

```bash
codex-lifeboat --summary SESSION_ID
```

Include truncated tool output in a full handoff:

```bash
codex-lifeboat SESSION_ID --include-tools
```

Split large Markdown output:

```bash
codex-lifeboat SESSION_ID --split-chars 200000
```

Scan a generated file for likely secrets:

```bash
codex-lifeboat --scan-secrets ~/codex-lifeboat-dumps/SESSION_ID-handoff.md
```

Secret redaction is best-effort. Review files before sharing them.

## Find Sessions

List recent sessions:

```bash
codex-lifeboat --list 20
```

Show largest sessions:

```bash
codex-lifeboat --largest 15
```

Search metadata:

```bash
codex-lifeboat --search "timeout"
```

Search rollout contents too:

```bash
codex-lifeboat --search "important phrase" --scan-content
```

## Doctor Report

Generate a local health report:

```bash
codex-lifeboat --doctor
```

Write it to a file:

```bash
codex-lifeboat --doctor -o ~/codex-lifeboat-dumps/doctor.md
```

The report highlights storage size, huge sessions, impossible token counters, missing rollout paths, orphan rollout files, and pinned sessions. Risky sessions include a `Reason` column showing which threshold matched.

## Pins

Pin a session so bulk purge skips it:

```bash
codex-lifeboat --pin SESSION_ID
```

Remove a pin:

```bash
codex-lifeboat --unpin SESSION_ID
```

List pins:

```bash
codex-lifeboat --list-pins
```

## Archive And Purge

Archive a session without purging:

```bash
codex-lifeboat --archive SESSION_ID
```

Dry-run a purge:

```bash
codex-lifeboat --purge --dry-run SESSION_ID
```

Purge a session:

```bash
codex-lifeboat --purge SESSION_ID
```

By default, purge writes a full handoff first. To skip that:

```bash
codex-lifeboat --purge --no-dump-before-purge SESSION_ID
```

Archive and purge:

```bash
codex-lifeboat --purge --archive SESSION_ID
```

Bulk purge every unpinned session:

```bash
codex-lifeboat --purge-all-unpinned --dry-run
codex-lifeboat --purge-all-unpinned
```

Bulk purge also writes handoffs by default. Use `--no-dump-before-purge` only when you are certain you do not need recovery files.

Purge removes the rollout JSONL file, matching rows from the Codex thread index, related dynamic tool/spawn-edge rows, matching log rows, and then vacuums the SQLite databases.

## Development

Run checks:

```bash
python3 -m py_compile codex_lifeboat.py
```

Run from the repo:

```bash
./codex_lifeboat.py --doctor
```

## License

MIT
