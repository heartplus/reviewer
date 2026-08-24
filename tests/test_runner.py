from __future__ import annotations

import subprocess
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import github_reviewer.agents.runner as runner_module
from github_reviewer.agents.runner import Runner
from github_reviewer.agents.runner import _extract_json_object, _is_retryable_provider_error
from github_reviewer.config.schema import AppConfig, RuntimeReviewRequest
from github_reviewer.review import create_review_runner
from github_reviewer.review.models import ReviewerResult, SummaryResult, VerifierResult


def _config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "agents": {"reviewer": {"model": "reviewer"}, "verifier": {"model": "verifier"}, "summarizer": {"model": "summary"}},
            "models": {
                "reviewer": {"name": "test-reviewer"},
                "verifier": {"name": "test-verifier"},
                "summary": {"name": "test-summary"},
            },
            "observability": {"enable_agent_tracing": False},
        }
    )


def _committed_repository(tmp_path: Path) -> tuple[str, str]:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    path = tmp_path / "service.py"
    path.write_text("def get(user):\n    return user\n", encoding="utf-8")
    subprocess.run(["git", "add", "service.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=tmp_path, check=True, capture_output=True)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True, capture_output=True, check=True).stdout.strip()
    path.write_text("def get(user):\n    return load(user.id)\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "change"], cwd=tmp_path, check=True, capture_output=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True, capture_output=True, check=True).stdout.strip()
    return base, head


def test_runner_renders_only_verified_findings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base, head = _committed_repository(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    responses = iter(
        [
            ReviewerResult.model_validate(
                {
                    "findings": [
                        {
                            "severity": "high",
                            "file": "service.py",
                            "line_start": 2,
                            "title": "Authorization is missing",
                            "evidence": "The changed lookup uses user.id directly.",
                            "trigger": "A caller passes another user id.",
                            "impact": "A record can be read without an authorization check.",
                        }
                    ]
                }
            ),
            VerifierResult.model_validate({"decisions": [{"finding_index": 0, "status": "confirmed", "reason": "No guard exists in the changed path."}]}),
            SummaryResult.model_validate({"summary": "One confirmed authorization issue."}),
        ]
    )

    async def fake_run(*args, **kwargs):
        return SimpleNamespace(final_output=next(responses))

    monkeypatch.setattr(Runner, "run", fake_run)
    runner = create_review_runner(_config(), tmp_path)
    report = asyncio.run(runner.review(RuntimeReviewRequest(repo=tmp_path, base=base, head=head)))

    assert len(report.findings) == 1
    assert report.findings[0].status == "confirmed"
    assert "Authorization is missing" in report.final_output


def test_runner_skips_models_for_empty_diff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base, _ = _committed_repository(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    async def unexpected_run(*args, **kwargs):
        raise AssertionError("model should not be called")

    monkeypatch.setattr(Runner, "run", unexpected_run)
    runner = create_review_runner(_config(), tmp_path)
    report = asyncio.run(runner.review(RuntimeReviewRequest(repo=tmp_path, base=base, head=base)))

    assert "No code changes" in report.final_output


def test_extract_json_object_accepts_markdown_fence() -> None:
    assert _extract_json_object("```json\n{\"summary\": \"ok\"}\n```") == '{"summary": "ok"}'


def test_runner_retries_transient_provider_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base, head = _committed_repository(tmp_path)
    config = _config().model_copy(
        update={"review": _config().review.model_copy(update={"provider_retry_max_attempts": 2, "provider_retry_base_delay_seconds": 0.001, "provider_retry_max_delay_seconds": 0.001})}
    )
    responses = iter(
        [
            ReviewerResult.model_validate({"findings": []}),
            SummaryResult.model_validate({"summary": "No findings."}),
        ]
    )
    attempts = 0

    async def fake_run(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary network failure")
        return SimpleNamespace(final_output=next(responses))

    async def no_sleep(delay: float) -> None:
        assert delay > 0

    monkeypatch.setattr(Runner, "run", fake_run)
    monkeypatch.setattr(runner_module.asyncio, "sleep", no_sleep)
    runner = create_review_runner(config, tmp_path)

    report = asyncio.run(runner.review(RuntimeReviewRequest(repo=tmp_path, base=base, head=head)))

    assert attempts == 3
    assert report.metadata.provider_retries == 1


def test_runner_does_not_retry_credential_errors() -> None:
    assert _is_retryable_provider_error(RuntimeError("Missing credentials for provider")) is False


def test_runner_retries_invalid_compatible_model_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base, head = _committed_repository(tmp_path)
    config = _config().model_copy(
        update={"review": _config().review.model_copy(update={"provider_retry_max_attempts": 2, "provider_retry_base_delay_seconds": 0.001, "provider_retry_max_delay_seconds": 0.001})}
    )
    responses = iter(
        [
            SimpleNamespace(final_output="not valid JSON"),
            SimpleNamespace(final_output=ReviewerResult.model_validate({"findings": []})),
            SimpleNamespace(final_output=SummaryResult.model_validate({"summary": "No findings."})),
        ]
    )

    async def fake_run(*args, **kwargs):
        return next(responses)

    async def no_sleep(delay: float) -> None:
        assert delay > 0

    monkeypatch.setattr(Runner, "run", fake_run)
    monkeypatch.setattr(runner_module.asyncio, "sleep", no_sleep)
    runner = create_review_runner(config, tmp_path)

    report = asyncio.run(runner.review(RuntimeReviewRequest(repo=tmp_path, base=base, head=head)))

    assert report.metadata.provider_retries == 1
