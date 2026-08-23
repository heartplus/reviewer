from github_reviewer.review.models import FindingStatus, ReviewFinding, Severity, SummaryResult
from github_reviewer.review.render import render_markdown


def _finding(status: FindingStatus) -> ReviewFinding:
    return ReviewFinding(
        severity=Severity.HIGH,
        status=status,
        file="src/example.py",
        line_start=42,
        title="Missing authorization check",
        evidence="The lookup does not include tenant_id.",
        trigger="A signed-in user requests another tenant's record.",
        impact="Cross-tenant data can be returned.",
        suggested_fix="Filter by tenant_id.",
    ).with_stable_id()


def test_finding_id_is_stable() -> None:
    assert _finding(FindingStatus.CANDIDATE).id == _finding(FindingStatus.CANDIDATE).id


def test_renderer_only_shows_confirmed_findings() -> None:
    rendered = render_markdown(
        [_finding(FindingStatus.CONFIRMED), _finding(FindingStatus.REJECTED)],
        SummaryResult(summary="Reviewed authorization changes."),
    )

    assert rendered.count("Missing authorization check") == 1
    assert "Cross-tenant data" in rendered


def test_renderer_states_empty_result_without_claiming_safety() -> None:
    rendered = render_markdown([_finding(FindingStatus.NEEDS_EVIDENCE)])

    assert "No high-confidence issues" in rendered
