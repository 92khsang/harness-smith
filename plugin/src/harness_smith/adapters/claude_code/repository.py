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

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

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
)
from harness_smith.canonical_json import CanonicalisationError, declaration_digest
from harness_smith.diagnostics import Diagnostic
from harness_smith.frontmatter import Frontmatter, FrontmatterState, read_frontmatter_file
from harness_smith.json_document import (
    JsonDocument,
    JsonDocumentState,
    own_repeated_names,
    read_json_document,
    repeated_names,
)
from harness_smith.vocabulary import Subject, SubjectKind

PROJECT_ENTRY_POINTS: tuple[str, ...] = ("CLAUDE.md", ".claude/CLAUDE.md")
RULES_DIRECTORY = ".claude/rules"
SKILLS_DIRECTORY = ".claude/skills"
COMMANDS_DIRECTORY = ".claude/commands"
AGENTS_DIRECTORY = ".claude/agents"
PROJECT_SETTINGS = ".claude/settings.json"

# The one member of a settings file this adapter reads; everything else in it is
# configuration the runtime owns and harness-smith leaves alone.
HOOKS_MEMBER = "hooks"

# What went wrong before the container's members could be read at all. The three are separate
# codes because they are separate fixes: repair the file, repair its JSON, or repair its shape.
CONTAINER_FINDINGS: Mapping[JsonDocumentState, str] = {
    JsonDocumentState.FILE_UNREADABLE: "HS-HOOK-CONTAINER-FILE-UNREADABLE",
    JsonDocumentState.UNPARSEABLE: "HS-HOOK-CONTAINER-UNPARSEABLE",
    JsonDocumentState.NOT_AN_OBJECT: "HS-HOOK-CONTAINER-INVALID",
}

# A project skill is exactly one directory deep; a Markdown artifact directory is walked whole.
PROJECT_SKILLS = "*/SKILL.md"
MARKDOWN_TREE = "**/*.md"


@dataclass(frozen=True)
class _Scan:
    """What scanning one runtime location found, and what it found wrong while looking."""

    artifacts: tuple[InventoriedArtifact, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    containers: tuple[ArtifactContainer, ...] = ()
    hooks: tuple[HookDeclaration, ...] = ()


@dataclass(frozen=True)
class _Hooks:
    """A container's hook declarations, or the finding that says why there are none."""

    declarations: tuple[HookDeclaration, ...] = ()
    code: str = ""
    reason: str = ""


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


def _settings(root: Path) -> _Scan:
    """Project settings hold hook declarations, so the file is an Artifact Container rather
    than an Artifact, and the hooks in it are artifacts addressed by a pointer into it.
    ``.claude/settings.local.json`` is machine-local and is never discovered."""
    path = root / PROJECT_SETTINGS
    if not path.is_file():
        return _Scan()
    hooks = _hooks(read_json_document(path))
    container = (
        ArtifactContainer(
            PROJECT_SETTINGS,
            ContainerFormat.JSON,
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


def _hooks(document: JsonDocument) -> _Hooks:
    """Every hook declaration in ``document``, each addressed by a JSON Pointer and digested.

    One declaration is one matcher group. The matcher and the ordered actions it runs are a
    single execution declaration, and reordering those actions changes what runs, so the group
    is addressed whole at ``/hooks/<event>/<index>`` rather than per action.

    Reading is all or nothing. A container read only in part would hand out pointers computed
    past a shape the reader did not expect, and those pointers would address something other
    than the declarations they name; and a declaration whose digest cannot be computed would
    leave the container half identified. Either way no hook in it resolves.

    A repeated property name is refused everywhere it would decide what is discovered: the
    ``hooks`` member itself, an event inside it, and anything inside a declaration. Which of
    two same-named members the runtime keeps is not recorded anywhere this project has
    verified, so a repeat there is reported rather than resolved by picking one. A repeat in
    configuration that is not a hook decides nothing here and is left alone.
    """
    if document.state is not JsonDocumentState.PARSED:
        return _Hooks(code=CONTAINER_FINDINGS[document.state], reason=document.reason)
    if HOOKS_MEMBER in own_repeated_names(document.members):
        return _invalid(f"the `{HOOKS_MEMBER}` member is declared more than once")
    events = document.members.get(HOOKS_MEMBER)
    if events is None:
        return _Hooks()
    if not isinstance(events, dict):
        return _invalid(f"the `{HOOKS_MEMBER}` member is not an object of hook events")
    repeated_events = own_repeated_names(events)
    if repeated_events:
        return _invalid(f"the `{repeated_events[0]}` hook event is declared more than once")
    declarations: list[HookDeclaration] = []
    for event in sorted(events):
        group = events[event]
        if not isinstance(group, list):
            return _invalid(f"the `{event}` hook event is not an array of declarations")
        for index, declaration in enumerate(group):
            if not isinstance(declaration, dict):
                return _invalid(
                    f"the `{event}` hook event holds a declaration that is not an object"
                )
            locator = f"{PROJECT_SETTINGS}#/{HOOKS_MEMBER}/{_pointer_token(event)}/{index}"
            digested = _digest(locator, declaration)
            if digested is None:
                return _invalid(_digest_reason(event, index, declaration))
            declarations.append(digested)
    return _Hooks(tuple(declarations))


def _digest(locator: str, declaration: Mapping[str, object]) -> HookDeclaration | None:
    """``declaration`` with its Declaration Digest, or nothing when RFC 8785 refuses it.

    Section 3.1 admits only declarations with no duplicate property names, whose strings are
    Unicode and whose numbers are IEEE 754 doubles. Digesting one that fails those conditions
    and calling the result an RFC 8785 digest would be a false claim, so it is refused instead.
    """
    if repeated_names(declaration):
        return None
    try:
        return HookDeclaration(locator, declaration_digest(declaration))
    except CanonicalisationError:
        return None


def _digest_reason(event: str, index: int, declaration: Mapping[str, object]) -> str:
    where = f"the declaration at index {index} of the `{event}` hook event"
    repeated = repeated_names(declaration)
    if repeated:
        return f"{where} repeats the property name `{repeated[0]}`"
    return f"{where} holds a value that has no canonical JSON form"


def _invalid(reason: str) -> _Hooks:
    return _Hooks(code="HS-HOOK-CONTAINER-INVALID", reason=reason)


def _pointer_token(name: str) -> str:
    """One JSON Pointer reference token, per RFC 6901: ``~`` becomes ``~0`` and ``/`` becomes
    ``~1``, in that order, so that a name carrying either stays one segment."""
    return name.replace("~", "~0").replace("/", "~1")


def _files(directory: Path, pattern: str) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob(pattern) if path.is_file())


def _locator(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()
