from __future__ import annotations

from typing import Any

from .config import AppConfig
from .pins import PinStore
from .agents import SessionBackend
from .sessions import SessionStore
from .text import human_size

HUGE_SESSION_BYTES = 500 * 1024 * 1024
IMPOSSIBLE_TOKEN_COUNT = 100_000_000


def set_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result = []
    for row in rows:
        sid = str(row.get("id") or row.get("rollout_path") or "")
        if sid in seen:
            continue
        seen.add(sid)
        result.append(row)
    return result


def risk_reasons(store: SessionBackend, row: dict[str, Any]) -> list[str]:
    reasons = []
    if store.size(row) >= HUGE_SESSION_BYTES:
        reasons.append(f"session file >= {human_size(HUGE_SESSION_BYTES)}")
    if int(row.get("tokens_used") or 0) > IMPOSSIBLE_TOKEN_COUNT:
        reasons.append(f"tokens > {IMPOSSIBLE_TOKEN_COUNT:,}")
    return reasons


def report(config: AppConfig, store: SessionBackend | None = None, pins: PinStore | None = None, *, agent_key: str = "codex") -> str:
    store = store or SessionStore(config)
    pins = pins or PinStore(config)
    rows = store.all()
    pinned = pins.load()
    agent_pins = {pin for pin in pinned if pin.startswith(f"{agent_key}:")}
    missing = [row for row in rows if store.file_status(row) == "Missing"]
    orphan = [row for row in rows if row.get("orphan")]
    impossible = [row for row in rows if int(row.get("tokens_used") or 0) > IMPOSSIBLE_TOKEN_COUNT]
    huge = [row for row in rows if store.size(row) >= HUGE_SESSION_BYTES]
    largest = sorted(rows, key=store.size, reverse=True)[:10]
    log_size = sum(path.stat().st_size for path in store.log_dbs() if path.exists())

    lines = [
        f"# {store.display_name} Lifeboat Doctor Report",
        "",
        f"- Agent: `{store.display_name}`",
        f"- {store.home_label}: `{config.codex_home if agent_key == 'codex' else config.claude_home}`",
        f"- Output dir: `{config.output_dir}`",
        f"- Indexed/visible sessions: `{len(rows)}`",
        f"- Pinned sessions: `{len(agent_pins)}`",
        f"- Session file storage: `{human_size(store.total_session_file_size())}`",
        f"- Log DB storage: `{human_size(log_size)}`",
        f"- Huge sessions >= {human_size(HUGE_SESSION_BYTES)}: `{len(huge)}`",
        f"- Impossible token counters > {IMPOSSIBLE_TOKEN_COUNT:,}: `{len(impossible)}`",
        f"- Missing session files: `{len(missing)}`",
        f"- Orphan session files: `{len(orphan)}`",
        "",
    ]

    def table(title: str, items: list[dict[str, Any]], include_reason: bool = False) -> None:
        lines.append(f"## {title}")
        lines.append("")
        if not items:
            lines.append("None.")
            lines.append("")
            return
        if include_reason:
            lines.append("| Size | Tokens | Pinned | Reason | Session | Title |")
            lines.append("| ---: | ---: | :---: | --- | --- | --- |")
        else:
            lines.append("| Size | Tokens | Pinned | Session | Title |")
            lines.append("| ---: | ---: | :---: | --- | --- |")
        for row in items:
            sid = str(row.get("id") or "")
            title_text = (row.get("title") or row.get("preview") or "").replace("|", "\\|").replace("\n", " ")
            if len(title_text) > 90:
                title_text = title_text[:87] + "..."
            prefix = f"| {human_size(store.size(row))} | {int(row.get('tokens_used') or 0)} | {'yes' if f'{agent_key}:{sid}' in pinned else ''} |"
            if include_reason:
                reason = ", ".join(risk_reasons(store, row)) or "unknown"
                lines.append(f"{prefix} {reason} | `{sid}` | {title_text} |")
            else:
                lines.append(f"{prefix} `{sid}` | {title_text} |")
        lines.append("")

    table("Largest Sessions", largest)
    table("Likely Risky Sessions", sorted(set_rows(huge + impossible), key=store.size, reverse=True), include_reason=True)
    table("Missing Session Files", missing)
    table("Orphan Session Files", orphan)
    return "\n".join(lines)
