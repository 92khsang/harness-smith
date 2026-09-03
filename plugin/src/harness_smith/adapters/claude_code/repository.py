"""Runtime-native structural discovery over a repository.

A scan is bounded by ``.claude/`` and the two accepted project entry-point locations rather
than by the whole repository tree, because those are the locations the runtime itself declares.

The runtime behaviour this encodes, from the Claude Code documentation:

- a project entry point is read from ``./CLAUDE.md`` or ``./.claude/CLAUDE.md``
  (https://code.claude.com/docs/en/memory)
- ``.claude/rules/`` is discovered recursively, and a rule's ``paths`` frontmatter scopes it to
  a glob (https://code.claude.com/docs/en/memory, .../claude-directory)
- a project skill is ``.claude/skills/<name>/SKILL.md``, exactly one directory deep, and its
  command name is that directory's name; a file in ``.claude/commands/`` is named by its file
  name, and for either the frontmatter ``name`` is only a display label
  (https://code.claude.com/docs/en/slash-commands)

A deeper ``SKILL.md`` is not a project skill. A plugin reaches one by declaring its path in the
plugin manifest, which ``plugin`` discovers, and a nested project skill lives under its own
subtree's ``.claude/skills/``, which needs the exclusion rules that bound a repository-wide
walk. Neither is discovered here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from harness_smith.adapters.claude_code import hooks as hook_container
from harness_smith.adapters.claude_code import tree
from harness_smith.artifacts import (
    ArtifactContainer,
    ArtifactType,
    ContainerFormat,
    Discovery,
    DiscoveryReport,
    HookDeclaration,
    InventoriedArtifact,
    Representation,
    Scope,
    SettingsLayer,
)
from harness_smith.diagnostics import Diagnostic
from harness_smith.frontmatter import Frontmatter, FrontmatterState, read_frontmatter_file
from harness_smith.json_document import read_json_document
from harness_smith.vocabulary import Subject, SubjectKind

PROJECT_ENTRY_POINTS: tuple[str, ...] = ("CLAUDE.md", ".claude/CLAUDE.md")
RULES_DIRECTORY = ".claude/rules"
SKILLS_DIRECTORY = ".claude/skills"
COMMANDS_DIRECTORY = ".claude/commands"
AGENTS_DIRECTORY = ".claude/agents"
PROJECT_SETTINGS = ".claude/settings.json"


@dataclass(frozen=True)
class _Scan:
    """What scanning one runtime location found, and what it found wrong while looking."""

    artifacts: tuple[InventoriedArtifact, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    containers: tuple[ArtifactContainer, ...] = ()
    hooks: tuple[HookDeclaration, ...] = ()


def discover(root: Path) -> Discovery:
    """Scan ``root`` for the artifacts the Claude Code runtime defines locations for."""
    scans = (_entry_points(root), _rules(root), _skills(root), _agents(root), _settings(root))
    return Discovery(
        report=DiscoveryReport(
            artifacts=tuple(artifact for scan in scans for artifact in scan.artifacts),
            containers=tuple(container for scan in scans for container in scan.containers),
        ),
        diagnostics=tuple(diagnostic for scan in scans for diagnostic in scan.diagnostics),
        hooks=tuple(declaration for scan in scans for declaration in scan.hooks),
    )


def _artifact(
    locator: str, artifact_type: ArtifactType, representation: Representation
) -> InventoriedArtifact:
    return InventoriedArtifact.runtime_native(
        locator, artifact_type, Scope.REPOSITORY, representation
    )


def _entry_points(root: Path) -> _Scan:
    present = [location for location in PROJECT_ENTRY_POINTS if (root / location).is_file()]
    artifacts = tuple(
        _artifact(location, ArtifactType.ENTRY_POINT, Representation.FILE) for location in present
    )
    if len(present) < len(PROJECT_ENTRY_POINTS):
        return _Scan(artifacts)
    duplicate = Diagnostic.of(
        "HS-ENTRYPOINT-DUPLICATE",
        Subject(SubjectKind.ARTIFACT, present[0]),
        message=(
            "the project entry point exists at both accepted locations, "
            f"{present[0]} and {present[1]}"
        ),
    )
    return _Scan(artifacts, (duplicate,))


def _rules(root: Path) -> _Scan:
    artifacts: list[InventoriedArtifact] = []
    diagnostics: list[Diagnostic] = []
    for path in tree.files(root / RULES_DIRECTORY, tree.MARKDOWN_TREE):
        locator = tree.locator(root, path)
        finding = _frontmatter_finding(locator, read_frontmatter_file(path))
        if finding is not None:
            diagnostics.append(finding)
        artifacts.append(_artifact(locator, ArtifactType.RULE, Representation.FILE))
    return _Scan(tuple(artifacts), tuple(diagnostics))


def _frontmatter_finding(locator: str, frontmatter: Frontmatter) -> Diagnostic | None:
    """A rule with no frontmatter is a prose-only rule, not a broken one. The two ways a block
    can fail are separate findings: one is the file, the other is the YAML written in it."""
    match frontmatter.state:
        case FrontmatterState.ABSENT | FrontmatterState.PARSED:
            return None
        case FrontmatterState.FILE_UNREADABLE:
            code = "HS-RULE-FILE-UNREADABLE"
        case FrontmatterState.INVALID:
            code = "HS-RULE-FRONTMATTER-INVALID"
        case _:
            assert_never(frontmatter.state)
    return Diagnostic.of(code, Subject(SubjectKind.ARTIFACT, locator), message=frontmatter.reason)


def _skills(root: Path) -> _Scan:
    artifacts: list[InventoriedArtifact] = []
    diagnostics: list[Diagnostic] = []
    skills_directory = root / SKILLS_DIRECTORY
    directory_form: set[str] = set()

    for path in tree.files(skills_directory, tree.NESTED_SKILLS):
        artifacts.append(
            _artifact(tree.locator(root, path), ArtifactType.SKILL, Representation.DIRECTORY)
        )
        directory_form.add(path.parent.name)

    for path in tree.files(root / COMMANDS_DIRECTORY, tree.MARKDOWN_TREE):
        locator = tree.locator(root, path)
        artifacts.append(_artifact(locator, ArtifactType.SKILL, Representation.LEGACY_COMMAND))
        if path.stem in directory_form:
            diagnostics.append(
                Diagnostic.of(
                    "HS-SKILL-NAME-SHADOWED",
                    Subject(SubjectKind.ARTIFACT, locator),
                    message=(
                        f"the command-form skill `{path.stem}` shares its name with a "
                        "directory-form skill, which wins"
                    ),
                )
            )
    return _Scan(tuple(artifacts), tuple(diagnostics))


def _agents(root: Path) -> _Scan:
    return _Scan(
        tuple(
            _artifact(tree.locator(root, path), ArtifactType.AGENT, Representation.FILE)
            for path in tree.files(root / AGENTS_DIRECTORY, tree.MARKDOWN_TREE)
        )
    )


def _settings(root: Path) -> _Scan:
    """Project settings hold hook declarations, so the file is an Artifact Container rather
    than an Artifact, and the hooks in it are artifacts addressed by a pointer into it.
    ``.claude/settings.local.json`` is machine-local and is never discovered."""
    path = root / PROJECT_SETTINGS
    if not path.is_file():
        return _Scan()
    hooks = hook_container.read(read_json_document(path), PROJECT_SETTINGS, Scope.REPOSITORY)
    container = (
        ArtifactContainer(
            PROJECT_SETTINGS,
            ContainerFormat.JSON,
            Scope.REPOSITORY,
            SettingsLayer.SHARED_PROJECT,
            tuple(declaration.locator for declaration in hooks.declarations),
        ),
    )
    if hooks.code:
        finding = Diagnostic.of(
            hooks.code, Subject(SubjectKind.CONTAINER, PROJECT_SETTINGS), message=hooks.reason
        )
        return _Scan(diagnostics=(finding,), containers=container)
    artifacts = tuple(
        _artifact(declaration.locator, ArtifactType.HOOK, Representation.CONTAINER_ENTRY)
        for declaration in hooks.declarations
    )
    return _Scan(artifacts, containers=container, hooks=hooks.declarations)
