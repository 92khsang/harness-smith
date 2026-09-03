"""What one scan reads, and what it refuses to read.

A scan reads the roots its request names and the runtime evidence its request carries. It does
not consult the ambient environment, so an offline run's answer does not turn on the machine it
ran on, and a fixture is a real substitute for one.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from harness_smith.adapters.claude_code import discover
from harness_smith.artifacts import (
    Activation,
    ActivationCause,
    ArtifactType,
    Scope,
    SettingsLayer,
)
from harness_smith.scan import (
    DiscoveryRequest,
    EvidenceDirectory,
    EvidenceDocument,
    EvidenceKind,
    EvidenceSource,
    EvidenceStatus,
    EvidenceTarget,
    RuntimeEvidenceSnapshot,
)
from tests.support import write_tree

SETTINGS = '{"hooks": {"Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "a"}]}]}}'


@pytest.fixture
def machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A machine whose global locations are full of hooks a scan must not reach for."""
    home = write_tree(tmp_path / "home", {".claude/settings.json": SETTINGS})
    policy = write_tree(
        tmp_path / "policy",
        {
            "claude-code/managed-settings.json": SETTINGS,
            "claude-code/managed-settings.d/10-security.json": SETTINGS,
        },
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude"))
    monkeypatch.chdir(policy)
    yield policy


def report(root: Path, **changes: object) -> list[str]:
    request = DiscoveryRequest(repository_root=root, **changes)  # type: ignore[arg-type]
    discovery = discover(request)
    return [artifact.locator for artifact in discovery.report.artifacts]


def repository(tmp_path: Path) -> Path:
    return write_tree(
        tmp_path / "repository", {"CLAUDE.md": "# entry point\n", ".claude/settings.json": SETTINGS}
    )


def test_a_request_without_runtime_evidence_reads_no_machine_global_location(
    tmp_path: Path, machine: Path
) -> None:
    """The user's settings and the system policy are full of hooks. None of them is this
    repository's, and an offline scan never looks."""
    found = report(repository(tmp_path))

    assert found == ["CLAUDE.md", ".claude/settings.json#/hooks/Stop/0"]
    assert not any(str(machine) in locator for locator in found)
    assert os.environ["HOME"] != str(tmp_path)


def test_the_same_repository_answers_the_same_whatever_the_machine_holds(
    tmp_path: Path, machine: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repository(tmp_path)
    before = report(root)

    monkeypatch.setenv("HOME", str(tmp_path / "somewhere-else"))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")

    assert report(root) == before


def test_an_empty_snapshot_is_not_the_same_request_as_no_snapshot(tmp_path: Path) -> None:
    """A collected snapshot that found nothing and a run that never asked are different
    requests, whatever they currently produce."""
    root = repository(tmp_path)
    asked = DiscoveryRequest(repository_root=root, runtime_evidence=RuntimeEvidenceSnapshot())
    never = DiscoveryRequest(repository_root=root)

    assert asked != never
    assert discover(asked).report.as_document() == discover(never).report.as_document()


def test_a_named_plugin_root_is_scanned_and_an_unnamed_one_is_not(tmp_path: Path) -> None:
    root = write_tree(
        tmp_path / "repository",
        {
            "CLAUDE.md": "# entry point\n",
            "product/skills/audit/SKILL.md": "---\nname: audit\n---\n",
            "vendor/skills/other/SKILL.md": "---\nname: other\n---\n",
        },
    )

    found = report(root, plugin_roots=(root / "product",))

    assert "skills/audit/SKILL.md" in found
    assert "skills/other/SKILL.md" not in found


def test_a_plugin_artifact_keeps_its_own_scope_in_the_composed_report(tmp_path: Path) -> None:
    root = write_tree(
        tmp_path / "repository",
        {
            ".claude/skills/audit/SKILL.md": "---\nname: audit\n---\n",
            "product/skills/audit/SKILL.md": "---\nname: audit\n---\n",
        },
    )

    discovery = discover(DiscoveryRequest(repository_root=root, plugin_roots=(root / "product",)))
    scopes = {
        (artifact.locator, artifact.scope.value)
        for artifact in discovery.report.artifacts
        if artifact.type is ArtifactType.SKILL
    }

    assert scopes == {
        (".claude/skills/audit/SKILL.md", "repository"),
        ("skills/audit/SKILL.md", "plugin"),
    }


USER_LOCATOR = "~/.claude/settings.json"


def user_target(locator: str) -> EvidenceTarget:
    return EvidenceTarget(
        source=EvidenceSource.USER_SETTINGS,
        kind=EvidenceKind.DOCUMENT,
        scope=Scope.USER_GLOBAL,
        settings_layer=SettingsLayer.USER,
        locator=locator,
    )


def user_document(locator: str, content: bytes) -> EvidenceDocument:
    return EvidenceDocument(
        source=EvidenceSource.USER_SETTINGS,
        scope=Scope.USER_GLOBAL,
        settings_layer=SettingsLayer.USER,
        locator=locator,
        status=EvidenceStatus.PRESENT,
        content=content,
    )


def collected(content: bytes, locator: str = USER_LOCATOR) -> RuntimeEvidenceSnapshot:
    """What a collector observed for the user's own settings, and nothing more."""
    return RuntimeEvidenceSnapshot(
        requested=(user_target(locator),), documents=(user_document(locator, content),)
    )


def test_one_snapshot_answers_the_same_on_any_machine(
    tmp_path: Path, machine: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The snapshot is the evidence. What the machine holds around it is not."""
    root = repository(tmp_path)
    snapshot = collected(SETTINGS.encode())
    before = discover(
        DiscoveryRequest(repository_root=root, runtime_evidence=snapshot)
    ).report.as_document()

    monkeypatch.setenv("HOME", str(tmp_path / "elsewhere"))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")

    assert (
        discover(
            DiscoveryRequest(repository_root=root, runtime_evidence=snapshot)
        ).report.as_document()
        == before
    )


def test_a_source_that_changed_after_it_was_observed_does_not_change_the_report(
    tmp_path: Path,
) -> None:
    """The collector observed one moment. Reopening the Locator would let the report describe
    two, and there is no moment at which both were true."""
    root = repository(tmp_path)
    observed = tmp_path / "observed-settings.json"
    observed.write_text(SETTINGS, encoding="utf-8")
    snapshot = collected(observed.read_bytes(), str(observed))
    request = DiscoveryRequest(repository_root=root, runtime_evidence=snapshot)
    before = discover(request).report.as_document()

    observed.unlink()

    assert discover(request).report.as_document() == before
    assert [entry.locator for entry in discover(request).report.containers] == [
        ".claude/settings.json",
        str(observed),
    ]


def test_an_observed_hook_keeps_the_scope_and_layer_it_was_observed_in(tmp_path: Path) -> None:
    discovery = discover(
        DiscoveryRequest(
            repository_root=repository(tmp_path), runtime_evidence=collected(SETTINGS.encode())
        )
    )
    container = next(
        entry for entry in discovery.report.containers if entry.locator == USER_LOCATOR
    )
    hook = next(
        artifact
        for artifact in discovery.report.artifacts
        if artifact.type is ArtifactType.HOOK and artifact.scope is Scope.USER_GLOBAL
    )

    assert container.settings_layer is SettingsLayer.USER
    assert container.holds == (hook.locator,)
    assert hook.locator == f"{USER_LOCATOR}#/hooks/Stop/0"


MANAGED_BASE = "/etc/claude-code/managed-settings.json"
MANAGED_DROPINS = "/etc/claude-code/managed-settings.d"


def policy_target(source: EvidenceSource, kind: EvidenceKind, locator: str) -> EvidenceTarget:
    return EvidenceTarget(
        source=source,
        kind=kind,
        scope=Scope.MANAGED_POLICY,
        settings_layer=SettingsLayer.MANAGED_POLICY,
        locator=locator,
    )


def policy_document(source: EvidenceSource, locator: str) -> EvidenceDocument:
    return EvidenceDocument(
        source=source,
        scope=Scope.MANAGED_POLICY,
        settings_layer=SettingsLayer.MANAGED_POLICY,
        locator=locator,
        status=EvidenceStatus.PRESENT,
        content=SETTINGS.encode(),
    )


def policy_snapshot() -> RuntimeEvidenceSnapshot:
    """A base file and one drop-in beside it, which is how an administrator splits a policy."""
    dropin = f"{MANAGED_DROPINS}/10-security.json"
    return RuntimeEvidenceSnapshot(
        requested=(
            policy_target(EvidenceSource.MANAGED_POLICY_BASE, EvidenceKind.DOCUMENT, MANAGED_BASE),
            policy_target(
                EvidenceSource.MANAGED_POLICY_DROPIN_DIRECTORY,
                EvidenceKind.DIRECTORY,
                MANAGED_DROPINS,
            ),
        ),
        documents=(
            policy_document(EvidenceSource.MANAGED_POLICY_BASE, MANAGED_BASE),
            policy_document(EvidenceSource.MANAGED_POLICY_DROPIN, dropin),
        ),
        directories=(
            EvidenceDirectory(
                source=EvidenceSource.MANAGED_POLICY_DROPIN_DIRECTORY,
                scope=Scope.MANAGED_POLICY,
                settings_layer=SettingsLayer.MANAGED_POLICY,
                locator=MANAGED_DROPINS,
                status=EvidenceStatus.PRESENT,
                entries=(dropin,),
            ),
        ),
    )


def test_a_policy_base_file_and_each_drop_in_stay_separate_containers(tmp_path: Path) -> None:
    """A declaration keeps the file it came from. Merging them into one virtual container would
    lose which administrator's file said what, and the merge order is a projection made
    elsewhere."""
    discovery = discover(
        DiscoveryRequest(repository_root=repository(tmp_path), runtime_evidence=policy_snapshot())
    )

    policy = [
        container
        for container in discovery.report.containers
        if container.scope is Scope.MANAGED_POLICY
    ]

    assert [container.locator for container in policy] == [
        MANAGED_BASE,
        f"{MANAGED_DROPINS}/10-security.json",
    ]
    assert all(container.holds for container in policy)


def test_a_policy_hook_is_inventoried_without_being_called_effective(tmp_path: Path) -> None:
    """The managed tier picks one of four ranked sources and a helper can replace the lot, so a
    readable file says what it declares and nothing about what is in force. The raw artifact
    stays: an activation projection is what decides unknown, not a missing artifact."""
    discovery = discover(
        DiscoveryRequest(repository_root=repository(tmp_path), runtime_evidence=policy_snapshot())
    )

    hooks = [
        artifact
        for artifact in discovery.report.artifacts
        if artifact.scope is Scope.MANAGED_POLICY
    ]

    assert len(hooks) == 2
    assert {artifact.activation for artifact in hooks} == {Activation.UNKNOWN}
    assert {artifact.activation_cause for artifact in hooks} == {
        ActivationCause.RUNTIME_STATE_NOT_READ
    }


def test_a_policy_hook_is_held_by_the_file_it_was_declared_in(tmp_path: Path) -> None:
    discovery = discover(
        DiscoveryRequest(repository_root=repository(tmp_path), runtime_evidence=policy_snapshot())
    )

    held = {
        artifact.locator: discovery.report.container_of(artifact)
        for artifact in discovery.report.artifacts
        if artifact.scope is Scope.MANAGED_POLICY
    }

    assert {
        locator: container.locator for locator, container in held.items() if container is not None
    } == {
        f"{MANAGED_BASE}#/hooks/Stop/0": MANAGED_BASE,
        f"{MANAGED_DROPINS}/10-security.json#/hooks/Stop/0": (
            f"{MANAGED_DROPINS}/10-security.json"
        ),
    }
