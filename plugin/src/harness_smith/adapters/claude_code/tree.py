"""Listing what is at a location, and naming what is found.

Both scans address artifacts by a Locator relative to the root they scanned, so the two
operations that turn a location into Locators live in one place rather than in each scan.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["files", "locator"]


def files(directory: Path, pattern: str) -> list[Path]:
    """Every file under ``directory`` matching ``pattern``, in Locator order. A location that
    is not a directory holds nothing, which is not a finding: a component may be declared
    before it is written."""
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob(pattern) if path.is_file())


def locator(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()
