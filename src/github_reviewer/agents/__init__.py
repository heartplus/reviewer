from __future__ import annotations

from typing import Any

__all__ = ["ReviewReport", "ReviewRunner", "build_review_agents"]


def __getattr__(name: str) -> Any:
    """Avoid importing builder and runner while the agents package initializes."""
    if name == "build_review_agents":
        from github_reviewer.agents.builder import build_review_agents

        return build_review_agents
    if name == "ReviewRunner":
        from github_reviewer.agents.runner import ReviewRunner

        return ReviewRunner
    if name == "ReviewReport":
        from github_reviewer.review.models import ReviewReport

        return ReviewReport
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
