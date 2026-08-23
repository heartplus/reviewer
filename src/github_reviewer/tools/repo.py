from __future__ import annotations

import subprocess
from pathlib import Path

from github_reviewer.config.schema import ReviewConfig
from github_reviewer.errors import RepositoryError, ToolError


class RepositoryTools:
    """Auditable, read-only access to one Git working tree."""

    def __init__(self, repo_root: str | Path, review_config: ReviewConfig) -> None:
        candidate = Path(repo_root).expanduser().resolve()
        if not candidate.is_dir():
            raise RepositoryError("REPO_NOT_FOUND", f"Repository directory does not exist: {candidate}")
        self.repo_root = self._resolve_git_root(candidate)
        self.review_config = review_config
        self._snapshot_ref: str | None = None

    def set_snapshot_ref(self, ref: str | None) -> None:
        """Select the Git tree used by context tools without changing the worktree."""
        if ref is not None:
            self._validate_ref(ref)
        self._snapshot_ref = ref

    def get_diff(self, base_ref: str, head_ref: str = "HEAD", *, context_lines: int = 8) -> str:
        self._validate_ref(base_ref)
        self._validate_ref(head_ref)
        if not 0 <= context_lines <= self.review_config.max_context_lines:
            raise ToolError("INVALID_CONTEXT", f"context_lines must be between 0 and {self.review_config.max_context_lines}")
        output = self._git([
            "diff",
            "--no-ext-diff",
            f"--unified={context_lines}",
            f"{base_ref}...{head_ref}",
            "--",
        ])
        return _truncate(output, self.review_config.max_diff_bytes)

    def changed_files(self, base_ref: str, head_ref: str = "HEAD") -> list[str]:
        self._validate_ref(base_ref)
        self._validate_ref(head_ref)
        output = self._git(["diff", "--name-only", "-z", f"{base_ref}...{head_ref}", "--"])
        files = [entry for entry in output.split("\0") if entry]
        if len(files) > self.review_config.max_changed_files:
            return files[: self.review_config.max_changed_files]
        return files

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
        return _truncate(rendered, self.review_config.max_file_bytes)

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
                return _truncate(output, self.review_config.max_file_bytes)
            raise ToolError("GREP_FAILED", output or "Repository search failed")
        args = ["rg", "--line-number", "--color", "never", "--max-count", str(max_matches)]
        if path_glob:
            args.extend(["--glob", path_glob])
        args.extend(["--", pattern, "."])
        output, returncode = self._run(args, check=False)
        if returncode in {0, 1}:
            return _truncate(output, self.review_config.max_file_bytes)
        raise ToolError("GREP_FAILED", output or "Repository search failed")

    def git_blame(self, path: str, *, start: int, end: int) -> str:
        if start < 1 or end < start:
            raise ToolError("INVALID_LINE_RANGE", "Line range must start at 1 and end at or after start")
        self._safe_path(path, must_exist=self._snapshot_ref is None)
        args = ["blame", "-L", f"{start},{end}"]
        if self._snapshot_ref:
            args.append(self._snapshot_ref)
        args.extend(["--", path])
        return _truncate(self._git(args), self.review_config.max_file_bytes)

    def commit_history(self, base_ref: str, head_ref: str, *, limit: int = 100) -> list[str]:
        self._validate_ref(base_ref)
        self._validate_ref(head_ref)
        if limit < 1:
            raise ToolError("INVALID_HISTORY_LIMIT", "History limit must be positive")
        output = self._git(["rev-list", "--reverse", f"--max-count={limit}", f"{base_ref}..{head_ref}"])
        return [commit for commit in output.splitlines() if commit]

    def parent_commit(self, commit: str) -> str:
        self._validate_ref(commit)
        output = self._git(["rev-parse", "--verify", f"{commit}^"])
        return output.strip()

    def run_tests(self, command: str, *, timeout_seconds: int = 120) -> str:
        if not self.review_config.allow_test_commands:
            raise ToolError("COMMAND_DISABLED", "Test commands are disabled by configuration")
        if command not in self.review_config.test_command_allowlist:
            raise ToolError("COMMAND_NOT_ALLOWED", "Test command is not in the configured allowlist")
        if timeout_seconds <= 0 or timeout_seconds > 900:
            raise ToolError("INVALID_TIMEOUT", "timeout_seconds must be between 1 and 900")
        args = command.split()
        if not args:
            raise ToolError("COMMAND_NOT_ALLOWED", "Empty test command is not allowed")
        try:
            output, _ = self._run(args, timeout_seconds=timeout_seconds, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ToolError("COMMAND_TIMEOUT", f"Test command timed out after {timeout_seconds} seconds", retryable=False) from exc
        return _truncate(output, self.review_config.max_test_output_bytes)

    # Backward-compatible name for the initial framework API.
    def run_command(self, command: str, *, timeout_seconds: int = 120) -> str:
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
        if not ref or ref.startswith("-") or "\0" in ref:
            raise ToolError("INVALID_REF", "Git ref is invalid")
        output, returncode = self._run(["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], check=False)
        if returncode != 0:
            raise ToolError("INVALID_REF", f"Git ref cannot be resolved: {ref}")

    def _git(self, args: list[str]) -> str:
        output, _ = self._run(["git", *args])
        return output

    def _run(self, args: list[str], *, timeout_seconds: int = 60, check: bool = True) -> tuple[str, int]:
        try:
            completed = subprocess.run(
                args,
                cwd=self.repo_root,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise ToolError("COMMAND_TIMEOUT", f"Repository command timed out after {timeout_seconds} seconds")
        except OSError as exc:
            raise ToolError("COMMAND_FAILED", f"Cannot execute repository command: {args[0]}") from exc
        output = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)
        if check and completed.returncode != 0:
            raise ToolError("GIT_FAILED", output or "Repository command failed")
        return output, completed.returncode

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
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return f"{truncated}\n\n[truncated to {max_bytes} bytes]"
