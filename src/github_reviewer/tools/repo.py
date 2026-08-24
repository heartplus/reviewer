from __future__ import annotations

import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from github_reviewer.config.schema import ReviewConfig
from github_reviewer.errors import RepositoryError, ToolError
from github_reviewer.observability import redact

_EMPTY_TREE_REF = "__github_reviewer_empty_tree__"


@dataclass(frozen=True)
class _CommandExecution:
    stdout: str
    stderr: str
    returncode: int | None
    timed_out: bool = False


def _observed_tool(name: str):
    def decorator(method: Callable[..., Any]):
        @wraps(method)
        def wrapper(self: "RepositoryTools", *args: object, **kwargs: object) -> Any:
            started = time.perf_counter()
            try:
                result = method(self, *args, **kwargs)
            except ToolError as exc:
                self._record_tool_call(name, args, kwargs, started, success=False, error_code=exc.code)
                raise
            self._record_tool_call(name, args, kwargs, started, success=True, truncated=_is_truncated(result))
            return result

        return wrapper

    return decorator


class RepositoryTools:
    """Auditable, read-only access to one Git working tree."""

    def __init__(self, repo_root: str | Path, review_config: ReviewConfig) -> None:
        candidate = Path(repo_root).expanduser().resolve()
        if not candidate.is_dir():
            raise RepositoryError("REPO_NOT_FOUND", f"Repository directory does not exist: {candidate}")
        self.repo_root = self._resolve_git_root(candidate)
        self.review_config = review_config
        self._snapshot_ref: str | None = None
        self._empty_tree_ref: str | None = None
        self._observer: Any | None = None
        self._tool_failures: list[str] | None = None

    def set_observer(self, observer: Any | None, tool_failures: list[str] | None = None) -> None:
        """Attach per-run structured telemetry without coupling tools to the runner."""
        self._observer = observer
        self._tool_failures = tool_failures

    def set_snapshot_ref(self, ref: str | None) -> None:
        """Select the Git tree used by context tools without changing the worktree."""
        if ref is not None:
            self._validate_ref(ref)
        self._snapshot_ref = ref

    @_observed_tool("get_diff")
    def get_diff(self, base_ref: str, head_ref: str = "HEAD", *, context_lines: int = 8) -> str:
        self._validate_ref(base_ref)
        self._validate_ref(head_ref)
        if not 0 <= context_lines <= self.review_config.max_context_lines:
            raise ToolError("INVALID_CONTEXT", f"context_lines must be between 0 and {self.review_config.max_context_lines}")
        is_empty_tree = base_ref == _EMPTY_TREE_REF
        resolved_base = self._empty_tree() if is_empty_tree else base_ref
        comparison = [resolved_base, head_ref] if is_empty_tree else [f"{resolved_base}...{head_ref}"]
        output = self._git([
            "diff",
            "--no-ext-diff",
            f"--unified={context_lines}",
            *comparison,
            "--",
        ])
        return _truncate(redact(output), self.review_config.max_diff_bytes)

    @_observed_tool("changed_files")
    def changed_files(self, base_ref: str, head_ref: str = "HEAD") -> list[dict[str, str]]:
        self._validate_ref(base_ref)
        self._validate_ref(head_ref)
        is_empty_tree = base_ref == _EMPTY_TREE_REF
        resolved_base = self._empty_tree() if is_empty_tree else base_ref
        comparison = [resolved_base, head_ref] if is_empty_tree else [f"{resolved_base}...{head_ref}"]
        output = self._git(["diff", "--name-status", "-z", *comparison, "--"])
        entries = [entry for entry in output.split("\0") if entry]
        files: list[dict[str, str]] = []
        index = 0
        while index < len(entries):
            status = entries[index]
            index += 1
            if index >= len(entries):
                raise ToolError("GIT_FAILED", "Repository returned an incomplete changed-file record")
            if status.startswith(("R", "C")):
                if index + 1 >= len(entries):
                    raise ToolError("GIT_FAILED", "Repository returned an incomplete rename record")
                old_path, path = entries[index], entries[index + 1]
                index += 2
                files.append({"status": status, "path": redact(path), "old_path": redact(old_path)})
            else:
                path = entries[index]
                index += 1
                files.append({"status": status, "path": redact(path)})
        if len(files) > self.review_config.max_changed_files:
            return files[: self.review_config.max_changed_files]
        return files

    @_observed_tool("read_file")
    def read_file(self, path: str, *, start: int = 1, end: int | None = None) -> str:
        if start < 1 or (end is not None and end < start):
            raise ToolError("INVALID_LINE_RANGE", "Line range must start at 1 and end at or after start")
        target = self._safe_path(path, must_exist=self._snapshot_ref is None)
        if self._snapshot_ref:
            raw = self._show_file(self._snapshot_ref, path)
        else:
            try:
                raw = target.read_bytes()
            except OSError as exc:
                raise ToolError("FILE_READ_FAILED", f"Cannot read file: {path}") from exc
        if b"\0" in raw:
            raise ToolError("BINARY_FILE", f"Cannot read binary file: {path}")
        try:
            lines = raw.decode("utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise ToolError("BINARY_FILE", f"Cannot decode file as UTF-8: {path}") from exc
        selected = lines[start - 1 : end]
        rendered = "\n".join(f"{line_no}: {line}" for line_no, line in enumerate(selected, start=start))
        return _truncate(redact(rendered), self.review_config.max_file_bytes)

    @_observed_tool("grep")
    def grep(self, pattern: str, *, path_glob: str | None = None, max_matches: int = 80) -> str:
        if not pattern:
            raise ToolError("INVALID_PATTERN", "Search pattern cannot be empty")
        if not 1 <= max_matches <= self.review_config.max_grep_matches:
            raise ToolError("INVALID_MATCH_LIMIT", f"max_matches must be between 1 and {self.review_config.max_grep_matches}")
        if self._snapshot_ref:
            args = ["git", "grep", "-n", f"--max-count={max_matches}", "-e", pattern, self._snapshot_ref, "--"]
            if path_glob:
                args.append(path_glob)
            output, returncode = self._run(args, check=False)
            if returncode in {0, 1}:
                return _truncate(redact(output), self.review_config.max_file_bytes)
            raise ToolError("GREP_FAILED", "Repository search failed")
        args = ["rg", "--line-number", "--color", "never", "--max-count", str(max_matches)]
        if path_glob:
            args.extend(["--glob", path_glob])
        args.extend(["--", pattern, "."])
        output, returncode = self._run(args, check=False)
        if returncode in {0, 1}:
            return _truncate(redact(output), self.review_config.max_file_bytes)
        raise ToolError("GREP_FAILED", "Repository search failed")

    @_observed_tool("git_blame")
    def git_blame(self, path: str, *, start: int, end: int) -> str:
        if start < 1 or end < start:
            raise ToolError("INVALID_LINE_RANGE", "Line range must start at 1 and end at or after start")
        self._safe_path(path, must_exist=self._snapshot_ref is None)
        args = ["blame", "-L", f"{start},{end}"]
        if self._snapshot_ref:
            args.append(self._snapshot_ref)
        args.extend(["--", path])
        return _truncate(redact(self._git(args)), self.review_config.max_file_bytes)

    @_observed_tool("commit_history")
    def commit_history(self, base_ref: str, head_ref: str, *, limit: int = 100) -> list[str]:
        self._validate_ref(base_ref)
        self._validate_ref(head_ref)
        if limit < 1:
            raise ToolError("INVALID_HISTORY_LIMIT", "History limit must be positive")
        output = self._git(["rev-list", "--reverse", f"--max-count={limit}", f"{base_ref}..{head_ref}"])
        return [commit for commit in output.splitlines() if commit]

    @_observed_tool("commit_history_all")
    def commit_history_all(self, head_ref: str, *, limit: int = 100) -> list[str]:
        self._validate_ref(head_ref)
        if limit < 1:
            raise ToolError("INVALID_HISTORY_LIMIT", "History limit must be positive")
        output = self._git(["rev-list", "--reverse", f"--max-count={limit}", head_ref])
        return [commit for commit in output.splitlines() if commit]

    @_observed_tool("parent_commit")
    def parent_commit(self, commit: str) -> str:
        self._validate_ref(commit)
        output, returncode = self._run(["git", "rev-parse", "--verify", f"{commit}^"], check=False)
        return output.strip() if returncode == 0 else _EMPTY_TREE_REF

    @_observed_tool("run_tests")
    def run_tests(self, command: str, *, timeout_seconds: int = 120) -> dict[str, object]:
        if not self.review_config.allow_test_commands:
            raise ToolError("COMMAND_DISABLED", "Test commands are disabled by configuration")
        if command not in self.review_config.test_command_allowlist:
            raise ToolError("COMMAND_NOT_ALLOWED", "Test command is not in the configured allowlist")
        if timeout_seconds <= 0 or timeout_seconds > 900:
            raise ToolError("INVALID_TIMEOUT", "timeout_seconds must be between 1 and 900")
        args = shlex.split(command)
        if not args:
            raise ToolError("COMMAND_NOT_ALLOWED", "Empty test command is not allowed")
        execution = self._execute(args, timeout_seconds=timeout_seconds, env=self._minimal_test_environment())
        stdout, stdout_truncated = _truncate_with_flag(redact(execution.stdout), self.review_config.max_test_output_bytes)
        stderr, stderr_truncated = _truncate_with_flag(redact(execution.stderr), self.review_config.max_test_output_bytes)
        return {
            "exit_code": execution.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": execution.timed_out,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
        }

    # Backward-compatible name for the initial framework API.
    def run_command(self, command: str, *, timeout_seconds: int = 120) -> dict[str, object]:
        return self.run_tests(command, timeout_seconds=timeout_seconds)

    def _resolve_git_root(self, candidate: Path) -> Path:
        try:
            completed = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=candidate,
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RepositoryError("NOT_GIT_REPOSITORY", f"Cannot inspect Git repository: {candidate}") from exc
        if completed.returncode != 0 or not completed.stdout.strip():
            raise RepositoryError("NOT_GIT_REPOSITORY", f"Not a Git repository: {candidate}")
        return Path(completed.stdout.strip()).resolve()

    def _validate_ref(self, ref: str) -> None:
        if ref == _EMPTY_TREE_REF:
            return
        if not ref or ref.startswith("-") or "\0" in ref:
            raise ToolError("INVALID_REF", "Git ref is invalid")
        output, returncode = self._run(["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], check=False)
        if returncode != 0:
            raise ToolError("INVALID_REF", f"Git ref cannot be resolved: {ref}")

    def _empty_tree(self) -> str:
        if self._empty_tree_ref is not None:
            return self._empty_tree_ref
        try:
            completed = subprocess.run(
                ["git", "mktree"],
                cwd=self.repo_root,
                input="",
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ToolError("GIT_FAILED", "Cannot create an empty Git tree for root commit review") from exc
        if completed.returncode != 0 or not completed.stdout.strip():
            raise ToolError("GIT_FAILED", "Cannot create an empty Git tree for root commit review")
        self._empty_tree_ref = completed.stdout.strip()
        return self._empty_tree_ref

    def _git(self, args: list[str]) -> str:
        output, _ = self._run(["git", *args])
        return output

    def _run(self, args: list[str], *, timeout_seconds: int = 60, check: bool = True) -> tuple[str, int]:
        execution = self._execute(args, timeout_seconds=timeout_seconds)
        if execution.timed_out:
            raise ToolError("COMMAND_TIMEOUT", f"Repository command timed out after {timeout_seconds} seconds")
        assert execution.returncode is not None
        output = "\n".join(part for part in (execution.stdout.strip(), execution.stderr.strip()) if part)
        if check and execution.returncode != 0:
            raise ToolError("GIT_FAILED", "Repository command failed")
        return output, execution.returncode

    def _execute(self, args: list[str], *, timeout_seconds: int, env: dict[str, str] | None = None) -> _CommandExecution:
        try:
            completed = subprocess.run(
                args,
                cwd=self.repo_root,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            return _CommandExecution(_output_text(exc.stdout), _output_text(exc.stderr), None, timed_out=True)
        except OSError as exc:
            raise ToolError("COMMAND_FAILED", f"Cannot execute repository command: {args[0]}") from exc
        return _CommandExecution(completed.stdout, completed.stderr, completed.returncode)

    def _minimal_test_environment(self) -> dict[str, str]:
        allowed = ("PATH", "HOME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR")
        environment = {key: os.environ[key] for key in allowed if key in os.environ}
        environment.setdefault("PATH", os.defpath)
        environment.setdefault("HOME", str(self.repo_root))
        return environment

    def _record_tool_call(
        self,
        name: str,
        args: tuple[object, ...],
        kwargs: dict[str, object],
        started: float,
        *,
        success: bool,
        truncated: bool = False,
        error_code: str | None = None,
    ) -> None:
        if error_code and self._tool_failures is not None:
            self._tool_failures.append(error_code)
        if self._observer is None:
            return
        parameters = {
            "args": [redact(str(value))[:160] for value in args],
            "kwargs": {key: redact(str(value))[:160] for key, value in kwargs.items()},
        }
        self._observer.event(
            "tool.completed" if success else "tool.failed",
            tool=name,
            parameters=parameters,
            duration_ms=int((time.perf_counter() - started) * 1000),
            success=success,
            truncated=truncated,
            error_code=error_code,
        )

    def _show_file(self, ref: str, path: str) -> bytes:
        try:
            completed = subprocess.run(
                ["git", "show", f"{ref}:{path}"],
                cwd=self.repo_root,
                capture_output=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ToolError("FILE_READ_FAILED", f"Cannot read file at {ref}: {path}") from exc
        if completed.returncode != 0:
            raise ToolError("FILE_NOT_FOUND", f"File does not exist at {ref}: {path}")
        return completed.stdout

    def _safe_path(self, path: str, *, must_exist: bool = True) -> Path:
        input_path = Path(path)
        if input_path.is_absolute() or any(part == ".git" for part in input_path.parts):
            raise ToolError("PATH_OUTSIDE_REPO", f"Path is not allowed: {path}")
        target = (self.repo_root / input_path).resolve()
        if not target.is_relative_to(self.repo_root):
            raise ToolError("PATH_OUTSIDE_REPO", f"Path escapes repository: {path}")
        if must_exist and not target.exists():
            raise ToolError("FILE_NOT_FOUND", f"File does not exist: {path}")
        if must_exist and not target.is_file():
            raise ToolError("NOT_A_FILE", f"Path is not a regular file: {path}")
        return target


def _truncate(text: str, max_bytes: int) -> str:
    return _truncate_with_flag(text, max_bytes)[0]


def _truncate_with_flag(text: str, max_bytes: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, False
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return f"{truncated}\n\n[truncated to {max_bytes} bytes]", True


def _output_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def _is_truncated(value: object) -> bool:
    if isinstance(value, str):
        return "[truncated to" in value
    if isinstance(value, dict):
        return bool(value.get("stdout_truncated") or value.get("stderr_truncated"))
    return False
