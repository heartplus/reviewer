from __future__ import annotations

from pathlib import Path

from github_reviewer.config import load_config


def test_load_default_config() -> None:
    config = load_config(Path("config/default.yaml"))

    assert config.model_for_agent("reviewer").name == "deepseek-v4-pro"
    assert config.model_for_agent("verifier").provider == "openai_compatible"
    assert config.model_for_agent("summarizer").base_url == "https://api.deepseek.com"
    assert not config.agents["reviewer"].use_repo_tools
    assert config.review.max_diff_bytes > 0
