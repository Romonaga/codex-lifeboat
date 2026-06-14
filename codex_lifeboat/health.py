from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .artifacts import ArtifactHistory
from .intelligence import RecoveryReadiness
from .text import human_size


@dataclass(frozen=True)
class SessionHealth:
    label: str
    score: int
    reasons: tuple[str, ...]
    next_actions: tuple[str, ...]


def session_health(
    *,
    row: dict[str, Any],
    readiness: RecoveryReadiness,
    artifacts: ArtifactHistory,
    size: int,
    has_session_file: bool,
    backup_count: int,
    pinned: bool,
    has_note: bool,
) -> SessionHealth:
    reasons: list[str] = []
    actions: list[str] = []

    if not has_session_file:
        return SessionHealth(
            label="Broken",
            score=10,
            reasons=("session file is missing", *readiness.reasons),
            next_actions=("restore a backup or recover the session JSONL before handoff",),
        )

    score = 35
    if artifacts.has_handoff:
        score += 20
        reasons.append("handoff exists")
    else:
        actions.append("write a full handoff")
    if artifacts.has_summary:
        score += 10
        reasons.append("compact summary exists")
    else:
        actions.append("write a compact summary")
    if artifacts.has_archive:
        score += 20
        reasons.append("archive exists")
    else:
        actions.append("archive the session file")
    if artifacts.resume_packages:
        score += 5
        reasons.append("resume package exists")
    if backup_count:
        score += 5
        reasons.append(f"{backup_count} injection/restore backup{'s' if backup_count != 1 else ''} available")
    if pinned:
        score += 3
        reasons.append("session is pinned")
    if has_note:
        score += 2
        reasons.append("session note exists")

    tokens = int(row.get("tokens_used") or 0)
    if size >= 500 * 1024 * 1024:
        score -= 25
        reasons.append(f"huge transcript ({human_size(size)})")
        actions.append("prefer handoff/summary over direct resume")
    elif size >= 100 * 1024 * 1024:
        score -= 15
        reasons.append(f"very large transcript ({human_size(size)})")
        actions.append("consider make-safe before continued work")
    elif size >= 25 * 1024 * 1024:
        score -= 5
        reasons.append(f"large transcript ({human_size(size)})")
    if tokens >= 1_000_000:
        score -= 8
        reasons.append(f"high token counter ({tokens:,})")

    score = max(0, min(100, score))
    if score >= 85:
        label = "Ready"
    elif score >= 65:
        label = "Recoverable"
    elif score >= 35:
        label = "Risky"
    else:
        label = "Broken"

    if not actions and label != "Ready":
        actions.append("review health details before purge or injection")
    if not actions:
        actions.append("safe to resume, export, or purge when intended")
    if not reasons:
        reasons.append("session file is readable")

    return SessionHealth(label=label, score=score, reasons=tuple(reasons), next_actions=tuple(actions))
