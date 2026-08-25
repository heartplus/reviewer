from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from github_reviewer.config.schema import AppConfig
from github_reviewer.errors import ConfigurationError

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::([^}]*))?\}")


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise ConfigurationError("CONFIG_NOT_FOUND", f"Configuration file does not exist: {config_path}")
    try:
        _load_nearby_env_file(config_path)
        with config_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        expanded = _expand_env(raw)
        return AppConfig.model_validate(_resolve_instruction_paths(expanded, config_path.parent))
    except yaml.YAMLError as exc:
        raise ConfigurationError("INVALID_YAML", f"Cannot parse configuration: {config_path}") from exc
    except ValidationError as exc:
        raise ConfigurationError("INVALID_CONFIG", str(exc)) from exc


def _load_nearby_env_file(config_path: Path) -> None:
    """Load a project-local .env without overwriting deployment environment variables."""
    candidates = (config_path.parent / ".env", config_path.parent.parent / ".env")
    env_path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if env_path is None:
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", key):
            continue
        os.environ.setdefault(key, value.strip().strip("\"'"))


def _expand_env(value: Any, path: str = "config") -> Any:
    if isinstance(value, dict):
        return {key: _expand_env(item, f"{path}.{key}") for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            variable, default = match.group(1), match.group(2)
            resolved = os.getenv(variable, default)
            if resolved is None:
                raise ConfigurationError("MISSING_ENV", f"Missing environment variable '{variable}' for {path}")
            return resolved

        return _ENV_PATTERN.sub(replace, value)
    return value


def _resolve_instruction_paths(raw: Any, config_dir: Path) -> Any:
    """Resolve per-agent instruction paths relative to the YAML file."""
    if not isinstance(raw, dict):
        return raw

    resolved = dict(raw)
    for section in ("agents", "specialists"):
        entries = resolved.get(section)
        if not isinstance(entries, dict):
            continue
        copied_entries = dict(entries)
        for role, settings in entries.items():
            if not isinstance(settings, dict) or not isinstance(settings.get("instruction"), str):
                continue
            copied_settings = dict(settings)
            instruction = Path(copied_settings["instruction"]).expanduser()
            if not instruction.is_absolute():
                instruction = config_dir / instruction
            copied_settings["instruction"] = instruction.resolve()
            copied_entries[role] = copied_settings
        resolved[section] = copied_entries
    return resolved
