from pathlib import Path
import sqlite3

from github_reviewer.config.schema import RuntimeReviewRequest
from github_reviewer.persistence import SQLiteReviewStore
from github_reviewer.review.models import ReviewReport, ReviewRunMetadata, ReviewStage, StageStatus


def test_sqlite_store_records_run_stage_and_outbox(tmp_path: Path) -> None:
    store = SQLiteReviewStore(tmp_path / "reviews.sqlite3")
    metadata = ReviewRunMetadata()
    request = RuntimeReviewRequest(repo=tmp_path, base="base", head="head")
    store.start_run(request, metadata)
    store.record_stage(metadata.run_id, ReviewStage(name="reviewer", status=StageStatus.COMPLETED))
    store.complete_run(ReviewReport(request=request, final_output="report", metadata=metadata))
    store.enqueue_comment(metadata.run_id, {"body": "report"}, "key-1")
    store.enqueue_comment(metadata.run_id, {"body": "duplicate"}, "key-1")

    pending = store.pending_comments()

    assert len(pending) == 1
    assert pending[0]["payload"] == {"body": "report"}


def test_sqlite_store_redacts_report_content(tmp_path: Path) -> None:
    store = SQLiteReviewStore(tmp_path / "reviews.sqlite3")
    metadata = ReviewRunMetadata()
    request = RuntimeReviewRequest(repo=tmp_path, base="base", head="head")
    store.start_run(request, metadata)
    store.complete_run(ReviewReport(request=request, final_output="token=sk-abcdefghijklmnopqrstuvwxyz", metadata=metadata))

    with sqlite3.connect(store.path) as connection:
        final_output = connection.execute("SELECT final_output FROM review_runs WHERE run_id = ?", (metadata.run_id,)).fetchone()[0]

    assert "sk-abcdefghijklmnopqrstuvwxyz" not in final_output
    assert "[REDACTED]" in final_output
