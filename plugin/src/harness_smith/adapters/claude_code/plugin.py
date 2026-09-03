"""Manifest-aware discovery over one plugin: the components it declares, and nothing else.

A plugin is a whole tree — sources, documentation, vendored dependencies, build output — of
which the runtime loads a named few. Discovery reads only the locations ``manifest`` resolved,
so the rest of the tree is excluded by rule rather than by a pattern that has to keep guessing
what a cache happens to contain.

Two kinds of component come out of it. Skills, command-form skills and subagents are Artifacts
of declared types, so they are enumerated file by file. Workflows, output styles, themes, MCP
and LSP configuration, monitors, executables and the manifest itself have no Artifact Type at
all, so they are located rather than enumerated and reported as Runtime Component Observations.
Having no type decides which operations apply to them; it does not decide what the adapter may
do with the Surface they sit on, so their Capability Policy is looked up from their Scope like
any other. A plugin's hooks are Artifacts too, and they are read at the locations
``manifest`` resolved and nowhere else: the default file the runtime always loads, the
additional files the manifest names, and the manifest itself where it writes hooks out in
place. Which of those exist, and which spellings the runtime accepts, was settled once there;
recomputing any of it here would be a second implementation of the same rules.

Everything found here sits on the ``plugin`` Surface, this repository's own plugin product
source. Classifying an installed third-party plugin as ``external`` is a separate scan's
question.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from harness_smith.adapters.claude_code import hooks as hook_container
from harness_smith.adapters.claude_code import tree
from harness_smith.adapters.claude_code.capability import capability
from harness_smith.adapters.claude_code.manifest import (
    HOOKS_MEMBER,
    MANIFEST,
    Component,
    Resolution,
    resolve,
)
from harness_smith.artifacts import (
    ArtifactContainer,
    ArtifactType,
    ContainerFormat,
    ContainerKind,
    Discovery,
    DiscoveryReport,
    HookDeclaration,
    InventoriedArtifact,
    Representation,
    RuntimeComponentObservation,
    Scope,
)
from harness_smith.diagnostics import Diagnostic
from harness_smith.json_document import JsonDocumentState, read_json_document
from harness_smith.vocabulary import Subject, SubjectKind

__all__ = ["discover_plugin"]

EXECUTABLES_DIRECTORY = "bin"
EXECUTABLES = "executables"
MANIFEST_COMPONENT = "manifest"

# The components with no Artifact Type, in report order. Hooks are absent because a Hook is an
# Artifact, and the manifest and the executables directory because no manifest key moves them.
OBSERVED: tuple[Component, ...] = (
    Component.WORKFLOWS,
    Component.OUTPUT_STYLES,
    Component.THEMES,
    Component.MONITORS,
    Component.MCP_SERVERS,
    Component.LSP_SERVERS,
)

SCOPE = Scope.PLUGIN


def discover_plugin(root: Path) -> Discovery:
    """Scan the plugin rooted at ``root`` for the components its manifest and the runtime's
    defaults put there."""
    resolution = resolve(root)
    hooks = _hooks(root, resolution)
    return Discovery(
        report=DiscoveryReport(
            artifacts=(
                *_skill_artifacts(root, resolution),
                *_agents(root, resolution),
                *hooks.artifacts,
            ),
            containers=hooks.containers,
            observations=_observations(root, resolution),
        ),
        diagnostics=(*resolution.diagnostics, *hooks.diagnostics),
        hooks=hooks.declarations,
    )


def _artifact(
    found: str, artifact_type: ArtifactType, representation: Representation
) -> InventoriedArtifact:
    return InventoriedArtifact.runtime_native(found, artifact_type, SCOPE, representation)


def _skill_artifacts(root: Path, resolution: Resolution) -> tuple[InventoriedArtifact, ...]:
    """Every Skill a plugin declares, however it is reached.

    A `skills` path and a `commands` path can name the same skill directory, and it is one
    Skill either way. Representation says how the artifact is written down, which the path that
    reached it does not change, so a directory-form skill stays one even when a command path
    found it.
    """
    found: dict[str, Representation] = {}
    for locator, representation in (*_skills(root, resolution), *_commands(root, resolution)):
        if found.get(locator) is not Representation.DIRECTORY:
            found[locator] = representation
    return tuple(
        _artifact(locator, ArtifactType.SKILL, representation)
        for locator, representation in sorted(found.items())
    )


def _skills(root: Path, resolution: Resolution) -> Iterator[tuple[str, Representation]]:
    """A skills path is either one skill or a directory of them, decided by whether it holds a
    ``SKILL.md`` of its own. Both forms are documented, and reading the path as a directory of
    skills when it is one would take a skill's own supporting material for more skills."""
    for location in resolution.locations[Component.SKILLS]:
        directory = root / location
        if (directory / tree.SKILL_FILE).is_file():
            yield tree.locator(root, directory / tree.SKILL_FILE), Representation.DIRECTORY
            continue
        for path in tree.files(directory, tree.NESTED_SKILLS):
            yield tree.locator(root, path), Representation.DIRECTORY


def _commands(root: Path, resolution: Resolution) -> Iterator[tuple[str, Representation]]:
    """A commands path names "a command file or skill directory".

    A directory holding a ``SKILL.md`` is that skill and only that skill: walking it for
    Markdown would inventory the skill's own supporting material as commands the runtime never
    loads. A directory without one is a directory of command files.
    """
    for location in resolution.locations[Component.COMMANDS]:
        path = root / location
        if path.is_file():
            if path.suffix == tree.MARKDOWN:
                yield tree.locator(root, path), Representation.LEGACY_COMMAND
            continue
        skill = path / tree.SKILL_FILE
        if skill.is_file():
            yield tree.locator(root, skill), Representation.DIRECTORY
            continue
        for entry in tree.files(path, tree.MARKDOWN_TREE):
            yield tree.locator(root, entry), Representation.LEGACY_COMMAND


def _agents(root: Path, resolution: Resolution) -> tuple[InventoriedArtifact, ...]:
    """A declared path may name one Markdown file rather than a directory of them."""
    found: list[str] = []
    for location in resolution.locations[Component.AGENTS]:
        path = root / location
        if path.is_file():
            if path.suffix == tree.MARKDOWN:
                found.append(tree.locator(root, path))
            continue
        found.extend(tree.locator(root, entry) for entry in tree.files(path, tree.MARKDOWN_TREE))
    return tuple(
        _artifact(entry, ArtifactType.AGENT, Representation.FILE)
        for entry in dict.fromkeys(sorted(found))
    )


def _observations(root: Path, resolution: Resolution) -> tuple[RuntimeComponentObservation, ...]:
    """A component is observed where it is, so a location nothing occupies is not reported."""
    found = [
        _observation(component.value, location)
        for component in OBSERVED
        for location in resolution.locations[component]
        if (root / location).exists()
    ]
    if (root / EXECUTABLES_DIRECTORY).is_dir():
        found.append(_observation(EXECUTABLES, EXECUTABLES_DIRECTORY))
    if (root / MANIFEST).is_file():
        found.append(_observation(MANIFEST_COMPONENT, MANIFEST))
    return tuple(found)


def _observation(component: str, location: str) -> RuntimeComponentObservation:
    return RuntimeComponentObservation(location, component, SCOPE, capability(SCOPE))


@dataclass(frozen=True)
class _Hooks:
    """The hook containers a plugin holds, and what was found wrong reading them."""

    containers: tuple[ArtifactContainer, ...] = ()
    artifacts: tuple[InventoriedArtifact, ...] = ()
    declarations: tuple[HookDeclaration, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()


def _hooks(root: Path, resolution: Resolution) -> _Hooks:
    """Every hook the plugin declares, at the locations the manifest resolved.

    The manifest is one location among them and is read from the document the resolution
    already parsed. The default file and each additional file stay separate containers, and a
    declaration repeated across them is two declarations at two Locators: which of them the
    runtime ends up running is a question about the effective harness, not about what is
    written down.
    """
    found = _Hooks()
    for location in resolution.locations[Component.HOOKS]:
        if location == MANIFEST:
            found = _joined(found, _inline(resolution))
            continue
        path = root / location
        if not path.is_file():
            continue
        read = hook_container.read(read_json_document(path), location, SCOPE)
        found = _joined(found, _container_read(read, location, ContainerKind.PLUGIN_HOOK_FILE))
    return found


def _inline(resolution: Resolution) -> _Hooks:
    """Hooks a manifest writes out in place, addressed by a pointer into the manifest.

    The field takes the events object directly or as entries of a list that also holds paths,
    so the pointer that reaches each one differs while everything under it is read one way.
    """
    document = resolution.manifest
    if document.state is not JsonDocumentState.PARSED:
        return _Hooks()
    declared = document.members.get(HOOKS_MEMBER)
    reads: list[hook_container.Hooks] = []
    if isinstance(declared, dict):
        reads.append(hook_container.read_events(declared, MANIFEST, f"/{HOOKS_MEMBER}", SCOPE))
    elif isinstance(declared, list):
        reads.extend(
            hook_container.read_events(entry, MANIFEST, f"/{HOOKS_MEMBER}/{index}", SCOPE)
            for index, entry in enumerate(declared)
            if isinstance(entry, dict)
        )
    if not reads:
        return _Hooks()
    return _container_read(_merged(reads), MANIFEST, ContainerKind.PLUGIN_MANIFEST)


def _merged(reads: list[hook_container.Hooks]) -> hook_container.Hooks:
    """One manifest is one container, however many inline declarations it holds."""
    refused = next((read for read in reads if read.code), None)
    if refused is not None:
        return refused
    return hook_container.Hooks(
        tuple(declaration for read in reads for declaration in read.declarations)
    )


def _container_read(read: hook_container.Hooks, locator: str, kind: ContainerKind) -> _Hooks:
    """One container's declarations, or the container holding nothing when it could not be
    read, which is a different report from one that holds nothing."""
    if read.code:
        finding = Diagnostic.of(
            read.code, Subject(SubjectKind.CONTAINER, locator), message=read.reason
        )
        return _Hooks(
            containers=(ArtifactContainer(locator, ContainerFormat.JSON, kind, SCOPE),),
            diagnostics=(finding,),
        )
    holds = tuple(declaration.locator for declaration in read.declarations)
    artifacts = tuple(
        InventoriedArtifact.runtime_native(
            declaration.locator, ArtifactType.HOOK, SCOPE, Representation.CONTAINER_ENTRY
        )
        for declaration in read.declarations
    )
    return _Hooks(
        containers=(ArtifactContainer(locator, ContainerFormat.JSON, kind, SCOPE, None, holds),),
        artifacts=artifacts,
        declarations=read.declarations,
    )


def _joined(left: _Hooks, right: _Hooks) -> _Hooks:
    return _Hooks(
        left.containers + right.containers,
        left.artifacts + right.artifacts,
        left.declarations + right.declarations,
        left.diagnostics + right.diagnostics,
    )
