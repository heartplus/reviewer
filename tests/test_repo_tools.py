from __future__ import annotations

import subprocess
from pathlib import Path

from github_reviewer.config.schema import ReviewConfig
from github_reviewer.errors import ToolError
from github_reviewer.tools.repo import RepositoryTools


def test_read_file_uses_safe_line_ranges(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    target = tmp_path / "sample.py"
    target.write_text("a\nb\nc\n", encoding="utf-8")

    tools = RepositoryTools(tmp_path, ReviewConfig())

    assert tools.read_file("sample.py", start=2, end=3) == "2: b\n3: c"


def test_path_escape_is_rejected(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    tools = RepositoryTools(tmp_path, ReviewConfig())

    try:
        tools.read_file("../outside.py")
    except ToolError as exc:
        assert exc.code == "PATH_OUTSIDE_REPO"
    else:
        raise AssertionError("expected path escape rejection")


def test_history_snapshot_reads_committed_content_not_dirty_worktree(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    target = tmp_path / "sample.py"
    target.write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "add", "sample.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=tmp_path, check=True, capture_output=True)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True, capture_output=True, check=True).stdout.strip()
    target.write_text("new\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "change"], cwd=tmp_path, check=True, capture_output=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True, capture_output=True, check=True).stdout.strip()
    target.write_text("dirty\n", encoding="utf-8")

    tools = RepositoryTools(tmp_path, ReviewConfig())
    tools.set_snapshot_ref(head)

    assert tools.get_diff(base, head)
    assert tools.read_file("sample.py") == "1: new"
    assert tools.commit_history(base, head) == [head]
    assert tools.parent_commit(head) == base
