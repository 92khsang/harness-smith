"""Reading a Markdown file's YAML frontmatter.

The block is parsed, never scanned. A line or regex scanner reads a block scalar's indented
content as more fields, loses a quoted colon, and cannot tell a flow sequence from a string,
so the parser is the contract rather than an implementation detail.

The schema is YAML 1.2 core, which is this project's decision: the runtime strips frontmatter
before injecting a rule, and harness-smith reads the keys from disk with its own parser
(ADR-0006). Under 1.2 only ``true`` and ``false`` are booleans, and ``yes``, ``no``, ``on``
and ``off`` are text. The loader is the safe one, so a tag naming a Python object is refused
rather than constructed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import MarkedYAMLError, YAMLError

__all__ = ["Frontmatter", "FrontmatterState", "read_frontmatter", "read_frontmatter_file"]

DELIMITER = "---"
BYTE_ORDER_MARK = "\ufeff"

# The block's first line is the file's second, so a mark inside the block is offset by the
# opening delimiter to give the reader a line number they can go to.
BLOCK_LINE_OFFSET = 2


class FrontmatterState(StrEnum):
    ABSENT = "absent"
    PARSED = "parsed"
    UNREADABLE = "unreadable"


@dataclass(frozen=True)
class Frontmatter:
    """A file's frontmatter block: absent, parsed into fields, or unreadable with a reason."""

    state: FrontmatterState
    fields: Mapping[str, object]
    reason: str

    @classmethod
    def absent(cls) -> Frontmatter:
        return cls(FrontmatterState.ABSENT, {}, "")

    @classmethod
    def parsed(cls, fields: Mapping[str, object]) -> Frontmatter:
        return cls(FrontmatterState.PARSED, fields, "")

    @classmethod
    def unreadable(cls, reason: str) -> Frontmatter:
        return cls(FrontmatterState.UNREADABLE, {}, reason)


def read_frontmatter(text: str) -> Frontmatter:
    """Read the frontmatter block of ``text``, which is a whole Markdown file."""
    lines = text.removeprefix(BYTE_ORDER_MARK).split("\n")
    if not _is_delimiter(lines[0]):
        return Frontmatter.absent()
    for index in range(1, len(lines)):
        if _is_delimiter(lines[index]):
            # Every line of the block keeps its own terminator: a block scalar's final newline
            # belongs to its value, and dropping it would change what the field says.
            return _parse("".join(f"{line}\n" for line in lines[1:index]))
    return Frontmatter.unreadable("the frontmatter block opens with --- and is never closed")


def read_frontmatter_file(path: Path) -> Frontmatter:
    """Read ``path``'s frontmatter. A file that cannot be read at all has no readable block.

    No reason names the path: a diagnostic carries the Locator in its subject, and messages
    stay free of absolute paths.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return Frontmatter.unreadable("the file is not valid UTF-8 text")
    except OSError as error:
        return Frontmatter.unreadable(
            f"the file could not be read: {error.strerror or 'unknown error'}"
        )
    return read_frontmatter(text)


def _is_delimiter(line: str) -> bool:
    return line.rstrip() == DELIMITER


def _parser() -> YAML:
    parser = YAML(typ="safe")
    parser.allow_duplicate_keys = False
    return parser


def _parse(block: str) -> Frontmatter:
    try:
        loaded = _parser().load(block)
    except YAMLError as error:
        return Frontmatter.unreadable(_yaml_reason(error))
    if loaded is None:
        return Frontmatter.parsed({})
    if not isinstance(loaded, dict):
        return Frontmatter.unreadable(
            f"the frontmatter is a YAML {_shape(loaded)}, not a mapping of fields"
        )
    unnamed = [key for key in loaded if not isinstance(key, str)]
    if unnamed:
        return Frontmatter.unreadable(
            f"the frontmatter has a field name that is not text: {unnamed[0]!r}"
        )
    fields: dict[str, object] = dict(loaded)
    return Frontmatter.parsed(fields)


def _shape(value: object) -> str:
    return "sequence" if isinstance(value, list) else "scalar"


def _yaml_reason(error: YAMLError) -> str:
    detail = str(error).splitlines()[0].strip()
    where = ""
    if isinstance(error, MarkedYAMLError):
        if error.problem is not None:
            detail = error.problem.strip()
        if error.problem_mark is not None:
            line = error.problem_mark.line + BLOCK_LINE_OFFSET
            where = f", at line {line} column {error.problem_mark.column + 1}"
    return f"the frontmatter is not valid YAML: {detail}{where}"
