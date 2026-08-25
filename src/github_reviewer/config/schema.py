from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderKind(StrEnum):
    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai_compatible"
    LITELLM = "litellm"


class ReviewSource(StrEnum):
    LOCAL = "local"
    GITHUB = "github"


class ModelSettingsConfig(StrictModel):
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    max_tokens: int | None = Field(default=None, gt=0)
    reasoning_effort: str | None = None
    parallel_tool_calls: bool | None = None
    extra_args: dict[str, Any] = Field(default_factory=dict)
    extra_body: dict[str, Any] = Field(default_factory=dict)

    @field_validator("reasoning_effort")
    @classmethod
    def validate_reasoning_effort(cls, value: str | None) -> str | None:
        if value is not None and value not in {"none", "low", "medium", "high", "xhigh"}:
            raise ValueError("reasoning_effort must be none, low, medium, high, or xhigh")
        return value


class ModelConfig(StrictModel):
    provider: ProviderKind = ProviderKind.OPENAI
    name: str = Field(min_length=1)
    base_url: str | None = None
    api_key_env: str | None = None
    supports_structured_output: bool = True
    settings: ModelSettingsConfig = Field(default_factory=ModelSettingsConfig)

    @model_validator(mode="after")
    def validate_provider_settings(self) -> "ModelConfig":
        if self.provider == ProviderKind.OPENAI_COMPATIBLE and not self.base_url:
            raise ValueError("openai_compatible provider requires base_url")
        if self.base_url and not self.base_url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            raise ValueError("base_url must use HTTPS, except for localhost development endpoints")
        return self


class AgentConfig(StrictModel):
    model: str = Field(min_length=1)
    use_repo_tools: bool = True
    instruction: Path | None = None


class SpecialistAgentConfig(AgentConfig):
    enabled: bool = True
    paths: list[str] = Field(default_factory=list)
    severities: list[str] = Field(default_factory=lambda: ["critical", "high", "medium"])
    max_context_bytes: int | None = Field(default=None, gt=0)


class ReviewConfig(StrictModel):
    base_ref: str = "origin/main"
    head_ref: str = "HEAD"
    max_diff_bytes: int = 200_000
    max_file_bytes: int = 60_000
    max_test_output_bytes: int = 30_000
    max_changed_files: int = 500
    max_grep_matches: int = 80
    max_findings: int = 30
    max_context_lines: int = 20
    max_agent_turns: int = 6
    allow_test_commands: bool = False
    test_command_allowlist: list[str] = Field(default_factory=list)
    provider_retry_max_attempts: int = Field(default=3, ge=1, le=10)
    provider_retry_base_delay_seconds: float = Field(default=0.5, gt=0, le=60)
    provider_retry_max_delay_seconds: float = Field(default=8.0, gt=0, le=300)

    @field_validator(
        "max_diff_bytes",
        "max_file_bytes",
        "max_test_output_bytes",
        "max_changed_files",
        "max_grep_matches",
        "max_findings",
        "max_context_lines",
        "max_agent_turns",
    )
    @classmethod
    def positive_limit(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("resource limits must be positive")
        return value

    @model_validator(mode="after")
    def validate_retry_delays(self) -> "ReviewConfig":
        if self.provider_retry_max_delay_seconds < self.provider_retry_base_delay_seconds:
            raise ValueError("provider_retry_max_delay_seconds must be at least provider_retry_base_delay_seconds")
        return self


class PersistenceConfig(StrictModel):
    enabled: bool = False
    sqlite_path: Path = Path(".github-reviewer/reviews.sqlite3")
    config_version: str = "v1"


class GitHubConfig(StrictModel):
    enabled: bool = False
    webhook_secret_env: str | None = None
    api_url: str = "https://api.github.com"
    token_env: str | None = None


class ObservabilityConfig(StrictModel):
    enable_agent_tracing: bool = True


class AppConfig(StrictModel):
    review: ReviewConfig = Field(default_factory=ReviewConfig)
    agents: dict[str, AgentConfig]
    models: dict[str, ModelConfig]
    specialists: dict[str, SpecialistAgentConfig] = Field(default_factory=dict)
    persistence: PersistenceConfig = Field(default_factory=PersistenceConfig)
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)

    @model_validator(mode="after")
    def validate_agent_model_references(self) -> "AppConfig":
        for required_role in ("reviewer", "verifier", "summarizer"):
            if required_role not in self.agents:
                raise ValueError(f"agents.{required_role} is required")
        for role, agent in {**self.agents, **self.specialists}.items():
            if agent.model not in self.models:
                raise ValueError(f"agent '{role}' references undefined model '{agent.model}'")
        return self

    def model_for_agent(self, agent_name: str) -> ModelConfig:
        agent = self.agents.get(agent_name) or self.specialists.get(agent_name)
        if agent is None:
            raise KeyError(f"Unknown agent role: {agent_name}")
        return self.models[agent.model]


class RuntimeReviewRequest(StrictModel):
    repo: Path
    base: str = "origin/main"
    head: str = "HEAD"
    source: ReviewSource = ReviewSource.LOCAL
    pull_request_number: int | None = Field(default=None, gt=0)
    commit_sha: str | None = None
