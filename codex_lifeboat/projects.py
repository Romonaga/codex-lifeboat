from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .health import SessionHealth
from .intelligence import project_key, project_label


@dataclass(frozen=True)
class ProjectSummary:
    key: str
    label: str
    sessions: int
    pinned: int
    noted: int
    ready: int
    recoverable: int
    risky: int
    broken: int
    missing_handoffs: int
    archived: int
    total_size: int
    largest_size: int
    latest_updated_at: int
    best_session_id: str
    best_title: str


@dataclass(frozen=True)
class TimelineEntry:
    session_id: str
    title: str
    updated_at: int
    readiness: str
    health: str
    health_score: int
    artifacts: str
    size: int
    note: str


def summarize_projects(
    rows: list[dict[str, Any]],
    *,
    state_for: Any,
    health_for: Any,
    is_pinned: Any,
    note_for: Any,
) -> list[ProjectSummary]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(project_key(row), []).append(row)

    summaries: list[ProjectSummary] = []
    for key, project_rows in buckets.items():
        total_size = 0
        largest_size = 0
        latest = 0
        best_row: dict[str, Any] | None = None
        best_health: SessionHealth | None = None
        counts = {"Ready": 0, "Recoverable": 0, "Risky": 0, "Broken": 0}
        missing_handoffs = 0
        archived = 0
        pinned = 0
        noted = 0
        for row in project_rows:
            state = state_for(row)
            health = health_for(row)
            label = health.label if health.label in counts else "Risky"
            counts[label] += 1
            total_size += state.size
            largest_size = max(largest_size, state.size)
            latest = max(latest, int(row.get("updated_at") or 0))
            if not state.artifacts.has_handoff:
                missing_handoffs += 1
            if state.artifacts.has_archive:
                archived += 1
            if is_pinned(row):
                pinned += 1
            if note_for(row):
                noted += 1
            if not best_health or health.score > best_health.score or (
                health.score == best_health.score and int(row.get("updated_at") or 0) > int(best_row.get("updated_at") or 0)
            ):
                best_row = row
                best_health = health
        best_session_id = str(best_row.get("id") or "") if best_row else ""
        best_title = str(best_row.get("title") or best_row.get("preview") or "") if best_row else ""
        summaries.append(
            ProjectSummary(
                key=key,
                label=project_label(project_rows[0], max_chars=48),
                sessions=len(project_rows),
                pinned=pinned,
                noted=noted,
                ready=counts["Ready"],
                recoverable=counts["Recoverable"],
                risky=counts["Risky"],
                broken=counts["Broken"],
                missing_handoffs=missing_handoffs,
                archived=archived,
                total_size=total_size,
                largest_size=largest_size,
                latest_updated_at=latest,
                best_session_id=best_session_id,
                best_title=best_title,
            )
        )
    return sorted(summaries, key=lambda item: (item.broken, item.risky, item.sessions, item.latest_updated_at), reverse=True)


def timeline_for_project(
    rows: list[dict[str, Any]],
    selected_row: dict[str, Any],
    *,
    state_for: Any,
    health_for: Any,
    note_for: Any,
) -> list[TimelineEntry]:
    selected_project = project_key(selected_row)
    entries: list[TimelineEntry] = []
    for row in rows:
        if project_key(row) != selected_project:
            continue
        state = state_for(row)
        health = health_for(row)
        note = note_for(row)
        title = str(row.get("title") or row.get("preview") or "Untitled").replace("\n", " ")
        entries.append(
            TimelineEntry(
                session_id=str(row.get("id") or ""),
                title=title,
                updated_at=int(row.get("updated_at") or 0),
                readiness=state.readiness.label,
                health=health.label,
                health_score=health.score,
                artifacts=state.artifacts.label(),
                size=state.size,
                note=note.text if note else "",
            )
        )
    return sorted(entries, key=lambda item: item.updated_at)
