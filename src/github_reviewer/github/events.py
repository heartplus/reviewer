from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from github_reviewer.errors import IntegrationError


@dataclass(frozen=True)
class PullRequestEvent:
    owner: str
    repo: str
    number: int
    base_ref: str
    base_sha: str
    head_ref: str
    head_sha: str
    clone_url: str
    action: str

    @property
    def repository(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def idempotency_key(self) -> str:
        return f"{self.repository}:{self.number}:{self.head_sha}"

    @classmethod
    def from_webhook(cls, payload: dict) -> "PullRequestEvent":
        try:
            repository = payload["repository"]
            pull_request = payload["pull_request"]
            return cls(
                owner=repository["owner"]["login"],
                repo=repository["name"],
                number=int(payload["number"]),
                base_ref=pull_request["base"]["ref"],
                base_sha=pull_request["base"]["sha"],
                head_ref=pull_request["head"]["ref"],
                head_sha=pull_request["head"]["sha"],
                clone_url=repository["clone_url"],
                action=payload["action"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise IntegrationError("INVALID_WEBHOOK", "Pull request webhook payload is incomplete") from exc


def verify_webhook_signature(body: bytes, signature: str | None, secret: str) -> None:
    if not signature or not signature.startswith("sha256="):
        raise IntegrationError("INVALID_SIGNATURE", "Webhook signature is missing or malformed")
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise IntegrationError("INVALID_SIGNATURE", "Webhook signature verification failed")
