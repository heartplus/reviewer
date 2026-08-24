from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from github_reviewer.config.schema import ReviewConfig
from github_reviewer.errors import ToolError
from github_reviewer.observability import ReviewObserver
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


def test_test_command_returns_bounded_structured_result_without_parent_secrets(tmp_path: Path, monkeypatch) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.setenv("LOCAL_REVIEW_TEST_SECRET", "should-not-reach-child")
    script = "import os, sys; print(os.getenv('LOCAL_REVIEW_TEST_SECRET', 'missing')); print('stderr output', file=sys.stderr); sys.exit(7)"
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}"
    tools = RepositoryTools(
        tmp_path,
        ReviewConfig(allow_test_commands=True, test_command_allowlist=[command], max_test_output_bytes=200),
    )

    result = tools.run_tests(command)

    assert result == {
        "exit_code": 7,
        "stdout": "missing\n",
        "stderr": "stderr output\n",
        "timed_out": False,
        "stdout_truncated": False,
        "stderr_truncated": False,
    }


def test_test_command_reports_timeout_and_independent_truncation(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    script = "import sys, time; print('abcdefgh', flush=True); print('ijklmnop', file=sys.stderr, flush=True); time.sleep(2)"
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}"
    tools = RepositoryTools(
        tmp_path,
        ReviewConfig(allow_test_commands=True, test_command_allowlist=[command], max_test_output_bytes=4),
    )

    result = tools.run_tests(command, timeout_seconds=1)

    assert result["exit_code"] is None
    assert result["timed_out"] is True
    assert result["stdout_truncated"] is True
    assert result["stderr_truncated"] is True
    assert "[truncated to 4 bytes]" in str(result["stdout"])


def test_repository_output_redacts_secret_like_values(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "sample.py").write_text("API_KEY=sk-abcdefghijklmnopqrstuvwxyz\n", encoding="utf-8")
    tools = RepositoryTools(tmp_path, ReviewConfig())

    rendered = tools.read_file("sample.py")

    assert "sk-abcdefghijklmnopqrstuvwxyz" not in rendered
    assert "[REDACTED]" in rendered


def test_changed_files_preserves_rename_status_and_tool_telemetry(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "old name.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=tmp_path, check=True, capture_output=True)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True, check=True, capture_output=True).stdout.strip()
    subprocess.run(["git", "mv", "old name.py", "new name.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "rename"], cwd=tmp_path, check=True, capture_output=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True, check=True, capture_output=True).stdout.strip()
    failures: list[str] = []
    observer = ReviewObserver("run-1")
    tools = RepositoryTools(tmp_path, ReviewConfig())
    tools.set_observer(observer, failures)

    files = tools.changed_files(base, head)
    with pytest.raises(ToolError):
        tools.read_file("../outside.py")

    assert files == [{"status": "R100", "path": "new name.py", "old_path": "old name.py"}]
    assert observer.events[0]["event"] == "tool.completed"
    assert observer.events[0]["tool"] == "changed_files"
    assert "timestamp" in observer.events[0]
    assert observer.events[0]["level"] == "info"
    assert observer.events[1]["event"] == "tool.failed"
    assert failures == ["PATH_OUTSIDE_REPO"]


def test_history_all_and_root_diff_use_empty_tree_baseline(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "initial.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "initial.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "root"], cwd=tmp_path, check=True, capture_output=True)
    root = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True, check=True, capture_output=True).stdout.strip()
    tools = RepositoryTools(tmp_path, ReviewConfig())

    commits = tools.commit_history_all(root)
    empty_tree = tools.parent_commit(root)

    assert commits == [root]
    assert "initial.py" in tools.get_diff(empty_tree, root)
    assert tools.changed_files(empty_tree, root) == [{"status": "A", "path": "initial.py"}]
