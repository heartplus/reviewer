from __future__ import annotations

from pathlib import Path

from github_reviewer.errors import ConfigurationError

_DEFAULT_INSTRUCTION_DIR = Path(__file__).resolve().parents[2] / "instructions"
_DEFAULT_FILES = frozenset({"reviewer", "verifier", "summarizer", "no_repo_tools"})


def default_instruction_path(role: str) -> Path:
    """Return the repository-managed default instruction file for an agent role."""
    filename = f"{role}.md" if role in _DEFAULT_FILES else "specialist.md"
    return _DEFAULT_INSTRUCTION_DIR / filename


def load_instruction(path: Path, *, specialist_name: str | None = None) -> str:
    """Read one editable role instruction and expand the specialist placeholder."""
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ConfigurationError("INSTRUCTION_NOT_FOUND", f"Instruction file does not exist: {resolved}")
    try:
        instruction = resolved.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ConfigurationError("INSTRUCTION_READ_FAILED", f"Cannot read instruction file: {resolved}") from exc
    if not instruction:
        raise ConfigurationError("EMPTY_INSTRUCTION", f"Instruction file is empty: {resolved}")
    if specialist_name is not None:
        instruction = instruction.replace("{{specialist_name}}", specialist_name)
    return instruction
