"""Hooks a Skill or a Subagent declares in its own frontmatter.

Where a Markdown file sits says it is a Skill or a Subagent. Only its frontmatter says whether
it is also a hook container, so a file nobody could read declares nothing and is not claimed as
one.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from harness_smith.adapters.claude_code import discover_plugin, discover_repository
from harness_smith.adapters.claude_code.declared import from_frontmatter
from harness_smith.artifacts import (
    ArtifactType,
    ContainerKind,
    Discovery,
    Representation,
    Scope,
)
from harness_smith.frontmatter import Frontmatter, FrontmatterState
from tests.support import write_tree

DECLARATION = (
    '- matcher: "Bash"\n      hooks:\n        - type: command\n          command: "check.sh"\n'
)


def declaring(event: str = "Stop") -> str:
    return f"---\nname: audit\nhooks:\n  {event}:\n    {DECLARATION}---\n\n# audit\n"


SKILL = ".claude/skills/audit/SKILL.md"
AGENT = ".claude/agents/reviewer.md"


def scan(tmp_path: Path, files: Mapping[str, str]) -> Discovery:
    return discover_repository(write_tree(tmp_path / "repository", files))


def codes(discovery: Discovery) -> list[str]:
    return sorted(diagnostic.code for diagnostic in discovery.diagnostics)


def hooks(discovery: Discovery) -> list[str]:
    return sorted(
        artifact.locator
        for artifact in discovery.report.artifacts
        if artifact.type is ArtifactType.HOOK
    )


def carriers(discovery: Discovery, artifact_type: ArtifactType) -> int:
    return len(
        [artifact for artifact in discovery.report.artifacts if artifact.type is artifact_type]
    )


def test_a_skill_declares_the_hooks_its_frontmatter_carries(tmp_path: Path) -> None:
    discovery = scan(tmp_path, {SKILL: declaring()})

    assert hooks(discovery) == [f"{SKILL}#/hooks/Stop/0"]
    (container,) = discovery.report.containers
    assert container.locator == SKILL
    assert container.kind is ContainerKind.SKILL_FRONTMATTER
    assert container.scope is Scope.REPOSITORY
    assert container.settings_layer is None
    assert codes(discovery) == []


def test_a_subagent_declares_its_own(tmp_path: Path) -> None:
    discovery = scan(tmp_path, {AGENT: declaring()})

    assert hooks(discovery) == [f"{AGENT}#/hooks/Stop/0"]
    (container,) = discovery.report.containers
    assert container.kind is ContainerKind.SUBAGENT_FRONTMATTER


def test_a_declared_stop_stays_a_stop(tmp_path: Path) -> None:
    """The runtime turns a subagent's `Stop` into `SubagentStop` when it runs one. That is what
    the runtime does, not what the file says, and this is an inventory of what the file says."""
    discovery = scan(tmp_path, {AGENT: declaring("Stop")})

    assert hooks(discovery) == [f"{AGENT}#/hooks/Stop/0"]
    assert not any("SubagentStop" in locator for locator in hooks(discovery))


def test_a_hook_carries_the_scope_of_the_file_that_declared_it(tmp_path: Path) -> None:
    discovery = discover_plugin(
        write_tree(tmp_path / "plugin", {"skills/audit/SKILL.md": declaring()})
    )

    (hook,) = [
        artifact for artifact in discovery.report.artifacts if artifact.type is ArtifactType.HOOK
    ]
    container = discovery.report.container_of(hook)

    assert hook.scope is Scope.PLUGIN
    assert hook.representation is Representation.CONTAINER_ENTRY
    assert container is not None
    assert container.scope is Scope.PLUGIN
    assert container.kind is ContainerKind.SKILL_FRONTMATTER


def test_a_digest_is_computed_over_the_matcher_group(tmp_path: Path) -> None:
    discovery = scan(tmp_path, {SKILL: declaring()})

    (declaration,) = discovery.hooks

    assert len(declaration.declaration_digest) == 64
    assert declaration.scope is Scope.REPOSITORY


def test_a_file_with_no_hooks_field_is_no_container_and_no_finding(tmp_path: Path) -> None:
    discovery = scan(tmp_path, {SKILL: "---\nname: audit\n---\n\n# audit\n"})

    assert carriers(discovery, ArtifactType.SKILL) == 1
    assert discovery.report.containers == ()
    assert hooks(discovery) == []
    assert codes(discovery) == []


def test_a_file_with_no_frontmatter_at_all_is_prose(tmp_path: Path) -> None:
    discovery = scan(tmp_path, {SKILL: "# audit\n"})

    assert discovery.report.containers == ()
    assert codes(discovery) == []


@pytest.mark.parametrize(
    ("locator", "artifact_type", "code"),
    [
        (SKILL, ArtifactType.SKILL, "HS-SKILL-FRONTMATTER-INVALID"),
        (AGENT, ArtifactType.AGENT, "HS-AGENT-FRONTMATTER-INVALID"),
    ],
)
def test_frontmatter_that_does_not_parse_claims_no_container(
    tmp_path: Path, locator: str, artifact_type: ArtifactType, code: str
) -> None:
    """Nobody has seen a `hooks` field, so nobody may say this file is a hook container."""
    discovery = scan(tmp_path, {locator: "---\nname: [1, 2\n---\n\n# broken\n"})

    assert carriers(discovery, artifact_type) == 1
    assert discovery.report.containers == ()
    assert hooks(discovery) == []
    assert codes(discovery) == [code]


@pytest.mark.parametrize(
    ("locator", "artifact_type", "code"),
    [
        (SKILL, ArtifactType.SKILL, "HS-SKILL-FILE-UNREADABLE"),
        (AGENT, ArtifactType.AGENT, "HS-AGENT-FILE-UNREADABLE"),
    ],
)
def test_a_file_that_cannot_be_read_claims_no_container(
    tmp_path: Path, locator: str, artifact_type: ArtifactType, code: str
) -> None:
    repository = write_tree(tmp_path / "repository", {".claude/rules/keep.md": "# keep\n"})
    unreadable = repository / locator
    unreadable.parent.mkdir(parents=True, exist_ok=True)
    unreadable.write_bytes(b"---\nname: \xff\xfe\n---\n")

    discovery = discover_repository(repository)

    assert carriers(discovery, artifact_type) == 1
    assert discovery.report.containers == ()
    assert hooks(discovery) == []
    assert codes(discovery) == [code]


def test_a_hooks_field_of_the_wrong_shape_is_a_container_holding_nothing(
    tmp_path: Path,
) -> None:
    """Here the file does say it declares hooks, so the container is real and its contents are
    what could not be read."""
    discovery = scan(tmp_path, {SKILL: "---\nname: audit\nhooks: run-everything\n---\n"})

    assert carriers(discovery, ArtifactType.SKILL) == 1
    assert [container.locator for container in discovery.report.containers] == [SKILL]
    assert discovery.report.containers[0].holds == ()
    assert hooks(discovery) == []
    assert codes(discovery) == ["HS-HOOK-CONTAINER-INVALID"]


def test_one_file_is_reported_once(tmp_path: Path) -> None:
    """Artifact discovery owns the file's own failure and the hook scan adds nothing to it."""
    discovery = scan(tmp_path, {SKILL: "---\nname: [1, 2\n---\n"})

    assert len(discovery.diagnostics) == 1


def test_fields_read_out_of_a_block_that_did_not_parse_declare_nothing() -> None:
    """Whatever a half-read block appears to hold, nothing was established by reading it."""
    half_read = Frontmatter(
        FrontmatterState.INVALID, {"hooks": {"Stop": []}}, "the YAML is not a mapping"
    )

    assert from_frontmatter(SKILL, ArtifactType.SKILL, Scope.REPOSITORY, half_read) == (
        from_frontmatter(SKILL, ArtifactType.SKILL, Scope.REPOSITORY, Frontmatter.absent())
    )
