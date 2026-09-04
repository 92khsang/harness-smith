"""Reading a whole file's bytes as text, in one open.

Asking the filesystem whether a file is there and then reading it are two answers about two
moments. Between them a file can appear or vanish, and a path that is not a regular file
answers "nothing here" to the first question while holding something somebody put there. A
caller that has to tell "nothing was declared" from "something is declared and could not be
read" needs both answers to come from the read that happened, so the path is opened once and
the open file is what everything else is asked about.

Every reason is written here rather than taken from the operating system. A message built from
``strerror`` varies by platform and locale, and a result document these tools promise to be
reproducible cannot carry one.

No reason names the path: a diagnostic carries the Locator in its subject, and messages stay
free of absolute paths.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

__all__ = ["TextFile", "TextFileState", "read_text_file"]

# Non-blocking, so that a named pipe answers instead of waiting for a writer that may never
# come; binary, so that no platform rewrites the bytes on the way in.
FLAGS = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)

CHUNK = 65536


class TextFileState(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNREADABLE = "unreadable"


@dataclass(frozen=True)
class TextFile:
    """A file's text, or the reason there is none to read."""

    state: TextFileState
    text: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        if self.text and self.state is not TextFileState.PRESENT:
            raise ValueError("text is what the read returned, so only a file that read has it")
        if bool(self.reason) is (self.state is TextFileState.PRESENT):
            raise ValueError("a reason says why there is no text, and only then")


def read_text_file(path: Path) -> TextFile:
    """``path``'s bytes as UTF-8 text.

    ``ABSENT`` is nothing at that path. Everything else that stops the read is ``UNREADABLE``:
    a directory or a device where a file was expected, a symbolic link with nothing at the
    other end, a file that would not open, and bytes that never became text. Each of those is
    somebody having put something there, and reading them as silence would let a botched file
    pass for a deliberate decision to declare nothing.

    A symbolic link that does resolve is read as the file it names. Following one is how a
    checkout that keeps its governance files elsewhere works at all, and what is read is a
    file either way.
    """
    try:
        descriptor = os.open(path, FLAGS)
    except (FileNotFoundError, NotADirectoryError):
        return _nothing_opened(path)
    except PermissionError:
        return _unreadable("the file could not be opened, because permission was denied")
    except OSError:
        return _unreadable("the file could not be opened")
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return _unreadable("the path is not a regular file")
        data = _bytes(descriptor)
    except OSError:
        return _unreadable("the file could not be read")
    finally:
        os.close(descriptor)
    try:
        return TextFile(TextFileState.PRESENT, text=data.decode("utf-8"))
    except UnicodeDecodeError:
        return _unreadable("the file is not valid UTF-8 text")


def _nothing_opened(path: Path) -> TextFile:
    """Nothing opened at ``path``, which is two answers: no entry there at all, or a symbolic
    link with nothing at the other end.

    That second look is taken only once the open has already failed, so it can never disagree
    with content that was read.
    """
    if path.is_symlink():
        return _unreadable("the path is a symbolic link with nothing at the other end")
    return TextFile(TextFileState.ABSENT, reason="there is no file at that path")


def _unreadable(reason: str) -> TextFile:
    return TextFile(TextFileState.UNREADABLE, reason=reason)


def _bytes(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    while chunk := os.read(descriptor, CHUNK):
        chunks.append(chunk)
    return b"".join(chunks)
