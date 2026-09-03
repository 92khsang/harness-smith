"""The Discovery Report document: what one scan serialises, and in what order.

A Locator alone does not order a report that composes several Surfaces, because the same
Locator can occur in more than one Scope.
"""

from __future__ import annotations

from typing import Any

import pytest

from harness_smith.artifacts import (
    ArtifactContainer,
    ArtifactType,
    CapabilityPolicy,
    CapabilityValue,
    ContainerFormat,
    ContainerKind,
    DiscoveryReport,
    InventoriedArtifact,
    Representation,
    RuntimeComponentObservation,
    Scope,
    SettingsLayer,
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
            ArtifactContainer(
                SHARED,
                ContainerFormat.JSON,
                ContainerKind.USER_SETTINGS,
                Scope.USER_GLOBAL,
                SettingsLayer.USER,
            ),
            ArtifactContainer(
                SHARED, ContainerFormat.JSON, ContainerKind.PLUGIN_HOOK_FILE, Scope.PLUGIN
            ),
        )
    )

    ordered = [entry["scope"] for entry in section(report, "containers")]

    assert ordered == ["plugin", "user-global"]


def test_a_container_whose_layer_and_scope_disagree_is_refused() -> None:
    """Each settings layer sits in exactly one Scope. A container declaring a pair that cannot
    both be true would let a consumer trust either one."""
    with pytest.raises(ValueError, match="layer is in"):
        ArtifactContainer(
            SHARED,
            ContainerFormat.JSON,
            ContainerKind.SHARED_PROJECT_SETTINGS,
            Scope.USER_GLOBAL,
            SettingsLayer.SHARED_PROJECT,
        )


def test_a_container_that_is_not_a_settings_file_has_no_layer() -> None:
    container = ArtifactContainer(
        SHARED, ContainerFormat.JSON, ContainerKind.PLUGIN_HOOK_FILE, Scope.PLUGIN
    )

    assert container.settings_layer is None
    assert container.as_document()["settingsLayer"] is None


def test_a_container_source_and_its_layer_are_one_table() -> None:
    """A settings container names its layer and everything else names none, so a container
    cannot claim to be a plugin hook file and a shared project settings layer at once."""
    with pytest.raises(ValueError, match="plugin-hook-file container is in no layer"):
        ArtifactContainer(
            SHARED,
            ContainerFormat.JSON,
            ContainerKind.PLUGIN_HOOK_FILE,
            Scope.PLUGIN,
            SettingsLayer.SHARED_PROJECT,
        )


def test_a_settings_container_without_its_layer_is_refused() -> None:
    with pytest.raises(ValueError, match="shared-project-settings container is in the"):
        ArtifactContainer(
            SHARED, ContainerFormat.JSON, ContainerKind.SHARED_PROJECT_SETTINGS, Scope.REPOSITORY
        )


def test_a_hook_is_held_by_the_container_in_its_own_scope() -> None:
    """The same Locator occurs in more than one Scope, so the join is on both."""
    held = ".claude/settings.json#/hooks/Stop/0"
    repository = ArtifactContainer(
        SHARED,
        ContainerFormat.JSON,
        ContainerKind.SHARED_PROJECT_SETTINGS,
        Scope.REPOSITORY,
        SettingsLayer.SHARED_PROJECT,
        (held,),
    )
    plugin = ArtifactContainer(
        SHARED, ContainerFormat.JSON, ContainerKind.PLUGIN_HOOK_FILE, Scope.PLUGIN, None, (held,)
    )
    report = DiscoveryReport(
        artifacts=(
            InventoriedArtifact.runtime_native(
                held, ArtifactType.HOOK, Scope.REPOSITORY, Representation.CONTAINER_ENTRY
            ),
            InventoriedArtifact.runtime_native(
                held, ArtifactType.HOOK, Scope.PLUGIN, Representation.CONTAINER_ENTRY
            ),
        ),
        containers=(repository, plugin),
    )

    found = {artifact.scope: report.container_of(artifact) for artifact in report.artifacts}

    assert found[Scope.REPOSITORY] is repository
    assert found[Scope.PLUGIN] is plugin
    assert repository.settings_layer is SettingsLayer.SHARED_PROJECT
    assert plugin.settings_layer is None


def held_hook(scope: Scope, locator: str) -> InventoriedArtifact:
    return InventoriedArtifact.runtime_native(
        locator, ArtifactType.HOOK, scope, Representation.CONTAINER_ENTRY
    )


def settings(scope: Scope, locator: str, *holds: str) -> ArtifactContainer:
    return ArtifactContainer(
        locator,
        ContainerFormat.JSON,
        ContainerKind.SHARED_PROJECT_SETTINGS
        if scope is Scope.REPOSITORY
        else ContainerKind.USER_SETTINGS,
        scope,
        SettingsLayer.SHARED_PROJECT if scope is Scope.REPOSITORY else SettingsLayer.USER,
        holds,
    )


def test_one_container_is_inventoried_once_per_scope() -> None:
    with pytest.raises(ValueError, match="inventoried once per Scope"):
        DiscoveryReport(
            containers=(settings(Scope.REPOSITORY, SHARED), settings(Scope.REPOSITORY, SHARED))
        )


def test_two_containers_cannot_both_claim_one_artifact() -> None:
    """`container_of` would otherwise depend on the order the sections happen to be in."""
    held = f"{SHARED}#/hooks/Stop/0"

    with pytest.raises(ValueError, match="held by one container"):
        DiscoveryReport(
            artifacts=(held_hook(Scope.REPOSITORY, held),),
            containers=(
                settings(Scope.REPOSITORY, SHARED, held),
                settings(Scope.REPOSITORY, "other.json", held),
            ),
        )


def test_what_a_container_holds_is_inventoried() -> None:
    held = f"{SHARED}#/hooks/Stop/0"

    with pytest.raises(ValueError, match="held by a container and not inventoried"):
        DiscoveryReport(containers=(settings(Scope.REPOSITORY, SHARED, held),))


def test_a_container_in_another_scope_does_not_satisfy_a_hold() -> None:
    held = f"{SHARED}#/hooks/Stop/0"

    with pytest.raises(ValueError, match="held by a container and not inventoried"):
        DiscoveryReport(
            artifacts=(held_hook(Scope.USER_GLOBAL, held),),
            containers=(settings(Scope.REPOSITORY, SHARED, held),),
        )


def test_an_artifact_addressed_by_a_pointer_is_held_by_something() -> None:
    with pytest.raises(ValueError, match="addressed by a pointer into nothing"):
        DiscoveryReport(artifacts=(held_hook(Scope.REPOSITORY, f"{SHARED}#/hooks/Stop/0"),))
