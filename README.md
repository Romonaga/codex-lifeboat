# Codex Lifeboat

Codex Lifeboat is a small local utility for rescuing useful context from Codex CLI session files before a session becomes too large, times out, or needs to be purged.

It creates a paste-ready Markdown handoff from a Codex rollout JSONL file, then optionally removes the session from local Codex state.

## Why

Long Codex sessions can become expensive to resume, difficult to inspect, or large enough to make local session management painful. Codex Lifeboat gives you a safer workflow:

1. Pick a session.
2. Dump the conversation into a Markdown handoff.
3. Paste that handoff into a new Codex session.
4. Purge the old session only when you are ready.

The tool streams JSONL line by line, so it can process multi-GB sessions without loading the whole file into memory.

## Features

- Interactive session picker.
- Search by session ID, title, preview, cwd, or rollout path.
- Optional content scan for hard-to-find sessions.
- Markdown handoff output designed to paste into a new Codex thread.
- Best-effort secret redaction by default.
- Optional truncated tool output capture.
- First-run configuration with no hardcoded machine paths.
- Safe purge mode with dry-run, full-ID confirmation, and optional dump-before-purge.
- Clean `q`, `quit`, `exit`, and `Ctrl-C` cancellation.

## Requirements

- Python 3.10 or newer.
- A local Codex state directory, usually `~/.codex`.

No third-party Python packages are required.

## Install

Clone the repo and make the script available somewhere on your `PATH`:

```bash
git clone https://github.com/Romonaga/codex-lifeboat.git
cd codex-lifeboat
chmod +x codex_lifeboat.py
```

Optional symlink:

```bash
mkdir -p ~/.local/bin
ln -s "$PWD/codex_lifeboat.py" ~/.local/bin/codex-lifeboat
```

Then run:

```bash
codex-lifeboat --help
```

## First Run

Configure where Codex state lives and where handoff files should be written:

```bash
codex-lifeboat --configure
```

Default config path:

```text
~/.config/codex-lifeboat/config.json
```

You can also configure non-interactively:

```bash
codex-lifeboat --configure \
  --codex-home ~/.codex \
  --output-dir ~/codex-lifeboat-dumps
```

Show the active config:

```bash
codex-lifeboat --show-config
```

Environment overrides:

```text
CODEX_LIFEBOAT_CONFIG
CODEX_LIFEBOAT_OUTPUT_DIR
CODEX_HOME
```

## Dump A Session

Run without arguments to pick from recent sessions:

```bash
codex-lifeboat
```

List recent sessions:

```bash
codex-lifeboat --list 20
```

Dump by session ID:

```bash
codex-lifeboat 019e40f3-a7e0-7950-ba84-0468e83a9f11
```

Dump by a direct rollout file path:

```bash
codex-lifeboat ~/.codex/sessions/2026/06/11/rollout-2026-06-11T16-55-57-019eb878-60f7-7a82-8dc3-ac8a9f8442f6.jsonl
```

Output defaults to:

```text
<configured output_dir>/<session-id>-handoff.md
```

That Markdown file starts with a restart prompt you can paste into a new Codex session.

## Search And Pick

Search indexed session metadata:

```bash
codex-lifeboat --search ollama
```

Search, then pick a result to dump:

```bash
codex-lifeboat --search ollama --pick
```

Scan session file contents too:

```bash
codex-lifeboat --search "some exact phrase" --scan-content
```

Content scans can be slow on very large session files.

## Include Tool Output

By default, Codex Lifeboat includes tool calls but omits bulky tool output. To include truncated tool output:

```bash
codex-lifeboat SESSION_ID --include-tools
```

Tune truncation:

```bash
codex-lifeboat SESSION_ID --include-tools --tool-chars 4000 --message-chars 20000
```

## Purge A Session

Always inspect first:

```bash
codex-lifeboat --purge --dry-run SESSION_ID
```

Interactive purge:

```bash
codex-lifeboat --purge
```

Search and purge:

```bash
codex-lifeboat --search ollama --purge
```

Dump before purging:

```bash
codex-lifeboat --purge --dump-before-purge SESSION_ID
```

Non-interactive purge requires explicit confirmation:

```bash
codex-lifeboat --purge --yes SESSION_ID
```

Purge removes:

- The rollout JSONL file.
- Matching rows from the Codex thread index database.
- Related thread dynamic tool and spawn-edge rows.
- Matching log rows from Codex log databases.

It then vacuums the SQLite databases.

## Safety Notes

- Purge prompts for the full session ID unless `--yes` is supplied.
- `--dry-run` deletes nothing.
- `--dump-before-purge` is recommended for any session you might need again.
- Secret redaction is best-effort, not a guarantee. Review handoff files before sharing them.
- `q`, `quit`, `exit`, and `Ctrl-C` cancel interactive prompts.

## Development

Run a syntax check:

```bash
python3 -m py_compile codex_lifeboat.py
```

Run from the repo:

```bash
./codex_lifeboat.py --list 10
```

