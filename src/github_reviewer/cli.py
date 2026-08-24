from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import typer
from rich.console import Console

from github_reviewer.config import load_config
from github_reviewer.config.schema import RuntimeReviewRequest
from github_reviewer.errors import ConfigurationError, ProviderError, RepositoryError, ReviewError
from github_reviewer.observability import redact
from github_reviewer.review import create_review_runner
from github_reviewer.tools import RepositoryTools

app = typer.Typer(help="Review local Git changes with configurable code-review agents.")
console = Console()
error_console = Console(stderr=True)


@app.command()
def review(
    repo: Path = typer.Option(..., help="Path to the local Git repository."),
    base: str | None = typer.Option(None, help="Base Git ref."),
    head: str | None = typer.Option(None, help="Head Git ref."),
    config: Path = typer.Option(Path("config/default.yaml"), help="Reviewer YAML configuration."),
    show_intermediate: bool = typer.Option(False, help="Print structured reviewer and verifier results."),
    verbose: bool = typer.Option(False, help="Show structured diagnostic events on stderr."),
) -> None:
    """Review a local repository diff."""
    if verbose:
        logging.basicConfig(level=logging.INFO)
    try:
        app_config = load_config(config)
        request = RuntimeReviewRequest(
            repo=repo,
            base=base or app_config.review.base_ref,
            head=head or app_config.review.head_ref,
        )
        runner = create_review_runner(app_config, repo)
        report = asyncio.run(runner.review(request))
    except ConfigurationError as exc:
        _exit(exc, 2)
    except RepositoryError as exc:
        _exit(exc, 3)
    except ProviderError as exc:
        _exit(exc, 4)
    except ReviewError as exc:
        _exit(exc, 5)
    except Exception as exc:
        error_console.print(f"Unexpected error: {type(exc).__name__}: {exc}", style="red")
        raise typer.Exit(5) from exc

    if show_intermediate:
        console.rule("Reviewer")
        console.print(redact(report.reviewer_output))
        console.rule("Verifier")
        console.print(redact(report.verifier_output))
    console.print(redact(report.final_output), end="")


@app.command("history")
def history(
    repo: Path = typer.Option(..., help="Path to the local Git repository."),
    base: str | None = typer.Option(None, help="First excluded Git ref."),
    head: str | None = typer.Option(None, help="Last included Git ref."),
    config: Path = typer.Option(Path("config/default.yaml"), help="Reviewer YAML configuration."),
    limit: int = typer.Option(20, min=1, max=200, help="Maximum commits to review."),
    all_history: bool = typer.Option(False, "--all", help="Review all reachable commits, including the root commit."),
    verbose: bool = typer.Option(False, help="Show structured diagnostic events on stderr."),
) -> None:
    """Review each committed change in a Git history range without checking out commits."""
    if verbose:
        logging.basicConfig(level=logging.INFO)
    try:
        app_config = load_config(config)
        base_ref, head_ref = base or app_config.review.base_ref, head or app_config.review.head_ref
        repo_tools = RepositoryTools(repo, app_config.review)
        commits = repo_tools.commit_history_all(head_ref, limit=limit) if all_history else repo_tools.commit_history(base_ref, head_ref, limit=limit)
        if not commits:
            console.print("No commits were found in the requested history range.")
            return
        runner = create_review_runner(app_config, repo)
        failures: list[tuple[str, ReviewError]] = []
        for commit in commits:
            parent = repo_tools.parent_commit(commit)
            request = RuntimeReviewRequest(repo=repo, base=parent, head=commit, commit_sha=commit)
            console.rule(f"Commit {commit[:12]}")
            try:
                report = asyncio.run(runner.review(request))
            except ReviewError as exc:
                failures.append((commit, exc))
                error_console.print(f"{commit[:12]}: {exc}", style="red")
                continue
            console.print(redact(report.final_output), end="")
        if failures:
            error_console.print(f"History review completed with {len(failures)} failed commit(s).", style="red")
            raise typer.Exit(_history_failure_exit_code(failures))
    except ConfigurationError as exc:
        _exit(exc, 2)
    except RepositoryError as exc:
        _exit(exc, 3)
    except ProviderError as exc:
        _exit(exc, 4)
    except ReviewError as exc:
        _exit(exc, 5)


def _exit(error: ReviewError, exit_code: int) -> None:
    error_console.print(str(error), style="red")
    raise typer.Exit(exit_code)


def _history_failure_exit_code(failures: list[tuple[str, ReviewError]]) -> int:
    if any(isinstance(error, ProviderError) for _, error in failures):
        return 4
    if any(isinstance(error, RepositoryError) for _, error in failures):
        return 3
    if any(isinstance(error, ConfigurationError) for _, error in failures):
        return 2
    return 5


if __name__ == "__main__":
    app()
