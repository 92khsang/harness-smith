"""The Claude Code runtime adapter: the locations this runtime defines and loads from.

Everything Claude-Code-specific lives here. Runtime-native structural discovery walks only the
locations the runtime itself declares, so a scan is bounded by ``.claude/`` and the two
accepted project entry-point locations rather than by the whole repository tree. Locations the
Harness Standard prescribes, and artifacts found because something points at them, are the
other two discovery layers and are not this function's business.

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
plugin manifest, which is the adapter's manifest-aware discovery, and a nested project skill
lives under its own subtree's ``.claude/skills/``, which needs the exclusion rules that bound a
repository-wide walk. Neither is discovered here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from harness_smith.artifacts import (
    Activation,
    ActivationCause,
    ArtifactContainer,
    ArtifactType,
    ContainerFormat,
    Discovery,
    DiscoveryReport,
    GovernanceSet,
    InventoriedArtifact,
    ManagementAuthority,
    Provenance,
    Representation,
    Scope,
)
from harness_smith.diagnostics import Diagnostic
from harness_smith.frontmatter import Frontmatter, FrontmatterState, read_frontmatter_file
from harness_smith.vocabulary import Subject, SubjectKind

PROJECT_ENTRY_POINTS: tuple[str, ...] = ("CLAUDE.md", ".claude/CLAUDE.md")
RULES_DIRECTORY = ".claude/rules"
SKILLS_DIRECTORY = ".claude/skills"
COMMANDS_DIRECTORY = ".claude/commands"
AGENTS_DIRECTORY = ".claude/agents"
PROJECT_SETTINGS = ".claude/settings.json"

# A project skill is exactly one directory deep; a Markdown artifact directory is walked whole.
PROJECT_SKILLS = "*/SKILL.md"
MARKDOWN_TREE = "**/*.md"


@dataclass(frozen=True)
class _Scan:
    """What scanning one runtime location found, and what it found wrong while looking."""

    artifacts: tuple[InventoriedArtifact, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()


def discover(root: Path) -> Discovery:
    """Scan ``root`` for the artifacts the Claude Code runtime defines locations for."""
    scans = (_entry_points(root), _rules(root), _skills(root), _agents(root))
    return Discovery(
        report=DiscoveryReport(
            artifacts=tuple(artifact for scan in scans for artifact in scan.artifacts),
            containers=_containers(root),
        ),
        diagnostics=tuple(diagnostic for scan in scans for diagnostic in scan.diagnostics),
    )


def _artifact(
    locator: str, artifact_type: ArtifactType, representation: Representation
) -> InventoriedArtifact:
    """A repository artifact as discovery alone can describe it.

    Discovery establishes location, type and representation. Provenance is authored until a
    lock records otherwise; everything scanned here is a location the runtime loads from, so
    the artifact is harness-relevant and Inventoried by construction. Management Authority
    reads as ``unknown`` because resolving it needs the manifest, the lock and Writer evidence
    that discovery never opens, and ``unknown`` refuses mutation, which is the safe answer to
    give before classification runs. Classification computes the authority and the remaining
    governance sets.
    """
    return InventoriedArtifact(
        locator=locator,
        type=artifact_type,
        scope=Scope.REPOSITORY,
        representation=representation,
        provenance=Provenance.AUTHORED,
        management_authority=ManagementAuthority.UNKNOWN,
        activation=Activation.UNKNOWN,
        activation_cause=ActivationCause.RUNTIME_STATE_NOT_READ,
        harness_relevant=True,
        sets=(GovernanceSet.INVENTORIED,),
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
    for path in _files(root / RULES_DIRECTORY, MARKDOWN_TREE):
        locator = _locator(root, path)
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

    for path in _files(skills_directory, PROJECT_SKILLS):
        artifacts.append(
            _artifact(_locator(root, path), ArtifactType.SKILL, Representation.DIRECTORY)
        )
        directory_form.add(path.parent.name)

    for path in _files(root / COMMANDS_DIRECTORY, MARKDOWN_TREE):
        locator = _locator(root, path)
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
            _artifact(_locator(root, path), ArtifactType.AGENT, Representation.FILE)
            for path in _files(root / AGENTS_DIRECTORY, MARKDOWN_TREE)
        )
    )


def _containers(root: Path) -> tuple[ArtifactContainer, ...]:
    """Project settings hold hook declarations, so the file is a container rather than an
    artifact. ``.claude/settings.local.json`` is machine-local and is never discovered."""
    if not (root / PROJECT_SETTINGS).is_file():
        return ()
    return (ArtifactContainer(locator=PROJECT_SETTINGS, format=ContainerFormat.JSON),)


def _files(directory: Path, pattern: str) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob(pattern) if path.is_file())


def _locator(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()
