from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "agent-lifeboat"


@dataclass(frozen=True)
class AppConfig:
    codex_home: Path
    claude_home: Path
    output_dir: Path
    config_path: Path

    @property
    def config_dir(self) -> Path:
        return self.config_path.parent


def default_config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    explicit = os.environ.get("AGENT_LIFEBOAT_CONFIG")
    if explicit:
        return Path(explicit).expanduser()
    return (base / APP_NAME / "config.json").expanduser()


def output_dir_env() -> str | None:
    return os.environ.get("AGENT_LIFEBOAT_OUTPUT_DIR")


def default_values() -> dict[str, str]:
    return {
        "codex_home": str(Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()),
        "claude_home": str(Path(os.environ.get("CLAUDE_HOME", Path.home() / ".claude")).expanduser()),
        "output_dir": str(Path(output_dir_env() or Path.cwd() / "agent-lifeboat-dumps").expanduser()),
    }


def read_config_file(config_path: Path) -> dict[str, str]:
    if not config_path.exists():
        return {}
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Config file is invalid JSON: {config_path}: {exc}") from exc
    if not isinstance(loaded, dict):
        return {}
    defaults = default_values()
    return {key: str(value) for key, value in loaded.items() if key in defaults}


def save_config(config: AppConfig) -> None:
    config.config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "codex_home": str(config.codex_home),
        "claude_home": str(config.claude_home),
        "output_dir": str(config.output_dir),
    }
    config.config_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_config(
    *,
    config_path: Path | None = None,
    codex_home: str | Path | None = None,
    claude_home: str | Path | None = None,
    output_dir: str | Path | None = None,
    create: bool = True,
) -> AppConfig:
    path = (config_path or default_config_path()).expanduser()
    values = default_values()
    values.update(read_config_file(path))
    if codex_home:
        values["codex_home"] = str(Path(codex_home).expanduser())
    if claude_home:
        values["claude_home"] = str(Path(claude_home).expanduser())
    if output_dir:
        values["output_dir"] = str(Path(output_dir).expanduser())
    config = AppConfig(
        codex_home=Path(values["codex_home"]).expanduser(),
        claude_home=Path(values["claude_home"]).expanduser(),
        output_dir=Path(values["output_dir"]).expanduser(),
        config_path=path,
    )
    if create and not path.exists():
        save_config(config)
    return config
