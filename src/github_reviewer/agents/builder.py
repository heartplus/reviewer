from __future__ import annotations

from dataclasses import dataclass, field

from agents import Agent, function_tool

from github_reviewer.agents.model_factory import build_model, build_model_settings
from github_reviewer.config.schema import AppConfig, SpecialistAgentConfig
from github_reviewer.instructions import default_instruction_path, load_instruction
from github_reviewer.review.models import ReviewerResult, SummaryResult, VerifierResult
from github_reviewer.tools.repo import RepositoryTools


@dataclass(frozen=True)
class ReviewAgents:
    reviewer: Agent
    verifier: Agent
    summarizer: Agent
    specialists: dict[str, Agent] = field(default_factory=dict)


def build_review_agents(config: AppConfig, repo_tools: RepositoryTools) -> ReviewAgents:
    tools = _build_repo_tools(config, repo_tools)
    reviewer = _agent(
        config,
        "reviewer",
        "Code Reviewer",
        _instructions_for_role(config, "reviewer"),
        _tools_for_role(config, "reviewer", tools),
        ReviewerResult,
    )
    verifier = _agent(
        config,
        "verifier",
        "Finding Verifier",
        _instructions_for_role(config, "verifier"),
        _tools_for_role(config, "verifier", tools),
        VerifierResult,
    )
    summarizer = _agent(
        config,
        "summarizer",
        "Review Summarizer",
        _instructions_for_role(config, "summarizer"),
        [],
        SummaryResult,
    )
    specialists = {
        name: _agent(
            config,
            name,
            f"{name.replace('_', ' ').title()} Reviewer",
            _instructions_for_role(config, name, settings),
            _tools_for_role(config, name, tools),
            ReviewerResult,
        )
        for name, settings in config.specialists.items()
        if settings.enabled
    }
    return ReviewAgents(reviewer=reviewer, verifier=verifier, summarizer=summarizer, specialists=specialists)


def _instructions_for_role(
    config: AppConfig,
    role: str,
    settings: SpecialistAgentConfig | None = None,
) -> str:
    agent_config = settings or config.agents[role]
    return load_instruction(
        agent_config.instruction or default_instruction_path(role),
        specialist_name=role if settings is not None else None,
    )


def _tools_for_role(config: AppConfig, role: str, tools):
    agent_config = config.agents.get(role) or config.specialists.get(role)
    return tools if agent_config and agent_config.use_repo_tools else []


def _agent(config: AppConfig, role: str, name: str, instructions: str, tools, output_type):
    model_config = config.model_for_agent(role)
    if not tools:
        instructions = f"{instructions}\n\n{load_instruction(default_instruction_path('no_repo_tools'))}"
    return Agent(
        name=name,
        instructions=instructions,
        model=build_model(model_config),
        model_settings=build_model_settings(model_config.settings),
        tools=tools,
        output_type=output_type if model_config.supports_structured_output else None,
    )


def _build_repo_tools(config: AppConfig, repo_tools: RepositoryTools):
    @function_tool
    def get_diff(base_ref: str, head_ref: str = "HEAD", context_lines: int = 8) -> str:
        """Return a bounded unified Git diff for base_ref...head_ref."""
        return repo_tools.get_diff(base_ref, head_ref, context_lines=context_lines)

    @function_tool
    def changed_files(base_ref: str, head_ref: str = "HEAD") -> list[dict[str, str]]:
        """Return bounded changed-file status and repository-relative paths."""
        return repo_tools.changed_files(base_ref, head_ref)

    @function_tool
    def read_file(path: str, start: int = 1, end: int | None = None) -> str:
        """Read a bounded line range from a repository file."""
        return repo_tools.read_file(path, start=start, end=end)

    @function_tool
    def grep(pattern: str, path_glob: str | None = None, max_matches: int = 80) -> str:
        """Search repository text with ripgrep and return matching lines."""
        return repo_tools.grep(pattern, path_glob=path_glob, max_matches=max_matches)

    @function_tool
    def git_blame(path: str, start: int, end: int) -> str:
        """Return Git blame information for a bounded range in a repository file."""
        return repo_tools.git_blame(path, start=start, end=end)

    repo_function_tools = [get_diff, changed_files, read_file, grep, git_blame]
    if config.review.allow_test_commands:
        @function_tool
        def run_tests(command: str, timeout_seconds: int = 120) -> dict[str, object]:
            """Run one configured allowlisted test command and return its bounded result."""
            return repo_tools.run_tests(command, timeout_seconds=timeout_seconds)

        repo_function_tools.append(run_tests)
    return repo_function_tools
