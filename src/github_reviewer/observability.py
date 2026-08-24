from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

_KEY_VALUE_SECRET_PATTERN = re.compile(r"(?i)(?:api[_-]?key|token|password|secret|private[_-]?key)\s*[:=]\s*[^\s,]+")
_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_KNOWN_TOKEN_PATTERN = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,})\b")
_PRIVATE_KEY_PATTERN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL)
_URI_CREDENTIAL_PATTERN = re.compile(r"([a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@", re.IGNORECASE)


def redact(value: str) -> str:
    value = _PRIVATE_KEY_PATTERN.sub("[REDACTED_PRIVATE_KEY]", value)
    value = _URI_CREDENTIAL_PATTERN.sub(r"\1[REDACTED]@", value)
    value = _BEARER_PATTERN.sub("Bearer [REDACTED]", value)
    value = _KNOWN_TOKEN_PATTERN.sub("[REDACTED]", value)
    return _KEY_VALUE_SECRET_PATTERN.sub("[REDACTED]", value)


def redact_value(value: object) -> object:
    """Recursively redact values before they cross a local output boundary."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: redact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    return value


@dataclass
class ReviewObserver:
    run_id: str
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("github_reviewer"))
    events: list[dict[str, object]] = field(default_factory=list)

    def event(self, name: str, **attributes: object) -> None:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": "info",
            "event": name,
            "run_id": self.run_id,
            **attributes,
        }
        safe_payload = redact_value(payload)
        self.events.append(safe_payload)
        self.logger.info(json.dumps(safe_payload, default=str, sort_keys=True))

    @contextmanager
    def stage(self, name: str, **attributes: object) -> Iterator[None]:
        started = time.perf_counter()
        self.event("stage.started", stage=name, **attributes)
        try:
            yield
        except Exception as exc:
            self.event("stage.failed", stage=name, duration_ms=int((time.perf_counter() - started) * 1000), error_type=type(exc).__name__)
            raise
        else:
            self.event("stage.completed", stage=name, duration_ms=int((time.perf_counter() - started) * 1000))
