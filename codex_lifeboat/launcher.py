from __future__ import annotations

import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LaunchResult:
    terminal: str
    cwd: Path
    command: list[str]
    terminal_command: list[str]
    warning: str | None = None

    def command_text(self) -> str:
        return shlex.join(self.command)


def resume_command(agent_key: str, session_id: str) -> list[str]:
    if agent_key == "claude":
        return ["claude", "--resume", session_id]
    return ["codex", "resume", session_id]


def resolve_resume_cwd(raw_cwd: object) -> tuple[Path, str | None]:
    home = Path.home()
    cwd_text = str(raw_cwd or "").strip()
    if not cwd_text:
        return home, "No cwd was recorded for this session; opened in your home directory."
    cwd = Path(cwd_text).expanduser()
    if cwd.is_dir():
        return cwd, None
    return home, f"Recorded cwd is not available: {cwd}. Opened in your home directory."


def launch_resume_terminal(agent_key: str, session_id: str, raw_cwd: object) -> tuple[LaunchResult | None, str | None]:
    if not session_id:
        return None, "Selected session has no session id."

    terminal = shutil.which("tilix")
    if not terminal:
        return None, "Tilix was not found on PATH."

    command = resume_command(agent_key, session_id)
    agent_binary = shutil.which(command[0])
    if not agent_binary:
        return None, f"{command[0]} was not found on PATH."

    cwd, warning = resolve_resume_cwd(raw_cwd)
    shell_script = f"{shlex.join(command)}; exec bash"
    terminal_command = [
        terminal,
        "--working-directory",
        str(cwd),
        "-e",
        "bash",
        "-lc",
        shell_script,
    ]

    try:
        subprocess.Popen(
            terminal_command,
            cwd=str(cwd),
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        return None, f"Could not launch Tilix: {exc}"

    return LaunchResult(terminal=terminal, cwd=cwd, command=command, terminal_command=terminal_command, warning=warning), None
