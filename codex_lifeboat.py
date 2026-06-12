#!/usr/bin/env python3
"""Create a compact Markdown handoff from a Codex session rollout file.

The script streams rollout JSONL line by line so it can process very large
sessions without loading the whole file into memory.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import signal
import sqlite3
import sys
from pathlib import Path
from typing import Any


APP_NAME = "codex-lifeboat"
CONFIG_PATH = Path(
    os.environ.get(
        "CODEX_LIFEBOAT_CONFIG",
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        / APP_NAME
        / "config.json",
    )
)
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
OUTPUT_DIR = Path(os.environ.get("CODEX_LIFEBOAT_OUTPUT_DIR", Path.cwd() / "codex-lifeboat-dumps"))

SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9_]{16,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{16,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}\b"),
    re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{16,}"),
]

SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|authorization)\b"
    r"(\s*[:=]\s*)(\S+)"
)


class UserCancelled(Exception):
    """Raised when the user cancels an interactive prompt."""


def prompt(text: str) -> str:
    try:
        value = input(text)
    except KeyboardInterrupt as exc:
        raise UserCancelled from exc
    if value.strip().lower() in {"q", "quit", "exit"}:
        raise UserCancelled
    return value


def handle_sigint(_signum: int, _frame: Any) -> None:
    print("\nCancelled.", file=sys.stderr)
    raise SystemExit(130)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dump a Codex session into a restart-friendly Markdown handoff."
    )
    parser.add_argument(
        "session",
        nargs="?",
        help="Codex session id, rollout JSONL path, or a unique id fragment.",
    )
    parser.add_argument(
        "--list",
        nargs="?",
        const=20,
        type=int,
        metavar="N",
        help="List the N most recent indexed sessions and exit. Default N is 20.",
    )
    parser.add_argument(
        "--configure",
        action="store_true",
        help="Create or update the first-run configuration, then exit.",
    )
    parser.add_argument(
        "--show-config",
        action="store_true",
        help="Print the effective configuration and exit.",
    )
    parser.add_argument(
        "--config",
        help=f"Config JSON path. Default: {CONFIG_PATH}",
    )
    parser.add_argument(
        "--codex-home",
        help="Override Codex state directory for this run.",
    )
    parser.add_argument(
        "--output-dir",
        help="Override default handoff output directory for this run.",
    )
    parser.add_argument(
        "--search",
        metavar="TEXT",
        help="Search indexed session id, title, preview, cwd, and rollout path.",
    )
    parser.add_argument(
        "--pick",
        action="store_true",
        help="After --list or --search, prompt for a number and dump that session.",
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        help="Purge the selected session instead of dumping it.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm purge without prompting. Use carefully.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="For purge, show what would be removed without deleting anything.",
    )
    parser.add_argument(
        "--dump-before-purge",
        action="store_true",
        help="Write a Markdown handoff before purging the session.",
    )
    parser.add_argument(
        "--scan-content",
        action="store_true",
        help="With --search, also scan rollout file contents. This can be slow on huge sessions.",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output Markdown path. Defaults to <configured output_dir>/<id>-handoff.md.",
    )
    parser.add_argument(
        "--include-tools",
        action="store_true",
        help="Include truncated tool outputs. By default only tool calls are listed.",
    )
    parser.add_argument(
        "--tool-chars",
        type=int,
        default=2000,
        help="Maximum characters per tool output when --include-tools is used.",
    )
    parser.add_argument(
        "--message-chars",
        type=int,
        default=12000,
        help="Maximum characters per user/assistant message.",
    )
    parser.add_argument(
        "--keep-system",
        action="store_true",
        help="Include system/developer messages. Default omits them.",
    )
    parser.add_argument(
        "--no-redact",
        action="store_true",
        help="Disable best-effort secret redaction.",
    )
    parser.add_argument(
        "--raw-tail",
        type=int,
        default=0,
        help="Append the last N raw JSONL lines for forensic recovery.",
    )
    return parser.parse_args()


def default_config() -> dict[str, str]:
    return {
        "codex_home": str(Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()),
        "output_dir": str(
        Path(os.environ.get("CODEX_LIFEBOAT_OUTPUT_DIR", Path.cwd() / "codex-lifeboat-dumps")).expanduser()
        ),
    }


def prompt_path(label: str, current: Path) -> Path:
    value = prompt(f"{label} [{current}] (q to cancel): ").strip()
    return Path(value).expanduser() if value else current


def write_config(config_path: Path, config: dict[str, str]) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def configure(config_path: Path, *, force_prompt: bool) -> dict[str, str]:
    config = default_config()
    if config_path.exists():
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                config.update({k: str(v) for k, v in loaded.items() if k in config})
        except json.JSONDecodeError:
            pass

    if force_prompt and sys.stdin.isatty():
        print("Configure Codex Session Dump")
        print(f"Config file: {config_path}")
        config["codex_home"] = str(prompt_path("Codex home", Path(config["codex_home"])))
        config["output_dir"] = str(prompt_path("Output directory", Path(config["output_dir"])))
    elif force_prompt and not sys.stdin.isatty():
        raise SystemExit("--configure needs a TTY. Use --codex-home and --output-dir in noninteractive mode.")

    write_config(config_path, config)
    return config


def load_config(args: argparse.Namespace) -> tuple[Path, dict[str, str]]:
    config_path = Path(args.config).expanduser() if args.config else CONFIG_PATH
    if not config_path.exists():
        config = configure(config_path, force_prompt=sys.stdin.isatty())
    else:
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Config file is invalid JSON: {config_path}: {exc}") from exc
        config = default_config()
        if isinstance(loaded, dict):
            config.update({k: str(v) for k, v in loaded.items() if k in config})

    if args.codex_home:
        config["codex_home"] = str(Path(args.codex_home).expanduser())
    if args.output_dir:
        config["output_dir"] = str(Path(args.output_dir).expanduser())
    return config_path, config


def apply_config(config: dict[str, str]) -> None:
    global CODEX_HOME, OUTPUT_DIR
    CODEX_HOME = Path(config["codex_home"]).expanduser()
    OUTPUT_DIR = Path(config["output_dir"]).expanduser()


def print_config(config_path: Path) -> None:
    print(f"config_path: {config_path}")
    print(f"codex_home:  {CODEX_HOME}")
    print(f"output_dir:  {OUTPUT_DIR}")


def truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return f"{text[:max_chars]}\n\n[... truncated {omitted} characters ...]"


def redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) if m.lastindex else "") + "[REDACTED]", text)
    return SENSITIVE_ASSIGNMENT.sub(r"\1\2[REDACTED]", text)


def clean_text(text: str, *, max_chars: int, do_redact: bool) -> str:
    if do_redact:
        text = redact(text)
    return truncate(text.rstrip(), max_chars)


def content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


def state_db() -> Path:
    candidates = sorted(CODEX_HOME.glob("state_*.sqlite"), reverse=True)
    return candidates[0] if candidates else CODEX_HOME / "state_5.sqlite"


def log_dbs() -> list[Path]:
    return sorted(CODEX_HOME.glob("logs_*.sqlite"))


def list_sessions(limit: int) -> list[dict[str, Any]]:
    db_path = state_db()
    rows: list[dict[str, Any]] = []
    if db_path.exists():
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = [
                dict(row)
                for row in conn.execute(
                    """
                    select id, rollout_path, updated_at, cwd, title, preview, tokens_used
                    from threads
                    order by updated_at desc
                    limit ?
                    """,
                    (limit,),
                ).fetchall()
            ]
    return rows


def print_sessions(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("No indexed Codex sessions found.")
        return
    for idx, row in enumerate(rows, 1):
        updated = iso_from_epoch(row.get("updated_at")) or str(row.get("updated_at", ""))
        title = (row.get("title") or row.get("preview") or "").replace("\n", " ")
        if len(title) > 110:
            title = title[:107] + "..."
        path = Path(row.get("rollout_path") or "")
        size = ""
        if path.exists():
            size = human_size(path.stat().st_size)
        print(f"{idx:>2}. {row.get('id')}  {updated}  {size:>8}  {title}")


def human_size(size: int) -> str:
    units = ["B", "K", "M", "G", "T"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024


def search_sessions(marker: str, *, scan_content: bool, limit: int = 100) -> list[dict[str, Any]]:
    needle = marker.lower()
    db_path = state_db()
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()

    if db_path.exists():
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                select id, rollout_path, updated_at, cwd, title, preview, tokens_used
                from threads
                order by updated_at desc
                """
            ).fetchall()
        for row in rows:
            data = dict(row)
            haystack = "\n".join(
                str(data.get(key) or "")
                for key in ("id", "rollout_path", "cwd", "title", "preview")
            ).lower()
            if needle in haystack:
                data["match"] = "index"
                matches.append(data)
                seen.add(data["id"])

    for path in sorted(CODEX_HOME.glob("sessions/**/rollout-*.jsonl")):
        sid = extract_id_from_path(path) or path.name
        if sid in seen:
            continue
        if needle in str(path).lower():
            matches.append(
                {
                    "id": sid,
                    "rollout_path": str(path),
                    "updated_at": int(path.stat().st_mtime),
                    "title": "(matched rollout path)",
                    "preview": "",
                    "cwd": "",
                    "tokens_used": 0,
                    "match": "path",
                }
            )
            seen.add(sid)

    if scan_content:
        for path in sorted(CODEX_HOME.glob("sessions/**/rollout-*.jsonl")):
            sid = extract_id_from_path(path) or path.name
            if sid in seen:
                continue
            try:
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    for line_no, line in enumerate(handle, 1):
                        if needle in line.lower():
                            matches.append(
                                {
                                    "id": sid,
                                    "rollout_path": str(path),
                                    "updated_at": int(path.stat().st_mtime),
                                    "title": f"(matched content line {line_no})",
                                    "preview": line[:180].strip(),
                                    "cwd": "",
                                    "tokens_used": 0,
                                    "match": "content",
                                }
                            )
                            seen.add(sid)
                            break
            except OSError:
                continue
            if len(matches) >= limit:
                break

    matches.sort(key=lambda row: row.get("updated_at") or 0, reverse=True)
    return matches[:limit]


def pick_from_rows(rows: list[dict[str, Any]], *, action: str = "dump") -> str:
    print_sessions(rows)
    if not rows:
        raise SystemExit("No sessions to pick from.")
    if not sys.stdin.isatty():
        raise SystemExit("Cannot prompt without a TTY. Pass a session id directly.")
    choice = prompt(f"\nEnter number or session id to {action} (q to cancel): ").strip()
    if choice.isdigit():
        idx = int(choice)
        if 1 <= idx <= len(rows):
            return str(rows[idx - 1]["id"])
    return choice


def choose_interactively(*, action: str = "dump") -> str:
    return pick_from_rows(list_sessions(20), action=action)


def sqlite_exec(path: Path, statements: str, params: tuple[Any, ...]) -> int:
    if not path.exists():
        return 0
    try:
        with sqlite3.connect(path) as conn:
            conn.execute("PRAGMA busy_timeout=5000")
            cursor = conn.execute(statements, params)
            changed = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
            conn.commit()
        return changed
    except sqlite3.Error as exc:
        print(f"Warning: could not update {path}: {exc}", file=sys.stderr)
        return 0


def vacuum_db(path: Path) -> None:
    if not path.exists():
        return
    try:
        with sqlite3.connect(path) as conn:
            conn.execute("VACUUM")
    except sqlite3.Error as exc:
        print(f"Warning: could not vacuum {path}: {exc}", file=sys.stderr)


def purge_session(
    *,
    session_id: str,
    rollout_path: Path,
    metadata: dict[str, Any],
    dry_run: bool,
    yes: bool,
) -> None:
    file_size = rollout_path.stat().st_size if rollout_path.exists() else 0
    title = metadata.get("title") or ""
    print("Purge target:")
    print(f"- Session ID: {session_id}")
    print(f"- Rollout file: {rollout_path}")
    print(f"- File size: {human_size(file_size)}")
    if title:
        print(f"- Title: {title}")
    print(f"- State DB: {state_db()}")
    logs = log_dbs()
    if logs:
        print("- Log DBs:")
        for path in logs:
            print(f"  - {path}")

    if dry_run:
        print("\nDry run only. Nothing was deleted.")
        return

    if not yes:
        if not sys.stdin.isatty():
            raise SystemExit("Refusing to purge without a TTY. Re-run with --yes to confirm.")
        answer = prompt("\nType the full session id to purge it, or q to cancel: ").strip()
        if answer != session_id:
            raise SystemExit("Purge cancelled.")

    if rollout_path.exists():
        rollout_path.unlink()
        print(f"Deleted rollout file: {rollout_path}")
    else:
        print("Rollout file was already missing.")

    state_path = state_db()
    deleted_threads = sqlite_exec(state_path, "delete from threads where id = ?", (session_id,))
    sqlite_exec(state_path, "delete from thread_dynamic_tools where thread_id = ?", (session_id,))
    sqlite_exec(
        state_path,
        "delete from thread_spawn_edges where parent_thread_id = ? or child_thread_id = ?",
        (session_id, session_id),
    )
    vacuum_db(state_path)
    print(f"Removed indexed thread rows: {deleted_threads}")

    log_rows = 0
    for log_path in logs:
        log_rows += sqlite_exec(log_path, "delete from logs where thread_id = ?", (session_id,))
        vacuum_db(log_path)
    print(f"Removed log rows: {log_rows}")

    sessions_dir = CODEX_HOME / "sessions"
    if sessions_dir.exists():
        for directory in sorted(sessions_dir.glob("**/*"), reverse=True):
            if directory.is_dir():
                try:
                    directory.rmdir()
                except OSError:
                    pass


def find_session(session: str) -> tuple[str, Path, dict[str, Any]]:
    raw = Path(session).expanduser()
    if raw.exists():
        session_id = extract_id_from_path(raw) or raw.stem
        return session_id, raw, {}

    metadata: dict[str, Any] = {}
    db_path = state_db()
    if db_path.exists():
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "select * from threads where id = ? or id like ? order by updated_at desc",
                (session, f"%{session}%"),
            ).fetchall()
        if len(rows) == 1:
            row = dict(rows[0])
            path = Path(row["rollout_path"]).expanduser()
            if path.exists():
                metadata = row
                return row["id"], path, metadata
        if len(rows) > 1:
            matches = "\n".join(f"  {row['id']}  {row['title']}" for row in rows[:20])
            raise SystemExit(f"Session fragment matched multiple threads:\n{matches}")

    matches = sorted(CODEX_HOME.glob(f"sessions/**/rollout-*{session}*.jsonl"))
    if len(matches) == 1:
        path = matches[0]
        return extract_id_from_path(path) or session, path, metadata
    if len(matches) > 1:
        raise SystemExit("Session fragment matched multiple rollout files:\n" + "\n".join(map(str, matches[:20])))

    raise SystemExit(f"Could not find Codex session: {session}")


def extract_id_from_path(path: Path) -> str | None:
    match = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", path.name)
    return match.group(1) if match else None


def iso_from_epoch(value: Any) -> str:
    try:
        return dt.datetime.fromtimestamp(int(value), tz=dt.timezone.utc).isoformat()
    except Exception:
        return ""


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                yield line_no, json.loads(line), line
            except json.JSONDecodeError as exc:
                yield line_no, {"type": "parse_error", "error": str(exc), "raw": line[:500]}, line


def format_block(text: str) -> str:
    return text.replace("\n```", "\n` ` `")


def write_handoff(
    *,
    session_id: str,
    rollout_path: Path,
    metadata: dict[str, Any],
    output_path: Path,
    include_tools: bool,
    tool_chars: int,
    message_chars: int,
    keep_system: bool,
    do_redact: bool,
    raw_tail: int,
) -> tuple[int, int, int]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    counts = {"messages": 0, "tool_calls": 0, "tool_outputs": 0}
    tail_lines: list[str] = []

    with output_path.open("w", encoding="utf-8") as out:
        out.write("# Codex Session Handoff\n\n")
        out.write("Paste this into a new Codex session to restore the useful context.\n\n")
        out.write("## Session\n\n")
        out.write(f"- Session ID: `{session_id}`\n")
        out.write(f"- Rollout file: `{rollout_path}`\n")
        out.write(f"- File size: `{rollout_path.stat().st_size:,}` bytes\n")
        if metadata:
            title = metadata.get("title") or ""
            cwd = metadata.get("cwd") or ""
            model = metadata.get("model") or ""
            reasoning = metadata.get("reasoning_effort") or ""
            updated = iso_from_epoch(metadata.get("updated_at"))
            out.write(f"- Title: {title}\n")
            out.write(f"- CWD: `{cwd}`\n")
            out.write(f"- Model: `{model}`\n")
            out.write(f"- Reasoning effort: `{reasoning}`\n")
            if updated:
                out.write(f"- Updated: `{updated}`\n")
        out.write("\n## Restart Prompt\n\n")
        out.write(
            "I am continuing from a previous Codex session. Use the handoff below as context. "
            "Preserve the decisions, constraints, commands, paths, and unresolved next steps.\n\n"
        )
        out.write("## Conversation\n\n")

        for line_no, obj, raw in iter_jsonl(rollout_path):
            if raw_tail:
                tail_lines.append(raw)
                if len(tail_lines) > raw_tail:
                    tail_lines.pop(0)

            payload = obj.get("payload") if isinstance(obj, dict) else None
            if not isinstance(payload, dict):
                continue

            if obj.get("type") == "session_meta":
                meta_id = payload.get("id")
                created = payload.get("timestamp")
                cwd = payload.get("cwd")
                cli_version = payload.get("cli_version")
                out.write("### Session Metadata\n\n")
                out.write(f"- Rollout session id: `{meta_id}`\n")
                out.write(f"- Created: `{created}`\n")
                out.write(f"- CWD: `{cwd}`\n")
                out.write(f"- CLI version: `{cli_version}`\n\n")
                continue

            if obj.get("type") != "response_item":
                continue

            item_type = payload.get("type")
            if item_type == "message":
                role = payload.get("role", "unknown")
                if role in {"system", "developer"} and not keep_system:
                    continue
                text = content_to_text(payload.get("content"))
                if not text.strip():
                    continue
                phase = payload.get("phase")
                label = f"{role}"
                if phase:
                    label += f" / {phase}"
                text = clean_text(text, max_chars=message_chars, do_redact=do_redact)
                out.write(f"### {label} (line {line_no})\n\n")
                out.write(format_block(text))
                out.write("\n\n")
                counts["messages"] += 1

            elif item_type == "function_call":
                name = payload.get("name", "tool")
                call_id = payload.get("call_id", "")
                args = payload.get("arguments", "")
                args = clean_text(str(args), max_chars=message_chars, do_redact=do_redact)
                out.write(f"### tool call: {name} (line {line_no})\n\n")
                if call_id:
                    out.write(f"- Call ID: `{call_id}`\n\n")
                out.write("```json\n")
                out.write(format_block(args))
                out.write("\n```\n\n")
                counts["tool_calls"] += 1

            elif item_type == "function_call_output":
                counts["tool_outputs"] += 1
                if not include_tools:
                    continue
                call_id = payload.get("call_id", "")
                text = clean_text(str(payload.get("output", "")), max_chars=tool_chars, do_redact=do_redact)
                out.write(f"### tool output (line {line_no})\n\n")
                if call_id:
                    out.write(f"- Call ID: `{call_id}`\n\n")
                out.write("```text\n")
                out.write(format_block(text))
                out.write("\n```\n\n")

        if raw_tail and tail_lines:
            out.write("## Raw Tail\n\n")
            out.write("```jsonl\n")
            for line in tail_lines:
                out.write(format_block(clean_text(line, max_chars=message_chars, do_redact=do_redact)))
                out.write("\n")
            out.write("```\n")

    return counts["messages"], counts["tool_calls"], counts["tool_outputs"]


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).expanduser() if args.config else CONFIG_PATH
    if args.configure:
        if sys.stdin.isatty():
            config = configure(config_path, force_prompt=True)
        else:
            config = default_config()
            if config_path.exists():
                try:
                    loaded = json.loads(config_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        config.update({k: str(v) for k, v in loaded.items() if k in config})
                except json.JSONDecodeError:
                    pass
            if args.codex_home:
                config["codex_home"] = str(Path(args.codex_home).expanduser())
            if args.output_dir:
                config["output_dir"] = str(Path(args.output_dir).expanduser())
            write_config(config_path, config)
        apply_config(config)
        print_config(config_path)
        return 0

    config_path, config = load_config(args)
    apply_config(config)

    if args.show_config:
        print_config(config_path)
        return 0

    if args.list is not None:
        rows = list_sessions(max(args.list, 1))
        if args.pick or args.purge:
            args.session = pick_from_rows(rows, action="purge" if args.purge else "dump")
        else:
            print_sessions(rows)
            return 0

    if args.search:
        rows = search_sessions(args.search, scan_content=args.scan_content)
        if args.pick or args.purge:
            args.session = pick_from_rows(rows, action="purge" if args.purge else "dump")
        else:
            print_sessions(rows)
            if not rows:
                return 1
            return 0

    if not args.session:
        args.session = choose_interactively(action="purge" if args.purge else "dump")

    session_id, rollout_path, metadata = find_session(args.session)
    output_path = Path(args.output).expanduser() if args.output else OUTPUT_DIR / f"{session_id}-handoff.md"
    if args.purge:
        if args.dump_before_purge:
            messages, tool_calls, tool_outputs = write_handoff(
                session_id=session_id,
                rollout_path=rollout_path,
                metadata=metadata,
                output_path=output_path,
                include_tools=args.include_tools,
                tool_chars=args.tool_chars,
                message_chars=args.message_chars,
                keep_system=args.keep_system,
                do_redact=not args.no_redact,
                raw_tail=args.raw_tail,
            )
            print(f"Wrote handoff before purge: {output_path}")
            print(f"Messages: {messages}")
            print(f"Tool calls: {tool_calls}")
            if args.include_tools:
                print(f"Tool outputs included: {tool_outputs}")
            else:
                print(f"Tool outputs seen but omitted: {tool_outputs}")
            print()
        purge_session(
            session_id=session_id,
            rollout_path=rollout_path,
            metadata=metadata,
            dry_run=args.dry_run,
            yes=args.yes,
        )
        return 0

    messages, tool_calls, tool_outputs = write_handoff(
        session_id=session_id,
        rollout_path=rollout_path,
        metadata=metadata,
        output_path=output_path,
        include_tools=args.include_tools,
        tool_chars=args.tool_chars,
        message_chars=args.message_chars,
        keep_system=args.keep_system,
        do_redact=not args.no_redact,
        raw_tail=args.raw_tail,
    )
    print(f"Wrote: {output_path}")
    print(f"Messages: {messages}")
    print(f"Tool calls: {tool_calls}")
    if args.include_tools:
        print(f"Tool outputs included: {tool_outputs}")
    else:
        print(f"Tool outputs seen but omitted: {tool_outputs}")
    return 0


if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_sigint)
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, UserCancelled):
        print("\nCancelled.", file=sys.stderr)
        raise SystemExit(130)
