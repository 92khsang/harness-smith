"""Reading a JSON Artifact Container.

An Artifact Container holds artifacts addressed by pointer rather than by path, so the whole
file has to be read before any pointer into it means anything, and a read that fails leaves
nothing addressable behind.

The file layer and the JSON layer fail separately, and the state says which, so a caller that
answers them differently never has to read the reason to find out. Within the JSON layer the
reason says whether the text was not JSON at all or was JSON of the wrong shape. Nothing
branches on that second difference, because neither case leaves a member to point at.

What counts as JSON here is RFC 8259, not what Python's parser happens to allow. ``NaN`` and
the infinities are refused because Section 6 does not permit them, and Python accepts them
only as an extension. A leading byte order mark is ignored because Section 8.1 lets a parser
ignore one rather than treat it as an error.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

__all__ = [
    "BYTE_ORDER_MARK",
    "JsonDocument",
    "JsonDocumentState",
    "parse_json_document",
    "read_json_document",
]

BYTE_ORDER_MARK = "\ufeff"


class JsonDocumentState(StrEnum):
    PARSED = "parsed"
    INVALID = "invalid"
    FILE_UNREADABLE = "file-unreadable"


class _UndefinedNumberError(ValueError):
    """A literal Python's parser accepts and JSON does not define."""


@dataclass(frozen=True)
class JsonDocument:
    """A JSON container's members, or the reason there are none to read."""

    state: JsonDocumentState
    members: Mapping[str, object]
    reason: str

    @classmethod
    def parsed(cls, members: Mapping[str, object]) -> JsonDocument:
        return cls(JsonDocumentState.PARSED, members, "")

    @classmethod
    def invalid(cls, reason: str) -> JsonDocument:
        """The text is there and does not read as a JSON object of members."""
        return cls(JsonDocumentState.INVALID, {}, reason)

    @classmethod
    def file_unreadable(cls, reason: str) -> JsonDocument:
        """The file's bytes never became text, so there was no document to look at."""
        return cls(JsonDocumentState.FILE_UNREADABLE, {}, reason)


def parse_json_document(text: str) -> JsonDocument:
    """Read ``text``, which is a whole JSON file."""
    try:
        loaded = json.loads(text.removeprefix(BYTE_ORDER_MARK), parse_constant=_refuse)
    except _UndefinedNumberError as error:
        return JsonDocument.invalid(f"the file is not valid JSON: {error} is not a JSON number")
    except json.JSONDecodeError as error:
        return JsonDocument.invalid(
            f"the file is not valid JSON: {error.msg}, at line {error.lineno} column {error.colno}"
        )
    if not isinstance(loaded, dict):
        return JsonDocument.invalid(f"the file is a JSON {_shape(loaded)}, not an object")
    members: dict[str, object] = loaded
    return JsonDocument.parsed(members)


def read_json_document(path: Path) -> JsonDocument:
    """Read ``path``'s JSON. A file whose bytes never become text has no document.

    No reason names the path: a diagnostic carries the Locator in its subject, and messages
    stay free of absolute paths.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return JsonDocument.file_unreadable("the file is not valid UTF-8 text")
    except OSError as error:
        return JsonDocument.file_unreadable(
            f"the file could not be read: {error.strerror or 'unknown error'}"
        )
    return parse_json_document(text)


def _refuse(literal: str) -> object:
    raise _UndefinedNumberError(literal)


def _shape(value: object) -> str:
    return "array" if isinstance(value, list) else "scalar"
