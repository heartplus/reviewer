from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from github_reviewer.errors import IntegrationError
from github_reviewer.github.events import PullRequestEvent
from github_reviewer.review.models import FindingStatus, ReviewReport


class GitHubClient:
    """Small GitHub REST client; token acquisition remains deployment-owned."""

    def __init__(self, token_env: str, api_url: str = "https://api.github.com") -> None:
        token = os.getenv(token_env)
        if not token:
            raise IntegrationError("MISSING_GITHUB_TOKEN", f"Missing GitHub token environment variable: {token_env}")
        self._token = token
        self._api_url = api_url.rstrip("/")

    def request(self, method: str, path: str, payload: dict | None = None) -> dict | list:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self._api_url}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": "github-reviewer",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
        except (HTTPError, URLError) as exc:
            raise IntegrationError("GITHUB_API_FAILED", f"GitHub API request failed: {method} {path}", retryable=True) from exc
        return json.loads(body) if body else {}


class PullRequestCheckout:
    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def prepare(self, event: PullRequestEvent) -> Path:
        target = Path(tempfile.mkdtemp(prefix=f"github-reviewer-pr-{event.number}-", dir=self.workspace_root))
        try:
            self._git(["clone", "--no-checkout", event.clone_url, str(target)], self.workspace_root)
            self._git(["fetch", "--depth", "1", "origin", event.base_sha, event.head_sha], target)
            self._git(["checkout", "--detach", event.head_sha], target)
        except Exception:
            # The caller owns cleanup. Keeping a failed checkout can assist diagnostics.
            raise
        return target

    @staticmethod
    def _git(args: list[str], cwd: Path) -> None:
        completed = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, timeout=120, check=False)
        if completed.returncode:
            raise IntegrationError("CHECKOUT_FAILED", completed.stderr.strip() or "Git checkout failed", retryable=True)


class ReviewPublisher:
    def __init__(self, client: GitHubClient) -> None:
        self._client = client

    def publish(self, event: PullRequestEvent, report: ReviewReport) -> list[int]:
        marker = f"<!-- github-reviewer:run:{report.metadata.run_id} -->"
        summary_body = f"{marker}\n{report.final_output}"
        existing_issue_comments = self._client.request("GET", f"/repos/{event.repository}/issues/{event.number}/comments?per_page=100")
        existing_summary = _find_marked_comment(existing_issue_comments, marker)
        if existing_summary:
            summary = self._client.request("PATCH", f"/repos/{event.repository}/issues/comments/{existing_summary['id']}", {"body": summary_body})
        else:
            summary = self._client.request("POST", f"/repos/{event.repository}/issues/{event.number}/comments", {"body": summary_body})
        comment_ids = [int(summary["id"])]
        existing_review_comments = self._client.request("GET", f"/repos/{event.repository}/pulls/{event.number}/comments?per_page=100")
        for finding in report.findings:
            if finding.status != FindingStatus.CONFIRMED:
                continue
            body = f"<!-- github-reviewer:finding:{finding.id} -->\n{finding.title}\n\n{finding.impact}"
            payload = {"body": body, "commit_id": event.head_sha, "path": finding.file, "line": finding.line_start, "side": "RIGHT"}
            try:
                existing = _find_marked_comment(existing_review_comments, f"<!-- github-reviewer:finding:{finding.id} -->")
                if existing:
                    response = self._client.request("PATCH", f"/repos/{event.repository}/pulls/comments/{existing['id']}", {"body": body})
                else:
                    response = self._client.request("POST", f"/repos/{event.repository}/pulls/{event.number}/comments", payload)
                comment_ids.append(int(response["id"]))
            except IntegrationError:
                # Keep the already-published summary; callers can retry inline comments from outbox.
                continue
        return comment_ids


def _find_marked_comment(comments: object, marker: str) -> dict | None:
    if not isinstance(comments, list):
        return None
    return next((comment for comment in comments if isinstance(comment, dict) and marker in str(comment.get("body", ""))), None)
