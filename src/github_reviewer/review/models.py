from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from github_reviewer.config.schema import RuntimeReviewRequest


class ReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FindingStatus(StrEnum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    NEEDS_EVIDENCE = "needs_evidence"


class ReviewFinding(ReviewModel):
    id: str = ""
    severity: Severity
    status: FindingStatus = FindingStatus.CANDIDATE
    file: str
    line_start: int = Field(ge=1)
    line_end: int | None = Field(default=None, ge=1)
    title: str = Field(min_length=1, max_length=200)
    evidence: str = Field(min_length=1)
    trigger: str = Field(min_length=1)
    impact: str = Field(min_length=1)
    suggested_fix: str | None = None
    verifier_reason: str | None = None
    source_agent: str = "reviewer"

    @field_validator("file")
    @classmethod
    def validate_file(cls, value: str) -> str:
        if not value or value.startswith("/") or ".." in value.split("/"):
            raise ValueError("file must be a repository-relative path")
        return value

    @field_validator("line_end")
    @classmethod
    def validate_line_end(cls, value: int | None, info) -> int | None:
        if value is not None and value < info.data["line_start"]:
            raise ValueError("line_end must be at or after line_start")
        return value

    def with_stable_id(self) -> "ReviewFinding":
        if self.id:
            return self
        raw = f"{self.file}\0{self.line_start}\0{self.title.strip().lower()}"
        return self.model_copy(update={"id": hashlib.sha256(raw.encode()).hexdigest()[:16]})


class ReviewerResult(ReviewModel):
    summary: str = ""
    findings: list[ReviewFinding] = Field(default_factory=list)
    test_suggestions: list[str] = Field(default_factory=list)


class VerificationDecision(ReviewModel):
    finding_index: int = Field(ge=0)
    status: Literal["confirmed", "rejected", "needs_evidence"]
    reason: str = Field(min_length=1)


class VerifierResult(ReviewModel):
    decisions: list[VerificationDecision] = Field(default_factory=list)
    summary: str = ""


class SummaryResult(ReviewModel):
    summary: str = ""
    residual_risks: list[str] = Field(default_factory=list)
    test_gaps: list[str] = Field(default_factory=list)


class StageStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ReviewStage(ReviewModel):
    name: str
    status: StageStatus = StageStatus.PENDING
    model: str | None = None
    provider: str | None = None
    duration_ms: int | None = None
    error_code: str | None = None


class ReviewRunMetadata(ReviewModel):
    run_id: str = Field(default_factory=lambda: uuid4().hex)
    schema_version: str = "v1"
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    diff_truncated: bool = False
    tool_failures: list[str] = Field(default_factory=list)
    stages: list[ReviewStage] = Field(default_factory=list)


class ReviewReport(ReviewModel):
    request: RuntimeReviewRequest
    reviewer_output: str = ""
    verifier_output: str = ""
    findings: list[ReviewFinding] = Field(default_factory=list)
    final_output: str = ""
    metadata: ReviewRunMetadata = Field(default_factory=ReviewRunMetadata)

