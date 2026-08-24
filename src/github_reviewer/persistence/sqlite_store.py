from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from github_reviewer.review.models import ReviewReport, ReviewRunMetadata, ReviewStage
from github_reviewer.observability import redact


class SQLiteReviewStore:
    """Local durable store for runs, stages, findings, and publish outbox work."""

    def __init__(self, path: str | Path, config_version: str = "v1") -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.config_version = config_version
        self._create_schema()

    def start_run(self, request, metadata: ReviewRunMetadata) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO review_runs
                (run_id, repository, source, pull_request_number, base_ref, head_ref, commit_sha,
                 config_version, status, started_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running', ?)
                """,
                (
                    metadata.run_id,
                    redact(str(request.repo)),
                    request.source,
                    request.pull_request_number,
                    request.base,
                    request.head,
                    request.commit_sha,
                    self.config_version,
                    metadata.started_at.isoformat(),
                ),
            )

    def record_stage(self, run_id: str, stage: ReviewStage) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO review_stages
                (run_id, stage, status, model, provider, duration_ms, error_code)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, stage.name, stage.status, stage.model, stage.provider, stage.duration_ms, stage.error_code),
            )

    def complete_run(self, report: ReviewReport) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE review_runs SET status = 'completed', completed_at = ?, final_output = ? WHERE run_id = ?",
                (report.metadata.completed_at.isoformat() if report.metadata.completed_at else None, redact(report.final_output), report.metadata.run_id),
            )
            conn.execute("DELETE FROM findings WHERE run_id = ?", (report.metadata.run_id,))
            conn.executemany(
                """
                INSERT INTO findings
                (run_id, finding_id, severity, status, file, line_start, line_end, title, evidence,
                 trigger_text, impact, suggested_fix, verifier_reason, source_agent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        report.metadata.run_id,
                        finding.id,
                        finding.severity,
                        finding.status,
                        redact(finding.file),
                        finding.line_start,
                        finding.line_end,
                        redact(finding.title),
                        redact(finding.evidence),
                        redact(finding.trigger),
                        redact(finding.impact),
                        redact(finding.suggested_fix) if finding.suggested_fix else None,
                        redact(finding.verifier_reason) if finding.verifier_reason else None,
                        finding.source_agent,
                    )
                    for finding in report.findings
                ],
            )

    def fail_run(self, metadata: ReviewRunMetadata, error_code: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE review_runs SET status = 'failed', completed_at = ?, error_code = ? WHERE run_id = ?",
                (metadata.completed_at.isoformat() if metadata.completed_at else None, error_code, metadata.run_id),
            )

    def enqueue_comment(self, run_id: str, payload: dict[str, object], idempotency_key: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO publish_outbox (run_id, idempotency_key, payload, status) VALUES (?, ?, ?, 'pending')",
                (run_id, idempotency_key, json.dumps(payload, sort_keys=True)),
            )

    def pending_comments(self, limit: int = 20) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, run_id, idempotency_key, payload, attempts FROM publish_outbox WHERE status = 'pending' ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"id": row[0], "run_id": row[1], "idempotency_key": row[2], "payload": json.loads(row[3]), "attempts": row[4]}
            for row in rows
        ]

    def mark_comment_published(self, outbox_id: int, comment_id: int) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE publish_outbox SET status = 'published', comment_id = ? WHERE id = ?", (comment_id, outbox_id))

    def mark_comment_failed(self, outbox_id: int) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE publish_outbox SET attempts = attempts + 1 WHERE id = ?", (outbox_id,))

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _create_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS review_runs (
                    run_id TEXT PRIMARY KEY,
                    repository TEXT NOT NULL,
                    source TEXT NOT NULL,
                    pull_request_number INTEGER,
                    base_ref TEXT NOT NULL,
                    head_ref TEXT NOT NULL,
                    commit_sha TEXT,
                    config_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    final_output TEXT,
                    error_code TEXT
                );
                CREATE TABLE IF NOT EXISTS review_stages (
                    run_id TEXT NOT NULL REFERENCES review_runs(run_id),
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    model TEXT,
                    provider TEXT,
                    duration_ms INTEGER,
                    error_code TEXT,
                    PRIMARY KEY (run_id, stage)
                );
                CREATE TABLE IF NOT EXISTS findings (
                    run_id TEXT NOT NULL REFERENCES review_runs(run_id),
                    finding_id TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    file TEXT NOT NULL,
                    line_start INTEGER NOT NULL,
                    line_end INTEGER,
                    title TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    trigger_text TEXT NOT NULL,
                    impact TEXT NOT NULL,
                    suggested_fix TEXT,
                    verifier_reason TEXT,
                    source_agent TEXT NOT NULL,
                    PRIMARY KEY (run_id, finding_id)
                );
                CREATE TABLE IF NOT EXISTS publish_outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES review_runs(run_id),
                    idempotency_key TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    comment_id INTEGER
                );
                """
            )
