from __future__ import annotations

from github_reviewer.review.models import FindingStatus, ReviewFinding, Severity, SummaryResult

_SEVERITY_ORDER = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
}


def render_markdown(findings: list[ReviewFinding], summary: SummaryResult | None = None) -> str:
    """Render only verified findings; model output never controls the result shape."""
    confirmed = sorted(
        (item for item in findings if item.status == FindingStatus.CONFIRMED),
        key=lambda item: (_SEVERITY_ORDER[item.severity], item.file, item.line_start, item.title),
    )
    parts = ["## Code Review"]
    if summary and summary.summary:
        parts.extend(["", summary.summary.strip()])
    if not confirmed:
        parts.extend(["", "No high-confidence issues were found in this change."])
    else:
        parts.extend(["", "### Confirmed findings"])
        for finding in confirmed:
            location = f"{finding.file}:{finding.line_start}"
            if finding.line_end and finding.line_end != finding.line_start:
                location = f"{location}-{finding.line_end}"
            parts.extend(
                [
                    "",
                    f"#### [{finding.severity}] `{location}` {finding.title}",
                    "",
                    f"**Impact:** {finding.impact}",
                    "",
                    f"**Evidence:** {finding.evidence}",
                    "",
                    f"**Trigger:** {finding.trigger}",
                ]
            )
            if finding.suggested_fix:
                parts.extend(["", f"**Suggested fix:** {finding.suggested_fix}"])
    if summary and summary.residual_risks:
        parts.extend(["", "### Residual risks", *[f"- {risk}" for risk in summary.residual_risks]])
    if summary and summary.test_gaps:
        parts.extend(["", "### Test gaps", *[f"- {gap}" for gap in summary.test_gaps]])
    return "\n".join(parts).strip() + "\n"

