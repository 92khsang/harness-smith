"""Finding the repository root the operation runs against."""

from __future__ import annotations

from pathlib import Path

REPOSITORY_MARKER = ".git"


def is_repository_root(candidate: Path) -> bool:
    return (candidate / REPOSITORY_MARKER).exists()


def find_repository_root(working_directory: Path) -> Path | None:
    """The nearest ancestor of ``working_directory`` that is a repository root."""
    start = working_directory.resolve()
    for candidate in (start, *start.parents):
        if is_repository_root(candidate):
            return candidate
    return None


def resolve_repository_root(explicit_root: Path | None, working_directory: Path) -> Path | None:
    """An explicit root is authoritative and is still required to be a repository."""
    if explicit_root is None:
        return find_repository_root(working_directory)
    resolved = explicit_root.expanduser().resolve()
    return resolved if resolved.is_dir() and is_repository_root(resolved) else None
