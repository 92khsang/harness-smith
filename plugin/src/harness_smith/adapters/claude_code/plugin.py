"""Manifest-aware discovery over one plugin: the components it declares, and nothing else.

A plugin is a whole tree — sources, documentation, vendored dependencies, build output — of
which the runtime loads a named few. Discovery reads only the locations ``manifest`` resolved,
so the rest of the tree is excluded by rule rather than by a pattern that has to keep guessing
what a cache happens to contain.

Two kinds of component come out of it. Skills, command-form skills and subagents are Artifacts
of declared types, so they are enumerated file by file. Workflows, output styles, themes, MCP
and LSP configuration, monitors, executables and the manifest itself have no Artifact Type at
all, so they are located and reported as Runtime Component Observations: read, never checked as
pass or fail, never mutated. A plugin's hooks are Artifacts too, and the scan that reads every
hook source the runtime honours consumes the locations resolved here.
"""

from __future__ import annotations

from pathlib import Path

from harness_smith.adapters.claude_code.manifest import MANIFEST, Component, Resolution, resolve
from harness_smith.adapters.claude_code.tree import files, locator
from harness_smith.artifacts import (
    ArtifactType,
    CapabilityPolicy,
    CapabilityValue,
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

# What the adapter is willing to do with a runtime component: list it, and nothing else. There
# is no type to check it against, no lifecycle to advise on, and a plugin is never written to.
OBSERVED_ONLY = CapabilityPolicy(
    inventory=CapabilityValue.OBSERVED_ONLY,
    structural_check=CapabilityValue.UNSUPPORTED,
    lifecycle_advice=CapabilityValue.UNSUPPORTED,
    mutation=CapabilityValue.UNSUPPORTED,
)

SKILL_FILE = "SKILL.md"
NESTED_SKILLS = "*/SKILL.md"
MARKDOWN = ".md"
MARKDOWN_TREE = "**/*.md"


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
    return InventoriedArtifact.runtime_native(found, artifact_type, Scope.PLUGIN, representation)


def _skills(root: Path, resolution: Resolution) -> tuple[InventoriedArtifact, ...]:
    """A skills path is either one skill or a directory of them, decided by whether it holds a
    ``SKILL.md`` of its own. Both forms are documented, and reading the path as a directory of
    skills when it is one would take a skill's own supporting material for more skills."""
    found: list[str] = []
    for location in resolution.locations[Component.SKILLS]:
        directory = root / location
        if (directory / SKILL_FILE).is_file():
            found.append(locator(root, directory / SKILL_FILE))
            continue
        found.extend(locator(root, path) for path in files(directory, NESTED_SKILLS))
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
            if path.suffix == MARKDOWN:
                found.append(locator(root, path))
            continue
        found.extend(locator(root, entry) for entry in files(path, MARKDOWN_TREE))
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
    return RuntimeComponentObservation(location, component, OBSERVED_ONLY)
