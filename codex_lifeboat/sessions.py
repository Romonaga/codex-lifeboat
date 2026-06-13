from __future__ import annotations

import datetime as dt
import sqlite3
import re
from pathlib import Path
from typing import Any

from .config import AppConfig


def extract_id_from_path(path: Path) -> str | None:
    match = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", path.name)
    return match.group(1) if match else None


def iso_from_epoch(value: Any) -> str:
    try:
        return dt.datetime.fromtimestamp(int(value), tz=dt.timezone.utc).isoformat()
    except Exception:
        return ""


class SessionStore:
    key = "codex"
    display_name = "Codex"
    home_label = "Codex home"
    session_file_label = "Session file"

    def __init__(self, config: AppConfig):
        self.config = config

    def state_db(self) -> Path:
        candidates = sorted(self.config.codex_home.glob("state_*.sqlite"), reverse=True)
        return candidates[0] if candidates else self.config.codex_home / "state_5.sqlite"

    def log_dbs(self) -> list[Path]:
        return sorted(self.config.codex_home.glob("logs_*.sqlite"))

    def rollout_files(self) -> list[Path]:
        return sorted(self.config.codex_home.glob("sessions/**/rollout-*.jsonl"))

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        db_path = self.state_db()
        if not db_path.exists():
            return []
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [
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

    def all(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        db_path = self.state_db()
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
                        """
                    ).fetchall()
                ]
            for row in rows:
                seen.add(str(row.get("id")))

        for path in self.rollout_files():
            sid = extract_id_from_path(path) or path.name
            if sid in seen:
                continue
            rows.append(
                {
                    "id": sid,
                    "rollout_path": str(path),
                    "updated_at": int(path.stat().st_mtime),
                    "cwd": "",
                    "title": "(orphan session file)",
                    "preview": "",
                    "tokens_used": 0,
                    "orphan": True,
                }
            )
        rows.sort(key=lambda row: row.get("updated_at") or 0, reverse=True)
        return rows

    def size(self, row: dict[str, Any]) -> int:
        path = self.session_file_path(row)
        return path.stat().st_size if path and path.is_file() else 0

    def session_file_path(self, row: dict[str, Any]) -> Path | None:
        raw = str(row.get("rollout_path") or "").strip()
        return Path(raw).expanduser() if raw else None

    def has_session_file(self, row: dict[str, Any]) -> bool:
        path = self.session_file_path(row)
        return bool(path and path.is_file())

    def file_status(self, row: dict[str, Any]) -> str:
        path = self.session_file_path(row)
        if row.get("orphan"):
            return "Orphan"
        if path and path.is_file():
            return "Available"
        if path:
            return "Missing"
        return "Unknown"

    def total_rollout_size(self) -> int:
        total = 0
        for path in self.rollout_files():
            try:
                total += path.stat().st_size
            except OSError:
                pass
        return total

    def total_session_file_size(self) -> int:
        return self.total_rollout_size()

    def search(self, marker: str, *, scan_content: bool = False, limit: int = 100) -> list[dict[str, Any]]:
        needle = marker.lower()
        matches: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in self.all():
            haystack = "\n".join(str(row.get(key) or "") for key in ("id", "title", "preview", "cwd", "rollout_path")).lower()
            if needle in haystack:
                matches.append(row)
                seen.add(str(row.get("id")))
            if len(matches) >= limit:
                return matches[:limit]

        if scan_content:
            for path in self.rollout_files():
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
                                break
                except OSError:
                    continue
                if len(matches) >= limit:
                    break
        matches.sort(key=lambda row: row.get("updated_at") or 0, reverse=True)
        return matches[:limit]

    def find(self, session: str) -> tuple[str, Path, dict[str, Any]]:
        raw = Path(session).expanduser()
        if raw.exists():
            session_id = extract_id_from_path(raw) or raw.stem
            return session_id, raw, {}

        db_path = self.state_db()
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
                    return row["id"], path, row
            if len(rows) > 1:
                matches = "\n".join(f"  {row['id']}  {row['title']}" for row in rows[:20])
                raise SystemExit(f"Session fragment matched multiple threads:\n{matches}")

        matches = sorted(self.config.codex_home.glob(f"sessions/**/rollout-*{session}*.jsonl"))
        if len(matches) == 1:
            path = matches[0]
            return extract_id_from_path(path) or session, path, {}
        if len(matches) > 1:
            raise SystemExit("Session fragment matched multiple session files:\n" + "\n".join(map(str, matches[:20])))
        raise SystemExit(f"Could not find Codex session: {session}")
