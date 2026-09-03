"""Reading a JSON Artifact Container.

An Artifact Container holds artifacts addressed by pointer rather than by path, so the whole
file has to be read before any pointer into it means anything, and a read that fails leaves
nothing addressable behind.

Three things can fail, and they are kept apart because each answers to its own finding and its
own fix: the file's bytes never became text, the text is not JSON, or the JSON is not an
object and so holds no members to point at. A caller chooses on the state rather than by
reading the reason.

What counts as JSON here is RFC 8259, not what Python's parser happens to allow. ``NaN`` and
the infinities are refused because Section 6 does not permit them and Python accepts them only
as an extension. A leading byte order mark is ignored because Section 8.1 lets a parser ignore
one rather than treat it as an error; whether the runtime's own reader does the same is
unverified, so that is a parser policy chosen here and not a claim about Claude Code.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

__all__ = [
    "BYTE_ORDER_MARK",
    "JsonDocument",
    "JsonDocumentState",
    "JsonObject",
    "own_repeated_names",
    "parse_json_bytes",
    "parse_json_document",
    "read_json_document",
    "repeated_names",
]

BYTE_ORDER_MARK = "\ufeff"


class JsonDocumentState(StrEnum):
    PARSED = "parsed"
    FILE_UNREADABLE = "file-unreadable"
    UNPARSEABLE = "unparseable"
    NOT_AN_OBJECT = "not-an-object"


class _UndefinedNumberError(ValueError):
    """A literal Python's parser accepts and JSON does not define."""


class JsonObject(dict[str, object]):
    """A parsed JSON object that remembers which of its property names repeated.

    RFC 8259 says names within an object SHOULD be unique and leaves a repeat to the parser.
    This one retains the last value and records that the name repeated; a caller decides what
    the repeat means. Recording it is the parser's job because a repeat is gone once the object
    has collapsed into a mapping, and no later reader can tell that it happened.
    """

    repeated_names: tuple[str, ...]

    def __init__(self, pairs: list[tuple[str, object]]) -> None:
        super().__init__(pairs)
        seen: set[str] = set()
        repeated: list[str] = []
        for name, _ in pairs:
            if name in seen and name not in repeated:
                repeated.append(name)
            seen.add(name)
        self.repeated_names = tuple(repeated)


@dataclass(frozen=True)
class JsonDocument:
    """A JSON container's members, or the reason there are none to read."""

    state: JsonDocumentState
    members: Mapping[str, object]
    reason: str

    @classmethod
    def absent(cls) -> JsonDocument:
        """No document at all, which is what a plugin with no manifest has."""
        return cls(JsonDocumentState.FILE_UNREADABLE, {}, "there is no document")

    @classmethod
    def parsed(cls, members: Mapping[str, object]) -> JsonDocument:
        return cls(JsonDocumentState.PARSED, members, "")

    @classmethod
    def unparseable(cls, reason: str) -> JsonDocument:
        """The text is there and is not JSON."""
        return cls(JsonDocumentState.UNPARSEABLE, {}, reason)

    @classmethod
    def not_an_object(cls, reason: str) -> JsonDocument:
        """The text is JSON, of a shape that holds no members to point at."""
        return cls(JsonDocumentState.NOT_AN_OBJECT, {}, reason)

    @classmethod
    def file_unreadable(cls, reason: str) -> JsonDocument:
        """The file's bytes never became text, so there was no document to look at."""
        return cls(JsonDocumentState.FILE_UNREADABLE, {}, reason)


def parse_json_document(text: str) -> JsonDocument:
    """Read ``text``, which is a whole JSON file."""
    try:
        loaded = json.loads(
            text.removeprefix(BYTE_ORDER_MARK),
            parse_constant=_refuse,
            object_pairs_hook=JsonObject,
        )
    except _UndefinedNumberError as error:
        return JsonDocument.unparseable(f"the file is not valid JSON: {error} is not a number")
    except json.JSONDecodeError as error:
        return JsonDocument.unparseable(
            f"the file is not valid JSON: {error.msg}, at line {error.lineno} column {error.colno}"
        )
    if not isinstance(loaded, dict):
        return JsonDocument.not_an_object(f"the file is a JSON {_shape(loaded)}, not an object")
    members: dict[str, object] = loaded
    return JsonDocument.parsed(members)


def parse_json_bytes(data: bytes) -> JsonDocument:
    """Read bytes that were observed elsewhere. Bytes that never become text hold no
    document, exactly as an unreadable file does."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return JsonDocument.file_unreadable("the file is not valid UTF-8 text")
    return parse_json_document(text)


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


def own_repeated_names(value: object) -> tuple[str, ...]:
    """The property names ``value``'s own object repeated, counting nothing nested inside it.

    ``value`` is a subtree this module parsed. A mapping built anywhere else carries no record
    of its own repeats and reads as having none.
    """
    return value.repeated_names if isinstance(value, JsonObject) else ()


def repeated_names(value: object) -> tuple[str, ...]:
    """Every property name that repeated in ``value``, or anywhere nested inside it."""
    if isinstance(value, JsonObject):
        return value.repeated_names + _nested(value.values())
    if isinstance(value, dict):
        return _nested(value.values())
    if isinstance(value, list):
        return _nested(value)
    return ()


def _nested(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(name for member in values for name in repeated_names(member))


def _refuse(literal: str) -> object:
    raise _UndefinedNumberError(literal)


def _shape(value: object) -> str:
    return "array" if isinstance(value, list) else "scalar"
