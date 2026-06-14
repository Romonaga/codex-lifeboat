from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig
from .handoff import WriteResult
from .operations import archive_session
from .recovery import RecoveryContext, write_agent_handoff, write_agent_summary


@dataclass(frozen=True)
class SafeBundleResult:
    handoff: WriteResult
    summary: WriteResult
    archive_path: Path


def make_safe_bundle(
    config: AppConfig,
    context: RecoveryContext,
    *,
    scrub_profile: str,
    target_agent: str,
) -> SafeBundleResult:
    handoff = write_agent_handoff(config, context, scrub_profile=scrub_profile, target_agent=target_agent)
    summary = write_agent_summary(config, context, scrub_profile=scrub_profile)
    archive_path = archive_session(
        context.session_id,
        context.session_file_path,
        {"agent": context.agent_key, **context.metadata},
        config.output_dir / "archives",
    )
    return SafeBundleResult(handoff=handoff, summary=summary, archive_path=archive_path)
