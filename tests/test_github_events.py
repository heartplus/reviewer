import hashlib
import hmac

import pytest

from github_reviewer.errors import IntegrationError
from github_reviewer.github.events import PullRequestEvent, verify_webhook_signature


def test_pull_request_event_and_signature() -> None:
    payload = {
        "action": "synchronize",
        "number": 12,
        "repository": {"owner": {"login": "acme"}, "name": "demo", "clone_url": "https://example.com/demo.git"},
        "pull_request": {"base": {"ref": "main", "sha": "base"}, "head": {"ref": "topic", "sha": "head"}},
    }
    event = PullRequestEvent.from_webhook(payload)
    body = b'{"event":"test"}'
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()

    verify_webhook_signature(body, signature, "secret")

    assert event.repository == "acme/demo"
    assert event.idempotency_key == "acme/demo:12:head"


def test_invalid_webhook_signature_is_rejected() -> None:
    with pytest.raises(IntegrationError, match="INVALID_SIGNATURE"):
        verify_webhook_signature(b"body", "sha256=invalid", "secret")
