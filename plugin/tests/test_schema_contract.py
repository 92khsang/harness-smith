"""The result schema and the implementation must name the same vocabulary."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

import jsonschema
import pytest

from harness_smith.artifacts import (
    Activation,
    ActivationCause,
    ArtifactType,
    CapabilityValue,
    ContainerFormat,
    GovernanceSet,
    ManagementAuthority,
    Provenance,
    Representation,
    Scope,
)
from harness_smith.diagnostics import DIAGNOSTIC_REGISTRY
from harness_smith.operations import DECLARED_OPERATIONS
from harness_smith.result import ChangeAction, PatchFormat
from harness_smith.vocabulary import Mode, Severity, Status, SubjectKind
from tests.support import schema, validate_document

CODE_SHAPE = re.compile(r"^HS-[A-Z0-9]+(-[A-Z0-9]+)*$")


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
        ("$defs/capabilityValue/enum", [member.value for member in CapabilityValue]),
        (
            "$defs/artifactContainer/properties/format/enum",
            [member.value for member in ContainerFormat],
        ),
        (
            "$defs/inventoriedArtifact/properties/type/enum",
            [member.value for member in ArtifactType],
        ),
        (
            "$defs/inventoriedArtifact/properties/scope/enum",
            [member.value for member in Scope],
        ),
        (
            "$defs/runtimeComponentObservation/properties/scope/enum",
            [member.value for member in Scope],
        ),
        (
            "$defs/artifactContainer/properties/scope/enum",
            [member.value for member in Scope],
        ),
        (
            "$defs/inventoriedArtifact/properties/representation/enum",
            [member.value for member in Representation],
        ),
        (
            "$defs/inventoriedArtifact/properties/provenance/enum",
            [member.value for member in Provenance],
        ),
        (
            "$defs/inventoriedArtifact/properties/activation/enum",
            [member.value for member in Activation],
        ),
        (
            "$defs/inventoriedArtifact/properties/activationCause/oneOf/0/enum",
            [member.value for member in ActivationCause],
        ),
        ("$defs/managementAuthority/enum", [member.value for member in ManagementAuthority]),
        ("$defs/governanceSet/enum", [member.value for member in GovernanceSet]),
    ],
)
def test_schema_enums_match_the_implementation(pointer: str, expected: list[str]) -> None:
    assert enum_at(pointer) == expected


def test_the_diagnostic_vocabulary_is_closed_and_matches_the_registry() -> None:
    """A code the registry does not carry is a schema error, not merely a badly shaped one.
    This is the parity check: an addition or an omission on either side fails here."""
    assert enum_at("$defs/diagnosticCode/enum") == sorted(DIAGNOSTIC_REGISTRY)


def test_every_registered_diagnostic_code_follows_the_naming_shape() -> None:
    unmatched = [code for code in DIAGNOSTIC_REGISTRY if not CODE_SHAPE.fullmatch(code)]

    assert unmatched == []


def test_the_schema_rejects_a_code_the_registry_does_not_carry() -> None:
    document = deepcopy(POPULATED_SURFACE_AUDIT)
    document["diagnostics"][0]["code"] = "HS-NOT-A-REAL-CODE"

    with pytest.raises(jsonschema.ValidationError):
        validate_document(document)


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


POPULATED_SURFACE_AUDIT: dict[str, Any] = {
    "schemaVersion": 1,
    "operation": "surface-audit",
    "mode": "read",
    "status": "ok",
    "diagnostics": [
        {
            "code": "HS-EFFECTIVE-HARNESS-UNCERTAIN",
            "severity": "warning",
            "subject": {"kind": "surface", "locator": ".claude/settings.json"},
            "message": "the managed policy could not be read",
            "cause": "managed-policy-uninspectable",
            "affected": [".claude/settings.json#/hooks/PreToolUse/0"],
            "remediation": "Supply the missing evidence, or accept the uncertainty",
        }
    ],
    "changes": [],
    "data": {
        "artifacts": [
            {
                "locator": "CLAUDE.md",
                "type": "entry-point",
                "scope": "repository",
                "representation": "file",
                "provenance": "authored",
                "managementAuthority": "local",
                "activation": "active",
                "activationCause": None,
                "harnessRelevant": True,
                "sets": ["inventoried", "governed", "managed", "governed-harness"],
            }
        ],
        "containers": [
            {
                "locator": ".claude/settings.json",
                "format": "json",
                "scope": "repository",
                "holds": [".claude/settings.json#/hooks/PreToolUse/0"],
            }
        ],
        "observations": [
            {
                "locator": ".mcp.json",
                "component": "mcp-server",
                "scope": "external",
                "capabilities": {
                    "inventory": "managed",
                    "structuralCheck": "observed-only",
                    "lifecycleAdvice": "observed-only",
                    "mutation": "unsupported",
                },
            }
        ],
    },
}


def test_a_populated_surface_audit_document_is_schema_valid() -> None:
    validate_document(POPULATED_SURFACE_AUDIT)


def mutated(**changes: Any) -> dict[str, Any]:
    document = deepcopy(POPULATED_SURFACE_AUDIT)
    document.update(changes)
    return document


def test_the_schema_rejects_an_unrecognised_top_level_key() -> None:
    with pytest.raises(jsonschema.ValidationError):
        validate_document(mutated(elapsedSeconds=0.4))


def test_the_schema_rejects_an_unrecognised_key_inside_an_artifact() -> None:
    document = deepcopy(POPULATED_SURFACE_AUDIT)
    document["data"]["artifacts"][0]["owner"] = "someone"

    with pytest.raises(jsonschema.ValidationError):
        validate_document(document)


def test_the_schema_rejects_a_change_on_a_read_operation() -> None:
    change = {
        "path": "CLAUDE.md",
        "action": "update",
        "digestBefore": "before",
        "digestAfter": "after",
        "applied": False,
        "patch": {"format": "unified", "content": "--- a\n+++ b\n"},
    }

    with pytest.raises(jsonschema.ValidationError):
        validate_document(mutated(changes=[change]))


def test_the_schema_rejects_data_on_a_run_that_identified_no_operation() -> None:
    with pytest.raises(jsonschema.ValidationError):
        validate_document(mutated(operation=None, status="usage-error"))


def test_the_schema_rejects_a_created_file_that_claims_a_previous_digest() -> None:
    change = {
        "path": "CLAUDE.md",
        "action": "create",
        "digestBefore": "before",
        "digestAfter": "after",
        "applied": True,
        "patch": {"format": "unified", "content": "--- a\n+++ b\n"},
    }

    with pytest.raises(jsonschema.ValidationError):
        validate_document(mutated(mode="apply", changes=[change]))


def test_the_schema_rejects_an_artifact_type_outside_the_taxonomy() -> None:
    document = deepcopy(POPULATED_SURFACE_AUDIT)
    document["data"]["artifacts"][0]["type"] = "workflow"

    with pytest.raises(jsonschema.ValidationError):
        validate_document(document)


def with_artifact(**changes: Any) -> dict[str, Any]:
    document = deepcopy(POPULATED_SURFACE_AUDIT)
    document["data"]["artifacts"][0].update(changes)
    return document


def test_management_authority_keeps_its_four_values() -> None:
    assert enum_at("$defs/managementAuthority/enum") == [
        "local",
        "harness-smith",
        "external-plugin",
        "unknown",
    ]


@pytest.mark.parametrize("scope", ["repository", "plugin"])
def test_authority_applies_where_mutation_is_conceivable(scope: str) -> None:
    """Inside repository and plugin scope authority always has one of the four values.
    Unresolved is `unknown`, which refuses mutation; null would say the question does not
    arise, and that is a different claim."""
    validate_document(with_artifact(scope=scope, managementAuthority="unknown"))

    with pytest.raises(jsonschema.ValidationError):
        validate_document(with_artifact(scope=scope, managementAuthority=None))


@pytest.mark.parametrize("scope", ["user-global", "external"])
def test_authority_does_not_apply_outside_repository_and_plugin_scope(scope: str) -> None:
    """Outside them there is no authority to hold, which is null rather than a fifth value."""
    validate_document(with_artifact(scope=scope, managementAuthority=None))

    with pytest.raises(jsonschema.ValidationError):
        validate_document(with_artifact(scope=scope, managementAuthority="local"))


def test_the_governance_sets_are_a_closed_vocabulary() -> None:
    with pytest.raises(jsonschema.ValidationError):
        validate_document(with_artifact(sets=["inventoried", "govrened"]))


def test_a_governance_set_is_named_at_most_once() -> None:
    with pytest.raises(jsonschema.ValidationError):
        validate_document(with_artifact(sets=["inventoried", "inventoried"]))


def test_every_inventoried_artifact_says_it_is_inventoried() -> None:
    """An entry of the Artifact Inventory is an Inventoried Artifact by definition, so the set
    is not one a report may leave off."""
    validate_document(with_artifact(sets=["inventoried"]))

    with pytest.raises(jsonschema.ValidationError):
        validate_document(with_artifact(sets=[]))

    with pytest.raises(jsonschema.ValidationError):
        validate_document(with_artifact(sets=["governed"]))


def test_the_schema_rejects_an_authority_outside_the_four_values() -> None:
    with pytest.raises(jsonschema.ValidationError):
        validate_document(with_artifact(managementAuthority="not-applicable"))
