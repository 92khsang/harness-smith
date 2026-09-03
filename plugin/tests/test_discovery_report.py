"""The Discovery Report document: what one scan serialises, and in what order.

A Locator alone does not order a report that composes several Surfaces, because the same
Locator can occur in more than one Scope.
"""

from __future__ import annotations

from typing import Any

from harness_smith.artifacts import (
    ArtifactContainer,
    ArtifactType,
    CapabilityPolicy,
    CapabilityValue,
    ContainerFormat,
    DiscoveryReport,
    InventoriedArtifact,
    Representation,
    RuntimeComponentObservation,
    Scope,
)

POLICY = CapabilityPolicy(
    CapabilityValue.MANAGED,
    CapabilityValue.MANAGED,
    CapabilityValue.MANAGED,
    CapabilityValue.MANAGED,
)

SHARED = ".mcp.json"


def section(report: DiscoveryReport, name: str) -> list[dict[str, Any]]:
    entries = report.as_document()[name]
    assert isinstance(entries, list)
    return entries


def observation(component: str, scope: Scope) -> RuntimeComponentObservation:
    return RuntimeComponentObservation(SHARED, component, scope, POLICY)


def artifact(artifact_type: ArtifactType, scope: Scope) -> InventoriedArtifact:
    return InventoriedArtifact.runtime_native(SHARED, artifact_type, scope, Representation.FILE)


def test_observations_sharing_a_locator_are_ordered_by_scope_then_component() -> None:
    report = DiscoveryReport(
        observations=(
            observation("mcpServers", Scope.PLUGIN),
            observation("manifest", Scope.EXTERNAL),
            observation("lspServers", Scope.PLUGIN),
        )
    )

    ordered = [(entry["scope"], entry["component"]) for entry in section(report, "observations")]

    assert ordered == [("external", "manifest"), ("plugin", "lspServers"), ("plugin", "mcpServers")]


def test_artifacts_sharing_a_locator_are_ordered_by_scope_then_type() -> None:
    report = DiscoveryReport(
        artifacts=(
            artifact(ArtifactType.SKILL, Scope.PLUGIN),
            artifact(ArtifactType.AGENT, Scope.PLUGIN),
            artifact(ArtifactType.RULE, Scope.REPOSITORY),
        )
    )

    ordered = [(entry["scope"], entry["type"]) for entry in section(report, "artifacts")]

    assert ordered == [("plugin", "agent"), ("plugin", "skill"), ("repository", "rule")]


def test_containers_sharing_a_locator_are_ordered_by_scope() -> None:
    report = DiscoveryReport(
        containers=(
            ArtifactContainer(SHARED, ContainerFormat.JSON, Scope.USER_GLOBAL),
            ArtifactContainer(SHARED, ContainerFormat.JSON, Scope.PLUGIN),
        )
    )

    ordered = [entry["scope"] for entry in section(report, "containers")]

    assert ordered == ["plugin", "user-global"]
