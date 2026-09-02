"""The result schema and the implementation must name the same vocabulary."""

from __future__ import annotations

from typing import Any

import pytest

from harness_smith.diagnostics import DIAGNOSTIC_REGISTRY
from harness_smith.envelope import Mode, Severity, Status, SubjectKind
from harness_smith.operations import DECLARED_OPERATIONS
from harness_smith.result import ChangeAction, PatchFormat
from tests.support import schema

CAPABILITY_VALUES = ["managed", "observed-only", "unsupported"]


def enum_at(pointer: str) -> list[str]:
    node: Any = schema()
    for segment in pointer.split("/"):
        node = node[int(segment)] if segment.isdigit() else node[segment]
    values: list[str] = node
    return values


def test_the_operation_enum_is_the_declared_operation_vocabulary() -> None:
    assert enum_at("properties/operation/oneOf/0/enum") == list(DECLARED_OPERATIONS)


@pytest.mark.parametrize(
    ("pointer", "expected"),
    [
        ("properties/mode/enum", [member.value for member in Mode]),
        ("properties/status/enum", [member.value for member in Status]),
        ("$defs/diagnostic/properties/severity/enum", [member.value for member in Severity]),
        ("$defs/subject/properties/kind/enum", [member.value for member in SubjectKind]),
        ("$defs/change/properties/action/enum", [member.value for member in ChangeAction]),
        ("$defs/patch/properties/format/enum", [member.value for member in PatchFormat]),
        ("$defs/capabilityValue/enum", CAPABILITY_VALUES),
    ],
)
def test_schema_enums_match_the_implementation(pointer: str, expected: list[str]) -> None:
    assert enum_at(pointer) == expected


def test_every_registered_diagnostic_code_matches_the_schema_pattern() -> None:
    import re

    pattern = re.compile(schema()["$defs"]["diagnosticCode"]["pattern"])

    unmatched = [code for code in DIAGNOSTIC_REGISTRY if not pattern.fullmatch(code)]

    assert unmatched == []


def _object_schemas(node: object, path: str = "") -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(node, dict):
        if "properties" in node and node.get("type") in {"object", None}:
            found.append((path, node))
        for key, value in node.items():
            found.extend(_object_schemas(value, f"{path}/{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_object_schemas(value, f"{path}/{index}"))
    return found


def test_no_object_in_the_schema_accepts_unrecognised_keys() -> None:
    """An unrecognised key is a schema error rather than something silently ignored."""
    permissive = [
        path
        for path, node in _object_schemas(schema())
        if "/if" not in path
        and "/then" not in path
        and node.get("additionalProperties") is not False
    ]

    assert permissive == []
