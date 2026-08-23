from __future__ import annotations

import os
from typing import Any

from openai import AsyncOpenAI

from github_reviewer.config.schema import ModelConfig, ModelSettingsConfig, ProviderKind


def build_model(model_config: ModelConfig) -> Any:
    """Build an Agents SDK model reference from configuration."""
    if model_config.provider == ProviderKind.OPENAI:
        return model_config.name

    if model_config.provider == ProviderKind.OPENAI_COMPATIBLE:
        from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel

        client = AsyncOpenAI(
            api_key=_api_key(model_config),
            base_url=model_config.base_url,
        )
        return OpenAIChatCompletionsModel(
            model=model_config.name,
            openai_client=client,
        )

    if model_config.provider == ProviderKind.LITELLM:
        from agents.extensions.models.litellm_model import LitellmModel

        return LitellmModel(
            model=model_config.name,
            base_url=model_config.base_url,
            api_key=_api_key(model_config, required=False),
        )

    raise ValueError(f"Unsupported provider: {model_config.provider}")


def build_model_settings(settings_config: ModelSettingsConfig) -> Any:
    from agents import ModelSettings

    payload: dict[str, Any] = {}
    if settings_config.temperature is not None:
        payload["temperature"] = settings_config.temperature
    if settings_config.top_p is not None:
        payload["top_p"] = settings_config.top_p
    if settings_config.max_tokens is not None:
        payload["max_tokens"] = settings_config.max_tokens
    if settings_config.parallel_tool_calls is not None:
        payload["parallel_tool_calls"] = settings_config.parallel_tool_calls
    if settings_config.extra_args:
        payload["extra_args"] = settings_config.extra_args
    if settings_config.extra_body:
        payload["extra_body"] = settings_config.extra_body
    if settings_config.reasoning_effort:
        from openai.types.shared import Reasoning

        payload["reasoning"] = Reasoning(effort=settings_config.reasoning_effort)
    return ModelSettings(**payload)


def _api_key(model_config: ModelConfig, *, required: bool = True) -> str | None:
    if model_config.api_key_env is None:
        return None
    value = os.getenv(model_config.api_key_env)
    if required and not value:
        raise RuntimeError(f"Missing API key environment variable: {model_config.api_key_env}")
    return value
