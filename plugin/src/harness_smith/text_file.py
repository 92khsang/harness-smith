"""Reading a whole file's bytes as text, in one open.

Asking the filesystem whether a file is there and then reading it are two answers about two
moments. Between them a file can appear or vanish, and a path that is not a regular file
answers "nothing here" to the first question while holding something somebody put there. A
caller that has to tell "nothing was declared" from "something is declared and could not be
read" needs both answers to come from the read that happened.

No reason names the path: a diagnostic carries the Locator in its subject, and messages stay
free of absolute paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

__all__ = ["TextFile", "TextFileState", "read_text_file"]


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

    ``ABSENT`` is nothing at that path: no file, and no directory on the way to one. Everything
    else that stops the read is ``UNREADABLE``, a directory at the path itself and bytes that
    never became text included, because in each of those somebody put something there.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        return TextFile(TextFileState.ABSENT, reason="there is no file at that path")
    except UnicodeDecodeError:
        return TextFile(TextFileState.UNREADABLE, reason="the file is not valid UTF-8 text")
    except OSError as error:
        return TextFile(
            TextFileState.UNREADABLE,
            reason=f"the file could not be read: {error.strerror or 'unknown error'}",
        )
    return TextFile(TextFileState.PRESENT, text=text)
