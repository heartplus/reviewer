from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

_SECRET_PATTERN = re.compile(r"(?i)(?:api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,]+")


def redact(value: str) -> str:
    return _SECRET_PATTERN.sub("[REDACTED]", value)


@dataclass
class ReviewObserver:
    run_id: str
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("github_reviewer"))
    events: list[dict[str, object]] = field(default_factory=list)

    def event(self, name: str, **attributes: object) -> None:
        payload = {"event": name, "run_id": self.run_id, **attributes}
        safe_payload = {key: redact(value) if isinstance(value, str) else value for key, value in payload.items()}
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

