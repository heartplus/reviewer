from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

import github_reviewer.cli as cli
from github_reviewer.errors import ProviderError
from github_reviewer.review.models import ReviewReport


def _write_config(path: Path) -> Path:
    config_path = path / "reviewer.yaml"
    config_path.write_text(
        """
agents:
  reviewer: {model: reviewer}
  verifier: {model: verifier}
  summarizer: {model: summarizer}
models:
  reviewer: {name: test-reviewer}
  verifier: {name: test-verifier}
  summarizer: {name: test-summarizer}
observability:
  enable_agent_tracing: false
""".strip(),
        encoding="utf-8",
    )
    return config_path


def _commit(repo: Path, content: str, message: str) -> str:
    (repo / "service.py").write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "service.py"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo, check=True, capture_output=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, text=True, check=True, capture_output=True).stdout.strip()


def _repository(tmp_path: Path) -> tuple[str, str]:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    base = _commit(tmp_path, "value = 1\n", "base")
    head = _commit(tmp_path, "value = 2\n", "change")
    return base, head


def test_review_cli_renders_report_and_redacts_intermediate_output(tmp_path: Path, monkeypatch) -> None:
    config_path = _write_config(tmp_path)
    calls = []

    class FakeRunner:
        async def review(self, request):
            calls.append(request)
            return ReviewReport(
                request=request,
                reviewer_output="api_key=sk-abcdefghijklmnopqrstuvwxyz",
                verifier_output="verified",
                final_output="## Code Review\n\nDone.\n",
            )

    monkeypatch.setattr(cli, "create_review_runner", lambda config, repo: FakeRunner())
    result = CliRunner().invoke(
        cli.app,
        ["review", "--repo", str(tmp_path), "--base", "base", "--head", "head", "--config", str(config_path), "--show-intermediate"],
    )

    assert result.exit_code == 0
    assert len(calls) == 1
    assert "Done." in result.stdout
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in result.stdout
    assert "[REDACTED]" in result.stdout


def test_review_cli_accepts_commit_and_resolves_its_parent(tmp_path: Path, monkeypatch) -> None:
    base, head = _repository(tmp_path)
    config_path = _write_config(tmp_path)
    calls = []

    class FakeRunner:
        async def review(self, request):
            calls.append(request)
            return ReviewReport(request=request, final_output="## Code Review\n\nDone.\n")

    monkeypatch.setattr(cli, "create_review_runner", lambda config, repo: FakeRunner())
    result = CliRunner().invoke(
        cli.app,
        ["review", "--repo", str(tmp_path), "--commit", head, "--config", str(config_path)],
    )

    assert result.exit_code == 0
    assert calls[0].base == base
    assert calls[0].head == head
    assert calls[0].commit_sha == head


def test_review_cli_rejects_commit_combined_with_range_arguments(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)

    result = CliRunner().invoke(
        cli.app,
        ["review", "--repo", str(tmp_path), "--commit", "HEAD", "--base", "HEAD", "--config", str(config_path)],
    )

    assert result.exit_code == 2
    assert "INVALID_ARGUMENTS" in result.stderr


def test_history_cli_reviews_each_commit(tmp_path: Path, monkeypatch) -> None:
    base, head = _repository(tmp_path)
    config_path = _write_config(tmp_path)
    calls = []

    class FakeRunner:
        async def review(self, request):
            calls.append(request)
            return ReviewReport(request=request, final_output="## Code Review\n\nDone.\n")

    monkeypatch.setattr(cli, "create_review_runner", lambda config, repo: FakeRunner())
    result = CliRunner().invoke(
        cli.app,
        ["history", "--repo", str(tmp_path), "--base", base, "--head", head, "--config", str(config_path)],
    )

    assert result.exit_code == 0
    assert [call.head for call in calls] == [head]
    assert f"Commit {head[:12]}" in result.stdout


def test_history_all_cli_includes_root_commit(tmp_path: Path, monkeypatch) -> None:
    base, head = _repository(tmp_path)
    config_path = _write_config(tmp_path)
    calls = []

    class FakeRunner:
        async def review(self, request):
            calls.append(request)
            return ReviewReport(request=request, final_output="## Code Review\n\nDone.\n")

    monkeypatch.setattr(cli, "create_review_runner", lambda config, repo: FakeRunner())
    result = CliRunner().invoke(
        cli.app,
        ["history", "--repo", str(tmp_path), "--head", head, "--all", "--config", str(config_path)],
    )

    assert result.exit_code == 0
    assert len(calls) == 2
    assert calls[0].head == base


def test_history_cli_continues_after_a_failed_commit(tmp_path: Path, monkeypatch) -> None:
    base, head = _repository(tmp_path)
    config_path = _write_config(tmp_path)
    calls = []

    class FlakyRunner:
        async def review(self, request):
            calls.append(request)
            if request.head == base:
                raise ProviderError("PROVIDER_FAILED", "temporary provider failure", retryable=True)
            return ReviewReport(request=request, final_output="## Code Review\n\nDone.\n")

    monkeypatch.setattr(cli, "create_review_runner", lambda config, repo: FlakyRunner())
    result = CliRunner().invoke(
        cli.app,
        ["history", "--repo", str(tmp_path), "--head", head, "--all", "--config", str(config_path)],
    )

    assert result.exit_code == 4
    assert [call.head for call in calls] == [base, head]
    assert "History review completed with 1 failed commit" in result.stderr


def test_cli_maps_configuration_and_provider_failures(tmp_path: Path, monkeypatch) -> None:
    missing = tmp_path / "missing.yaml"
    config_error = CliRunner().invoke(cli.app, ["review", "--repo", str(tmp_path), "--config", str(missing)])

    assert config_error.exit_code == 2
    assert "CONFIG_NOT_FOUND" in config_error.stderr

    config_path = _write_config(tmp_path)

    class FailingRunner:
        async def review(self, request):
            raise ProviderError("PROVIDER_FAILED", "provider unavailable", retryable=True)

    monkeypatch.setattr(cli, "create_review_runner", lambda config, repo: FailingRunner())
    provider_error = CliRunner().invoke(cli.app, ["review", "--repo", str(tmp_path), "--config", str(config_path)])

    assert provider_error.exit_code == 4
    assert "PROVIDER_FAILED" in provider_error.stderr
