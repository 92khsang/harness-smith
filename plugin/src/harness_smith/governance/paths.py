"""Comparing the repository-relative paths a governance file keys its entries by.

A path is normalised lexically and never resolved against the filesystem: resolving would
follow symlinks and answer differently on different machines, and these files are compared,
diffed and merged by people who are not on the machine that wrote them.

Two spellings of one path are one key. That is what makes "a path appearing twice in one
mapping" a rule with something to catch: `docs/x.md` and `./docs/x.md` name one file.
"""

from __future__ import annotations

__all__ = ["normalised"]

CURRENT = "./"


def normalised(path: str) -> str:
    """``path`` as the one spelling entries are compared by.

    Separators become forward slashes, a leading `./` is dropped however many times it is
    written, and repeated slashes collapse. Nothing else moves: a `..` keeps its meaning,
    because removing one would name a different file whenever a symlink is in the way.
    """
    forward = path.replace("\\", "/")
    while "//" in forward:
        forward = forward.replace("//", "/")
    while forward.startswith(CURRENT):
        forward = forward[len(CURRENT) :]
    return forward
