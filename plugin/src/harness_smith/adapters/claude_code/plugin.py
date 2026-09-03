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
            artifacts=(
                *_skills(root, resolution),
                *_markdown(
                    root,
                    resolution,
                    Component.COMMANDS,
                    ArtifactType.SKILL,
                    Representation.LEGACY_COMMAND,
                ),
                *_markdown(
                    root, resolution, Component.AGENTS, ArtifactType.AGENT, Representation.FILE
                ),
            ),
            observations=_observations(root, resolution),
        ),
        diagnostics=resolution.diagnostics,
    )


def _artifact(
    found: str, artifact_type: ArtifactType, representation: Representation
) -> InventoriedArtifact:
    return InventoriedArtifact.runtime_native(found, artifact_type, SCOPE, representation)


def _skills(root: Path, resolution: Resolution) -> tuple[InventoriedArtifact, ...]:
    """A skills path is either one skill or a directory of them, decided by whether it holds a
    ``SKILL.md`` of its own. Both forms are documented, and reading the path as a directory of
    skills when it is one would take a skill's own supporting material for more skills."""
    found: list[str] = []
    for location in resolution.locations[Component.SKILLS]:
        directory = root / location
        if (directory / tree.SKILL_FILE).is_file():
            found.append(tree.locator(root, directory / tree.SKILL_FILE))
            continue
        found.extend(tree.locator(root, path) for path in tree.files(directory, tree.NESTED_SKILLS))
    return _artifacts(found, ArtifactType.SKILL, Representation.DIRECTORY)


def _markdown(
    root: Path,
    resolution: Resolution,
    component: Component,
    artifact_type: ArtifactType,
    representation: Representation,
) -> tuple[InventoriedArtifact, ...]:
    """A declared path may name one Markdown file rather than a directory of them."""
    found: list[str] = []
    for location in resolution.locations[component]:
        path = root / location
        if path.is_file():
            if path.suffix == tree.MARKDOWN:
                found.append(tree.locator(root, path))
            continue
        found.extend(tree.locator(root, entry) for entry in tree.files(path, tree.MARKDOWN_TREE))
    return _artifacts(found, artifact_type, representation)


def _artifacts(
    found: list[str], artifact_type: ArtifactType, representation: Representation
) -> tuple[InventoriedArtifact, ...]:
    """Two locations may name the same file, and it is one artifact either way."""
    return tuple(
        _artifact(entry, artifact_type, representation) for entry in dict.fromkeys(sorted(found))
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
