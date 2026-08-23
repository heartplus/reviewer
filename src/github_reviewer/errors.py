from __future__ import annotations

from dataclasses import dataclass


@dataclass(eq=False)
class ReviewError(Exception):
    """A safe, stable error exposed by the review framework."""

    code: str
    message: str
    retryable: bool = False

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class ConfigurationError(ReviewError):
    pass


class RepositoryError(ReviewError):
    pass


class ToolError(ReviewError):
    pass


class ProviderError(ReviewError):
    pass


class IntegrationError(ReviewError):
    pass
