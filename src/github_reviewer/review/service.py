from __future__ import annotations

from pathlib import Path

from github_reviewer.agents.builder import build_review_agents
from github_reviewer.agents.runner import ReviewRunner
from github_reviewer.config.schema import AppConfig
from github_reviewer.persistence import SQLiteReviewStore
from github_reviewer.tools import RepositoryTools


def create_review_runner(config: AppConfig, repo: str | Path) -> ReviewRunner:
    repo_tools = RepositoryTools(repo, config.review)
    agents = build_review_agents(config, repo_tools)
    store = None
    if config.persistence.enabled:
        store = SQLiteReviewStore(config.persistence.sqlite_path, config.persistence.config_version)
    return ReviewRunner(config, agents, repo_tools, store)
