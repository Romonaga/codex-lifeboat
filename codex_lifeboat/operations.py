from __future__ import annotations

import datetime as dt
import json
import sqlite3
import tarfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from .config import AppConfig
from .sessions import SessionStore


@dataclass(frozen=True)
class PurgePlan:
    session_id: str
    rollout_path: Path
    db_path: Path
    log_dbs: list[Path]


def archive_session(session_id: str, rollout_path: Path, metadata: dict[str, Any], archive_dir: Path) -> Path:
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_path = archive_dir / f"{session_id}-{stamp}.tar.gz"
    meta = {
        "session_id": session_id,
        "rollout_path": str(rollout_path),
        "archived_at": stamp,
        "metadata": metadata,
    }
    with tarfile.open(archive_path, "w:gz") as tar:
        if rollout_path.exists():
            tar.add(rollout_path, arcname=rollout_path.name)
        info = tarfile.TarInfo("metadata.json")
        body = json.dumps(meta, indent=2).encode("utf-8")
        info.size = len(body)
        tar.addfile(info, fileobj=BytesIO(body))
    return archive_path


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
    except sqlite3.Error:
        return 0


def vacuum_db(path: Path) -> None:
    if not path.exists():
        return
    try:
        with sqlite3.connect(path) as conn:
            conn.execute("VACUUM")
    except sqlite3.Error:
        return


def purge_plan(config: AppConfig, session_id: str, rollout_path: Path) -> PurgePlan:
    store = SessionStore(config)
    return PurgePlan(session_id=session_id, rollout_path=rollout_path, db_path=store.state_db(), log_dbs=store.log_dbs())


def purge_session(config: AppConfig, session_id: str, rollout_path: Path, *, dry_run: bool = True) -> list[str]:
    plan = purge_plan(config, session_id, rollout_path)
    actions = [
        f"session file: {plan.rollout_path}",
        f"state db: {plan.db_path}",
        f"log dbs: {len(plan.log_dbs)}",
    ]
    if dry_run:
        return ["Dry run only. Nothing was deleted.", *actions]

    if plan.rollout_path.exists():
        plan.rollout_path.unlink()
    deleted_threads = sqlite_exec(plan.db_path, "delete from threads where id = ?", (session_id,))
    vacuum_db(plan.db_path)
    log_rows = 0
    for log_path in plan.log_dbs:
        log_rows += sqlite_exec(log_path, "delete from logs where thread_id = ?", (session_id,))
        vacuum_db(log_path)
    sessions_dir = config.codex_home / "sessions"
    if sessions_dir.exists():
        for directory in sorted(sessions_dir.glob("**/*"), reverse=True):
            if directory.is_dir():
                try:
                    directory.rmdir()
                except OSError:
                    pass
    return [*actions, f"removed indexed thread rows: {deleted_threads}", f"removed log rows: {log_rows}"]
