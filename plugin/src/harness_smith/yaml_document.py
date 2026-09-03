"""Reading a whole YAML file's text.

The governance manifest is hand-edited YAML, so the two failures a text that is already in
hand can have are kept apart: the text is not YAML, or the YAML is not a mapping and so holds
no keys to read. A caller chooses on the state rather than by reading the reason. Whether
there was a file to read at all is answered by ``text_file``, in the open that read it.

A repeated key is refused by the parser rather than resolved. YAML 1.2 leaves a duplicate to
the implementation, and which of two same-named keys survives decides what a manifest says
about a path, so it is reported instead of silently taking one.

The schema is YAML 1.2 core, the same decision the frontmatter reader records: only ``true``
and ``false`` are booleans, and a tag naming a Python object is refused rather than constructed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from ruamel.yaml import YAML
from ruamel.yaml.error import MarkedYAMLError, YAMLError

__all__ = [
    "YamlDocument",
    "YamlDocumentState",
    "parse_yaml_document",
]

BYTE_ORDER_MARK = "﻿"


class YamlDocumentState(StrEnum):
    PARSED = "parsed"
    UNPARSEABLE = "unparseable"
    NOT_A_MAPPING = "not-a-mapping"


@dataclass(frozen=True)
class YamlDocument:
    """A YAML file's keys, or the reason there are none to read."""

    state: YamlDocumentState
    members: Mapping[str, object]
    reason: str

    @classmethod
    def parsed(cls, members: Mapping[str, object]) -> YamlDocument:
        return cls(YamlDocumentState.PARSED, members, "")

    @classmethod
    def unparseable(cls, reason: str) -> YamlDocument:
        return cls(YamlDocumentState.UNPARSEABLE, {}, reason)

    @classmethod
    def not_a_mapping(cls, reason: str) -> YamlDocument:
        return cls(YamlDocumentState.NOT_A_MAPPING, {}, reason)


def parse_yaml_document(text: str) -> YamlDocument:
    """Read ``text``, which is a whole YAML file."""
    try:
        loaded = _parser().load(text.removeprefix(BYTE_ORDER_MARK))
    except YAMLError as error:
        return YamlDocument.unparseable(f"the file is not valid YAML: {_reason(error)}")
    if loaded is None:
        return YamlDocument.parsed({})
    if not isinstance(loaded, dict):
        return YamlDocument.not_a_mapping(f"the file is a YAML {_shape(loaded)}, not a mapping")
    unnamed = [key for key in loaded if not isinstance(key, str)]
    if unnamed:
        return YamlDocument.not_a_mapping(f"the file has a key that is not text: {unnamed[0]!r}")
    members: dict[str, object] = dict(loaded)
    return YamlDocument.parsed(members)


def _parser() -> YAML:
    parser = YAML(typ="safe")
    parser.allow_duplicate_keys = False
    return parser


def _shape(value: object) -> str:
    return "sequence" if isinstance(value, list) else "scalar"


def _reason(error: YAMLError) -> str:
    detail = str(error).splitlines()[0].strip()
    where = ""
    if isinstance(error, MarkedYAMLError):
        if error.problem is not None:
            detail = error.problem.strip()
        if error.problem_mark is not None:
            where = (
                f", at line {error.problem_mark.line + 1} column {error.problem_mark.column + 1}"
            )
    return f"{detail}{where}"
