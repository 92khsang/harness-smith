"""The shapes the runtime's locations take, and how a location becomes Locators.

Both scans read the same runtime, so the file names and glob patterns its layout is made of,
and the two operations that turn a location into Locators, live here rather than once in each
scan.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["MARKDOWN", "MARKDOWN_TREE", "NESTED_SKILLS", "SKILL_FILE", "files", "locator"]

SKILL_FILE = "SKILL.md"
MARKDOWN = ".md"

# A skill directory holds its `SKILL.md` exactly one level down; a directory of Markdown
# artifacts is walked whole.
NESTED_SKILLS = "*/SKILL.md"
MARKDOWN_TREE = "**/*.md"


def files(directory: Path, pattern: str) -> list[Path]:
    """Every file under ``directory`` matching ``pattern``, in Locator order. A location that
    is not a directory holds nothing, which is not a finding: a component may be declared
    before it is written."""
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob(pattern) if path.is_file())


def locator(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()
