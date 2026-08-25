from __future__ import annotations

from pathlib import Path

import pytest

from github_reviewer.config import load_config
from github_reviewer.errors import ConfigurationError
from github_reviewer.instructions import load_instruction


def test_load_default_config() -> None:
    config = load_config(Path("config/default.yaml"))

    assert config.model_for_agent("reviewer").name == "deepseek-v4-pro"
    assert config.model_for_agent("verifier").provider == "openai_compatible"
    assert config.model_for_agent("summarizer").base_url == "https://api.deepseek.com"
    assert not config.agents["reviewer"].use_repo_tools
    assert config.agents["reviewer"].instruction == (Path("instructions/reviewer.md").resolve())
    assert config.review.max_diff_bytes > 0


def test_instruction_path_is_resolved_relative_to_config_file(tmp_path: Path) -> None:
    instruction_dir = tmp_path / "prompts"
    instruction_dir.mkdir()
    instruction_path = instruction_dir / "reviewer.md"
    instruction_path.write_text("请审查变更。", encoding="utf-8")
    config_path = tmp_path / "reviewer.yaml"
    config_path.write_text(
        """
agents:
  reviewer: {model: test, instruction: prompts/reviewer.md}
  verifier: {model: test}
  summarizer: {model: test}
models:
  test: {name: test-model}
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.agents["reviewer"].instruction == instruction_path.resolve()


def test_instruction_loader_replaces_specialist_name(tmp_path: Path) -> None:
    path = tmp_path / "specialist.md"
    path.write_text("你是 {{specialist_name}} 专项审查员。", encoding="utf-8")

    assert load_instruction(path, specialist_name="security") == "你是 security 专项审查员。"


def test_instruction_loader_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="INSTRUCTION_NOT_FOUND"):
        load_instruction(tmp_path / "missing.md")
