"""Unit tests for the result envelope: ordering, status resolution, and the code registry."""

from __future__ import annotations

import pytest

from harness_smith.diagnostics import (
    DIAGNOSTIC_REGISTRY,
    Diagnostic,
    Severity,
    Subject,
    SubjectKind,
)
from harness_smith.result import (
    Change,
    ChangeAction,
    Mode,
    OperationResult,
    Patch,
    PatchFormat,
    Status,
    resolve_status,
)
from tests.support import validate_document


def diagnostic(code: str, locator: str | None = None) -> Diagnostic:
    return Diagnostic.of(code, Subject(SubjectKind.ARTIFACT, locator), message=code)


def test_every_registered_code_carries_a_remediation() -> None:
    assert DIAGNOSTIC_REGISTRY
    for spec in DIAGNOSTIC_REGISTRY.values():
        assert spec.remediation.strip()


def test_an_unregistered_code_cannot_be_emitted() -> None:
    with pytest.raises(KeyError):
        diagnostic("HS-NOT-A-REAL-CODE")


def test_a_diagnostic_takes_its_severity_and_remediation_from_the_registry() -> None:
    entry = diagnostic("HS-CLI-USAGE").as_document()

    assert entry["severity"] == Severity.ERROR
    assert entry["remediation"] == DIAGNOSTIC_REGISTRY["HS-CLI-USAGE"].remediation


def test_diagnostics_are_sorted_by_severity_descending_then_code_then_subject() -> None:
    result = OperationResult(
        operation=None,
        mode=Mode.READ,
        diagnostics=(
            diagnostic("HS-HOOK-RELOCATED", "b"),
            diagnostic("HS-CLI-USAGE", "b"),
            diagnostic("HS-CLI-USAGE", "a"),
            diagnostic("HS-ENFORCEMENT-ORPHAN", "a"),
        ),
    )

    diagnostics = result.as_document()["diagnostics"]

    assert isinstance(diagnostics, list)
    ordered = [(entry["code"], entry["subject"]["locator"]) for entry in diagnostics]

    assert ordered == [
        ("HS-CLI-USAGE", "a"),
        ("HS-CLI-USAGE", "b"),
        ("HS-ENFORCEMENT-ORPHAN", "a"),
        ("HS-HOOK-RELOCATED", "b"),
    ]


def test_status_is_ok_when_nothing_is_reported() -> None:
    assert resolve_status(()) is Status.OK


def test_a_usage_error_outranks_every_other_outcome() -> None:
    status = resolve_status((diagnostic("HS-ENFORCEMENT-ORPHAN"), diagnostic("HS-CLI-USAGE")))

    assert status is Status.USAGE_ERROR


def test_an_environment_failure_outranks_a_policy_violation() -> None:
    status = resolve_status(
        (diagnostic("HS-PLACEMENT-INVALID"), diagnostic("HS-PACKAGE-VALIDATOR-UNAVAILABLE"))
    )

    assert status is Status.ENVIRONMENT_ERROR


def test_a_warning_alone_does_not_raise_the_status() -> None:
    assert resolve_status((diagnostic("HS-ENFORCEMENT-ORPHAN"),)) is Status.OK


def a_change(path: str) -> Change:
    return Change(
        path=path,
        action=ChangeAction.UPDATE,
        patch=Patch(PatchFormat.UNIFIED, "--- a\n+++ b\n"),
        digest_before="before",
        digest_after="after",
    )


def test_changes_are_sorted_by_path() -> None:
    result = OperationResult(
        operation="config-gc", mode=Mode.PLAN, changes=(a_change("b.md"), a_change("a.md"))
    )

    changes = result.as_document()["changes"]

    assert isinstance(changes, list)
    assert [entry["path"] for entry in changes] == ["a.md", "b.md"]


def test_a_planned_change_carries_the_patch_that_produced_it_and_is_not_applied() -> None:
    document = OperationResult(
        operation="config-gc", mode=Mode.PLAN, changes=(a_change("a.md"),)
    ).as_document()

    validate_document(document)

    changes = document["changes"]
    assert isinstance(changes, list)
    assert changes[0]["applied"] is False
    assert changes[0]["patch"] == {"format": "unified", "content": "--- a\n+++ b\n"}
