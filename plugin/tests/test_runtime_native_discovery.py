"""Runtime-native structural discovery, at the adapter's own contract.

These are the locations the Claude Code runtime itself defines and loads from. The adapter
promises no compatibility to anything outside the package, so it is tested directly rather
than only through a golden document.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from harness_smith.adapters import claude_code
from harness_smith.artifacts import (
    Activation,
    ActivationCause,
    ArtifactType,
    ContainerFormat,
    Discovery,
    GovernanceSet,
    InventoriedArtifact,
    ManagementAuthority,
    Provenance,
    Representation,
    Scope,
)
from tests.support import write_tree


def scan(tmp_path: Path, files: Mapping[str, str]) -> Discovery:
    return claude_code.discover(write_tree(tmp_path / "repository", files))


def locators(discovery: Discovery, artifact_type: ArtifactType | None = None) -> list[str]:
    return [
        artifact.locator
        for artifact in discovery.report.artifacts
        if artifact_type is None or artifact.type is artifact_type
    ]


def codes(discovery: Discovery) -> list[str]:
    return [diagnostic.code for diagnostic in discovery.diagnostics]


def only(discovery: Discovery, artifact_type: ArtifactType) -> InventoriedArtifact:
    matching = [
        artifact for artifact in discovery.report.artifacts if artifact.type is artifact_type
    ]
    assert len(matching) == 1, f"expected one {artifact_type}, found {matching}"
    return matching[0]


def test_a_repository_with_no_runtime_locations_discovers_nothing(tmp_path: Path) -> None:
    discovery = scan(tmp_path, {"README.md": "# readme\n"})

    assert discovery.report.artifacts == ()
    assert discovery.report.containers == ()
    assert discovery.report.observations == ()
    assert discovery.diagnostics == ()


@pytest.mark.parametrize("location", ["CLAUDE.md", ".claude/CLAUDE.md"])
def test_either_accepted_project_entry_point_location_is_recognised(
    tmp_path: Path, location: str
) -> None:
    discovery = scan(tmp_path, {location: "# entry point\n"})

    assert locators(discovery, ArtifactType.ENTRY_POINT) == [location]
    assert codes(discovery) == []


def test_both_entry_point_locations_at_once_is_a_duplicate(tmp_path: Path) -> None:
    discovery = scan(tmp_path, {"CLAUDE.md": "# one\n", ".claude/CLAUDE.md": "# two\n"})

    assert locators(discovery, ArtifactType.ENTRY_POINT) == ["CLAUDE.md", ".claude/CLAUDE.md"]
    assert codes(discovery) == ["HS-ENTRYPOINT-DUPLICATE"]
    assert ".claude/CLAUDE.md" in discovery.diagnostics[0].message


def test_a_nested_entry_point_does_not_make_the_project_entry_point_a_duplicate(
    tmp_path: Path,
) -> None:
    """Only the two accepted root locations decide the duplicate. Whether a subdirectory
    CLAUDE.md is inventoried at all is #34's question, so nothing here fixes that answer."""
    discovery = scan(tmp_path, {"CLAUDE.md": "# one\n", "packages/api/CLAUDE.md": "# nested\n"})

    assert "HS-ENTRYPOINT-DUPLICATE" not in codes(discovery)


def test_rules_are_scanned_recursively(tmp_path: Path) -> None:
    discovery = scan(
        tmp_path,
        {
            ".claude/rules/style.md": "# style\n",
            ".claude/rules/python/typing.md": '---\npaths:\n  - "**/*.py"\n---\n\n# typing\n',
            ".claude/rules/deep/deeper/nested.md": "# nested\n",
        },
    )

    assert locators(discovery, ArtifactType.RULE) == [
        ".claude/rules/deep/deeper/nested.md",
        ".claude/rules/python/typing.md",
        ".claude/rules/style.md",
    ]
    assert codes(discovery) == []


def test_a_rule_that_is_not_markdown_is_not_a_rule(tmp_path: Path) -> None:
    discovery = scan(tmp_path, {".claude/rules/notes.txt": "not a rule\n"})

    assert locators(discovery, ArtifactType.RULE) == []


def test_unparseable_rule_frontmatter_is_reported_and_the_rule_still_inventoried(
    tmp_path: Path,
) -> None:
    discovery = scan(tmp_path, {".claude/rules/broken.md": "---\npaths: [1, 2\n---\n\n# broken\n"})

    assert locators(discovery, ArtifactType.RULE) == [".claude/rules/broken.md"]
    assert codes(discovery) == ["HS-RULE-FRONTMATTER-INVALID"]
    assert discovery.diagnostics[0].subject.locator == ".claude/rules/broken.md"


def test_a_rule_that_is_not_utf_8_is_a_file_finding_not_a_yaml_one(tmp_path: Path) -> None:
    repository = write_tree(tmp_path / "repository", {".claude/rules/keep.md": "# keep\n"})
    (repository / ".claude" / "rules" / "broken.md").write_bytes(b"---\nname: \xff\xfe\n---\n")

    discovery = claude_code.discover(repository)

    assert codes(discovery) == ["HS-RULE-FILE-UNREADABLE"]
    assert discovery.diagnostics[0].subject.locator == ".claude/rules/broken.md"
    assert locators(discovery, ArtifactType.RULE) == [
        ".claude/rules/broken.md",
        ".claude/rules/keep.md",
    ]


def test_a_rule_without_frontmatter_is_not_a_finding(tmp_path: Path) -> None:
    discovery = scan(tmp_path, {".claude/rules/prose.md": "# prose only\n"})

    assert codes(discovery) == []


def test_a_directory_form_skill_is_a_skill(tmp_path: Path) -> None:
    discovery = scan(tmp_path, {".claude/skills/audit/SKILL.md": "---\nname: audit\n---\n"})

    skill = only(discovery, ArtifactType.SKILL)

    assert skill.locator == ".claude/skills/audit/SKILL.md"
    assert skill.representation is Representation.DIRECTORY


def test_a_project_skill_is_exactly_one_directory_deep(tmp_path: Path) -> None:
    """`.claude/skills/<name>/SKILL.md` is the project skill location. A deeper SKILL.md is a
    plugin component a manifest declares (#5) or supporting material of the skill above it,
    and a nested project skill lives under its own subtree's `.claude/skills/` (#34)."""
    discovery = scan(
        tmp_path,
        {
            ".claude/skills/audit/SKILL.md": "# audit\n",
            ".claude/skills/engineering/audit/SKILL.md": "# deeper\n",
            ".claude/skills/audit/resources/example/SKILL.md": "# an example, not a skill\n",
        },
    )

    assert locators(discovery, ArtifactType.SKILL) == [".claude/skills/audit/SKILL.md"]


def test_a_deeper_skill_file_invents_no_command_collision(tmp_path: Path) -> None:
    """Two groups holding a same-named SKILL.md are not two project skills, so a command of
    that name is shadowed by neither."""
    discovery = scan(
        tmp_path,
        {
            ".claude/skills/team-a/deploy/SKILL.md": "# a\n",
            ".claude/skills/team-b/deploy/SKILL.md": "# b\n",
            ".claude/commands/deploy.md": "deploy\n",
        },
    )

    assert codes(discovery) == []
    assert locators(discovery, ArtifactType.SKILL) == [".claude/commands/deploy.md"]


def test_a_command_form_skill_is_a_skill_in_its_legacy_representation(tmp_path: Path) -> None:
    discovery = scan(tmp_path, {".claude/commands/audit.md": "Run the audit.\n"})

    skill = only(discovery, ArtifactType.SKILL)

    assert skill.locator == ".claude/commands/audit.md"
    assert skill.representation is Representation.LEGACY_COMMAND


def test_a_command_sharing_a_skills_name_is_shadowed_by_it(tmp_path: Path) -> None:
    discovery = scan(
        tmp_path,
        {".claude/skills/audit/SKILL.md": "# audit\n", ".claude/commands/audit.md": "audit\n"},
    )

    assert sorted(locators(discovery, ArtifactType.SKILL)) == [
        ".claude/commands/audit.md",
        ".claude/skills/audit/SKILL.md",
    ]
    assert codes(discovery) == ["HS-SKILL-NAME-SHADOWED"]
    assert discovery.diagnostics[0].subject.locator == ".claude/commands/audit.md"


def test_a_command_with_its_own_name_is_not_shadowed(tmp_path: Path) -> None:
    discovery = scan(
        tmp_path,
        {".claude/skills/audit/SKILL.md": "# audit\n", ".claude/commands/report.md": "report\n"},
    )

    assert codes(discovery) == []


def test_a_skills_command_name_comes_from_its_directory_not_its_frontmatter(
    tmp_path: Path,
) -> None:
    """For a project skill the directory name defines the command; the frontmatter name is
    only a display label, so it is the directory a command can collide with."""
    discovery = scan(
        tmp_path,
        {
            ".claude/skills/audit/SKILL.md": "---\nname: report\n---\n\n# audit\n",
            ".claude/commands/report.md": "report\n",
        },
    )

    assert codes(discovery) == []


def test_agents_are_scanned_recursively(tmp_path: Path) -> None:
    discovery = scan(
        tmp_path,
        {".claude/agents/reviewer.md": "# reviewer\n", ".claude/agents/deep/planner.md": "# p\n"},
    )

    assert locators(discovery, ArtifactType.AGENT) == [
        ".claude/agents/deep/planner.md",
        ".claude/agents/reviewer.md",
    ]


def test_project_settings_are_an_artifact_container_rather_than_an_artifact(
    tmp_path: Path,
) -> None:
    discovery = scan(tmp_path, {".claude/settings.json": '{"hooks": {}}\n'})

    assert discovery.report.artifacts == ()
    assert [container.locator for container in discovery.report.containers] == [
        ".claude/settings.json"
    ]
    assert discovery.report.containers[0].format is ContainerFormat.JSON


def test_machine_local_settings_are_excluded(tmp_path: Path) -> None:
    discovery = scan(tmp_path, {".claude/settings.local.json": '{"hooks": {}}\n'})

    assert discovery.report.containers == ()


def test_discovery_reports_repository_scope_and_leaves_authority_unresolved(
    tmp_path: Path,
) -> None:
    """Discovery establishes location and type. Provenance without a lock is authored, the
    runtime loads every location scanned here, and a discovered artifact is Inventoried by
    definition. Authority applies in repository scope, so an unresolved one is `unknown` --
    the value that refuses mutation -- never null, which means authority does not apply."""
    discovery = scan(tmp_path, {"CLAUDE.md": "# entry\n", ".claude/rules/style.md": "# style\n"})

    for artifact in discovery.report.artifacts:
        assert artifact.scope is Scope.REPOSITORY
        assert artifact.provenance is Provenance.AUTHORED
        assert artifact.management_authority is ManagementAuthority.UNKNOWN
        assert artifact.activation is Activation.UNKNOWN
        assert artifact.activation_cause is ActivationCause.RUNTIME_STATE_NOT_READ
        assert artifact.harness_relevant is True
        assert artifact.sets == (GovernanceSet.INVENTORIED,)


def test_the_report_is_ordered_by_locator(tmp_path: Path) -> None:
    discovery = scan(
        tmp_path,
        {
            "CLAUDE.md": "# entry\n",
            ".claude/rules/b.md": "# b\n",
            ".claude/rules/a.md": "# a\n",
            ".claude/agents/z.md": "# z\n",
        },
    )

    document = discovery.report.as_document()
    artifacts = document["artifacts"]
    assert isinstance(artifacts, list)
    assert [entry["locator"] for entry in artifacts] == [
        ".claude/agents/z.md",
        ".claude/rules/a.md",
        ".claude/rules/b.md",
        "CLAUDE.md",
    ]


def test_a_runtime_location_that_is_a_file_rather_than_a_directory_is_ignored(
    tmp_path: Path,
) -> None:
    discovery = scan(tmp_path, {".claude/rules": "not a directory\n"})

    assert discovery.report.artifacts == ()
    assert discovery.diagnostics == ()
