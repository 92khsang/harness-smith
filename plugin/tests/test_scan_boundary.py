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
from harness_smith.artifacts import ArtifactType
from harness_smith.scan import DiscoveryRequest, RuntimeEvidenceSnapshot
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
