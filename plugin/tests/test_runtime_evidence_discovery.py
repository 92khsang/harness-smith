"""What a runtime evidence snapshot turns into, checked at the envelope a consumer reads.

The scan produces artifacts and containers for Surfaces no offline run reaches, so the checks
here run the whole result document through the schema rather than a fixture written by hand.
A fixture only ever proves that the fixture is valid.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from harness_smith.adapters.claude_code import discover
from harness_smith.artifacts import (
    ArtifactType,
    InventoriedArtifact,
    ManagementAuthority,
    Representation,
    Scope,
    SettingsLayer,
)
from harness_smith.result import OperationResult
from harness_smith.scan import (
    DiscoveryRequest,
    EvidenceCause,
    EvidenceDocument,
    EvidenceKind,
    EvidenceSource,
    EvidenceStatus,
    EvidenceTarget,
    RuntimeEvidenceSnapshot,
)
from harness_smith.vocabulary import Mode
from tests.support import validate_document, write_tree

HOOKS = '{"hooks": {"Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "a"}]}]}}'

SOURCES = {
    EvidenceSource.USER_SETTINGS: (
        Scope.USER_GLOBAL,
        SettingsLayer.USER,
        "~/.claude/settings.json",
    ),
    EvidenceSource.PROJECT_LOCAL_SETTINGS: (
        Scope.REPOSITORY,
        SettingsLayer.PROJECT_LOCAL,
        ".claude/settings.local.json",
    ),
    EvidenceSource.MANAGED_POLICY_BASE: (
        Scope.MANAGED_POLICY,
        SettingsLayer.MANAGED_POLICY,
        "/etc/claude-code/managed-settings.json",
    ),
}


def snapshot(source: EvidenceSource, content: bytes) -> RuntimeEvidenceSnapshot:
    scope, layer, locator = SOURCES[source]
    return RuntimeEvidenceSnapshot(
        requested=(
            EvidenceTarget(
                source=source,
                kind=EvidenceKind.DOCUMENT,
                scope=scope,
                settings_layer=layer,
                locator=locator,
            ),
        ),
        documents=(
            EvidenceDocument(
                source=source,
                scope=scope,
                settings_layer=layer,
                locator=locator,
                status=EvidenceStatus.PRESENT,
                content=content,
            ),
        ),
    )


def audited(tmp_path: Path, source: EvidenceSource, content: bytes) -> dict[str, Any]:
    """The whole envelope a consumer would read, not the part a test remembered to look at."""
    root = write_tree(tmp_path / "repository", {"CLAUDE.md": "# entry point\n"})
    discovery = discover(
        DiscoveryRequest(repository_root=root, runtime_evidence=snapshot(source, content))
    )
    result = OperationResult(
        operation="surface-audit",
        mode=Mode.READ,
        diagnostics=discovery.diagnostics,
        data=discovery.report.as_document(),
    )
    document: dict[str, Any] = result.as_document()
    validate_document(document)
    return document


@pytest.mark.parametrize("source", list(SOURCES))
def test_a_runtime_evidence_envelope_is_schema_valid(
    tmp_path: Path, source: EvidenceSource
) -> None:
    document = audited(tmp_path, source, HOOKS.encode())

    assert len(document["data"]["artifacts"]) == 2


@pytest.mark.parametrize("source", list(SOURCES))
def test_authority_is_held_only_where_mutation_is_conceivable(
    tmp_path: Path, source: EvidenceSource
) -> None:
    """`unknown` is one of the four answers, the one that refuses mutation. Outside repository
    and plugin scope nobody here holds authority at all, which is null."""
    scope = SOURCES[source][0]
    document = audited(tmp_path, source, HOOKS.encode())

    (hook,) = [entry for entry in document["data"]["artifacts"] if entry["type"] == "hook"]

    assert hook["scope"] == scope.value
    assert hook["managementAuthority"] == ("unknown" if scope is Scope.REPOSITORY else None)


def test_an_external_artifact_holds_no_authority() -> None:
    artifact = InventoriedArtifact.runtime_native(
        "somewhere.md", ArtifactType.SKILL, Scope.EXTERNAL, Representation.FILE
    )

    assert artifact.management_authority is None


def test_a_repository_artifact_holds_one(tmp_path: Path) -> None:
    document = audited(tmp_path, EvidenceSource.PROJECT_LOCAL_SETTINGS, HOOKS.encode())

    (entry,) = [item for item in document["data"]["artifacts"] if item["type"] == "entry-point"]

    assert entry["managementAuthority"] == ManagementAuthority.UNKNOWN.value


BROKEN = [
    ("invalid UTF-8", b"\xff\xfe{}", "HS-HOOK-CONTAINER-FILE-UNREADABLE"),
    ("malformed JSON", b"{not json", "HS-HOOK-CONTAINER-UNPARSEABLE"),
    ("a JSON array", b"[]", "HS-HOOK-CONTAINER-INVALID"),
    ("a hooks member of the wrong shape", b'{"hooks": "everything"}', "HS-HOOK-CONTAINER-INVALID"),
    (
        "a repeated member that decides discovery",
        b'{"hooks": {"Stop": []}, "hooks": {"Stop": []}}',
        "HS-HOOK-CONTAINER-INVALID",
    ),
    (
        "a declaration with no canonical form",
        b'{"hooks": {"Stop": [{"command": "\\ud800"}]}}',
        "HS-HOOK-CONTAINER-INVALID",
    ),
]


@pytest.mark.parametrize(("what", "content", "code"), BROKEN, ids=[case[0] for case in BROKEN])
@pytest.mark.parametrize(
    "source", [EvidenceSource.USER_SETTINGS, EvidenceSource.MANAGED_POLICY_BASE]
)
def test_content_the_collector_read_and_this_scan_cannot_is_reported(
    tmp_path: Path, source: EvidenceSource, what: str, content: bytes, code: str
) -> None:
    """The collector handed over the bytes, so the fault is in them and this is the scan that
    can say so. A container holding nothing and no finding would read as a file with no hooks."""
    document = audited(tmp_path, source, content)

    assert [entry["code"] for entry in document["diagnostics"]] == [code], what
    assert [entry["locator"] for entry in document["data"]["containers"]] == [SOURCES[source][2]]
    assert document["data"]["containers"][0]["holds"] == []
    assert [entry for entry in document["data"]["artifacts"] if entry["type"] == "hook"] == []


def test_a_source_the_collector_could_not_read_is_left_to_the_run_that_asked(
    tmp_path: Path,
) -> None:
    """That failure is the collector's to explain and the requesting mode's to project. This
    scan never saw the content and has nothing of its own to add."""
    scope, layer, locator = SOURCES[EvidenceSource.USER_SETTINGS]
    unreadable = RuntimeEvidenceSnapshot(
        requested=(
            EvidenceTarget(
                source=EvidenceSource.USER_SETTINGS,
                kind=EvidenceKind.DOCUMENT,
                scope=scope,
                settings_layer=layer,
                locator=locator,
            ),
        ),
        documents=(
            EvidenceDocument(
                source=EvidenceSource.USER_SETTINGS,
                scope=scope,
                settings_layer=layer,
                locator=locator,
                status=EvidenceStatus.UNREADABLE,
                cause=EvidenceCause.PERMISSION_DENIED,
            ),
        ),
    )
    root = write_tree(tmp_path / "repository", {"CLAUDE.md": "# entry point\n"})

    discovery = discover(DiscoveryRequest(repository_root=root, runtime_evidence=unreadable))

    assert [container.locator for container in discovery.report.containers] == [locator]
    assert discovery.diagnostics == ()
