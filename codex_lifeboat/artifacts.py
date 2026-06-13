from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig


@dataclass(frozen=True)
class ArtifactHistory:
    handoffs: list[Path]
    summaries: list[Path]
    archives: list[Path]
    resume_packages: list[Path]

    @property
    def has_handoff(self) -> bool:
        return bool(self.handoffs)

    @property
    def has_summary(self) -> bool:
        return bool(self.summaries)

    @property
    def has_archive(self) -> bool:
        return bool(self.archives)

    @property
    def latest(self) -> Path | None:
        paths = [*self.handoffs, *self.summaries, *self.archives, *self.resume_packages]
        existing = [path for path in paths if path.exists()]
        if not existing:
            return None
        return max(existing, key=lambda path: path.stat().st_mtime)

    def label(self) -> str:
        parts: list[str] = []
        if self.handoffs:
            parts.append(f"H{len(self.handoffs)}")
        if self.summaries:
            parts.append(f"S{len(self.summaries)}")
        if self.archives:
            parts.append(f"A{len(self.archives)}")
        if self.resume_packages:
            parts.append(f"R{len(self.resume_packages)}")
        return " ".join(parts) if parts else "-"


def artifact_prefix(session_id: str, agent_key: str) -> str:
    return session_id if agent_key == "codex" else f"{agent_key}-{session_id}"


def artifact_history(config: AppConfig, session_id: str, agent_key: str) -> ArtifactHistory:
    prefix = artifact_prefix(session_id, agent_key)
    output_dir = config.output_dir
    archives_dir = output_dir / "archives"
    packages_dir = output_dir / "resume-packages"
    handoffs = sorted(output_dir.glob(f"{prefix}-handoff*.md"))
    summaries = sorted(output_dir.glob(f"{prefix}-summary*.md"))
    archives = sorted(archives_dir.glob(f"{session_id}-*.tar.gz"))
    agent_archives = sorted(archives_dir.glob(f"{prefix}-*.tar.gz"))
    resume_packages = sorted(packages_dir.glob(f"{prefix}-resume-*.tar.gz"))
    return ArtifactHistory(
        handoffs=handoffs,
        summaries=summaries,
        archives=sorted(set([*archives, *agent_archives])),
        resume_packages=resume_packages,
    )
