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
any other. A plugin's hooks are Artifacts too, and reading every hook source the runtime honours
is a separate scan; resolving where a plugin's hooks live is ``manifest``'s job and reading them
is not this one's.

Everything found here sits on the ``plugin`` Surface, this repository's own plugin product
source. Classifying an installed third-party plugin as ``external`` is a separate scan's
question.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from harness_smith.adapters.claude_code import tree
from harness_smith.adapters.claude_code.capability import capability
from harness_smith.adapters.claude_code.manifest import MANIFEST, Component, Resolution, resolve
from harness_smith.artifacts import (
    ArtifactType,
    Discovery,
    DiscoveryReport,
    InventoriedArtifact,
    Representation,
    RuntimeComponentObservation,
    Scope,
)

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
    return Discovery(
        report=DiscoveryReport(
            artifacts=(*_skill_artifacts(root, resolution), *_agents(root, resolution)),
            observations=_observations(root, resolution),
        ),
        diagnostics=resolution.diagnostics,
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
