from github_reviewer.review.models import ReviewFinding, ReviewReport

__all__ = ["ReviewFinding", "ReviewReport", "create_review_runner"]


def create_review_runner(*args, **kwargs):
    # Lazy import prevents a package-level cycle while agent modules import result schemas.
    from github_reviewer.review.service import create_review_runner as factory

    return factory(*args, **kwargs)

__all__ = ["create_review_runner"]
