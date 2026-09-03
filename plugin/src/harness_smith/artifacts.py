"""The artifact model, and what one scan produces.

An Artifact is a discovered unit of exactly one declared type. Provenance, Representation,
Scope and Activation are attributes on any type rather than types of their own, which is what
keeps the taxonomy at eight members.

A Discovery Report has three parts so that runtime surfaces with no declared type stay visible
without breaking the Artifact Inventory's type invariant: artifacts of the eight types, the
Artifact Containers holding artifacts addressed by pointer, and observations of runtime
components that have no type at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from harness_smith.diagnostics import Diagnostic

__all__ = [
    "SCOPE_BY_LAYER",
    "Activation",
    "ActivationCause",
    "ArtifactContainer",
    "ArtifactType",
    "CapabilityPolicy",
    "CapabilityValue",
    "ContainerFormat",
    "Discovery",
    "DiscoveryReport",
    "GovernanceSet",
    "HookDeclaration",
    "InventoriedArtifact",
    "ManagementAuthority",
    "Provenance",
    "Representation",
    "RuntimeComponentObservation",
    "Scope",
    "SettingsLayer",
]


class ArtifactType(StrEnum):
    ENTRY_POINT = "entry-point"
    RULE = "rule"
    SKILL = "skill"
    AGENT = "agent"
    HOOK = "hook"
    ENFORCEMENT = "enforcement"
    DOCUMENTATION = "documentation"
    DECISION_RECORD = "decision-record"


class Scope(StrEnum):
    """Which Surface an Artifact belongs to.

    A Surface is an identity and a precedence boundary, not a set of permissions and not a
    population. ``managed-policy`` is the administrator-controlled policy tier in effect for
    the current runtime or device; how many machines or users an organisation deployed it to
    is not part of that identity. Two Surfaces that permit the same things are still two
    Surfaces, so collapsing ``managed-policy`` into ``user-global`` because their Capability
    Policy rows agree would lose who the tier answers to and where it sits in precedence.
    """

    REPOSITORY = "repository"
    PLUGIN = "plugin"
    USER_GLOBAL = "user-global"
    EXTERNAL = "external"
    MANAGED_POLICY = "managed-policy"


class Representation(StrEnum):
    """How an Artifact is written down, where the runtime accepts a type in more than one
    form. A command-form skill is a Skill in its legacy-command representation, not a type of
    its own, and a hook declared inside a settings file is a Hook in its container-entry
    representation rather than a file of its own."""

    FILE = "file"
    DIRECTORY = "directory"
    LEGACY_COMMAND = "legacy-command"
    CONTAINER_ENTRY = "container-entry"


class Provenance(StrEnum):
    """Where an Artifact's content came from. History, never permission to write it now."""

    AUTHORED = "authored"
    GENERATED = "generated"
    IMPORTED = "imported"
    ADOPTED = "adopted"


class ManagementAuthority(StrEnum):
    """Who may write an Artifact now. ``UNKNOWN`` refuses mutation rather than presuming."""

    LOCAL = "local"
    HARNESS_SMITH = "harness-smith"
    EXTERNAL_PLUGIN = "external-plugin"
    UNKNOWN = "unknown"


class Activation(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"


class ActivationCause(StrEnum):
    """Two disjoint sets: "we could not tell" and "we can tell, and it is off"."""

    MANAGED_POLICY_UNINSPECTABLE = "managed-policy-uninspectable"
    WORKSPACE_TRUST_UNKNOWN = "workspace-trust-unknown"
    PLUGIN_AGENT_HOOK_SUPPORT_UNVERIFIED = "plugin-agent-hook-support-unverified"
    RUNTIME_STATE_NOT_READ = "runtime-state-not-read"
    ALLOW_MANAGED_HOOKS_ONLY = "allow-managed-hooks-only"
    DISABLE_ALL_HOOKS_MANAGED = "disable-all-hooks-managed"
    DISABLE_ALL_HOOKS = "disable-all-hooks"


class GovernanceSet(StrEnum):
    """A derived query over one Discovery Report and one external-evidence snapshot, never a
    label stored on an Artifact. Governed splits completely into Managed, Advisory and
    Unclassified."""

    INVENTORIED = "inventoried"
    GOVERNED = "governed"
    MANAGED = "managed"
    ADVISORY = "advisory"
    UNCLASSIFIED = "unclassified"
    OBSERVED = "observed"
    GOVERNED_HARNESS = "governed-harness"


class SettingsLayer(StrEnum):
    """Which settings layer a container belongs to, which is a different question from Scope.

    Scope says which project a file affects and where it sits in ownership; the layer says
    whether it is settings a project shares, a personal overlay, a user's own global
    configuration, or an administrator's policy. Two containers in `repository` Scope can be
    different layers, and an operation deciding whether it may write one needs the layer that
    Scope does not carry. Neither axis changes Capability Policy, which is a function of Scope
    alone.
    """

    SHARED_PROJECT = "shared-project"
    PROJECT_LOCAL = "project-local"
    USER = "user"
    MANAGED_POLICY = "managed-policy"


# Each layer sits in exactly one Scope, so a container declaring both is checked rather than
# trusted: the pair is the one place the two axes have to agree.
SCOPE_BY_LAYER: Mapping[SettingsLayer, Scope] = {
    SettingsLayer.SHARED_PROJECT: Scope.REPOSITORY,
    SettingsLayer.PROJECT_LOCAL: Scope.REPOSITORY,
    SettingsLayer.USER: Scope.USER_GLOBAL,
    SettingsLayer.MANAGED_POLICY: Scope.MANAGED_POLICY,
}


class ContainerFormat(StrEnum):
    JSON = "json"
    YAML_FRONTMATTER = "yaml-frontmatter"


class CapabilityValue(StrEnum):
    MANAGED = "managed"
    OBSERVED_ONLY = "observed-only"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class CapabilityPolicy:
    """What the Runtime Adapter is willing to do with a Surface, per capability. A permissive
    mutation value is a precondition, not permission."""

    inventory: CapabilityValue
    structural_check: CapabilityValue
    lifecycle_advice: CapabilityValue
    mutation: CapabilityValue

    def as_document(self) -> dict[str, object]:
        return {
            "inventory": self.inventory.value,
            "structuralCheck": self.structural_check.value,
            "lifecycleAdvice": self.lifecycle_advice.value,
            "mutation": self.mutation.value,
        }


@dataclass(frozen=True)
class InventoriedArtifact:
    """An Artifact a scan discovered, with the classification carried alongside it.

    ``management_authority`` is null exactly where authority does not apply, which is outside
    repository and plugin scope. Inside them it always takes one of the four values, and
    ``unknown`` is what an unresolved one reads as, because refusing mutation is the safe
    answer. ``sets`` holds the governance sets the artifact belongs to, which are derived
    queries over the report and the external-evidence snapshot rather than stored labels.
    """

    locator: str
    type: ArtifactType
    scope: Scope
    representation: Representation
    provenance: Provenance
    management_authority: ManagementAuthority | None
    activation: Activation
    activation_cause: ActivationCause | None
    harness_relevant: bool
    sets: tuple[GovernanceSet, ...]

    @classmethod
    def runtime_native(
        cls,
        locator: str,
        artifact_type: ArtifactType,
        scope: Scope,
        representation: Representation,
    ) -> InventoriedArtifact:
        """An Artifact as runtime-native structural discovery alone can describe it.

        Discovery establishes location, type, Scope and Representation. Provenance is authored
        until a lock records otherwise; every location scanned this way is one the runtime
        loads from, so the artifact is harness-relevant and Inventoried by construction.
        Management Authority reads as ``unknown`` because resolving it needs the manifest, the
        lock and Writer evidence that discovery never opens, and ``unknown`` refuses mutation,
        which is the safe answer to give before classification runs. Classification computes
        the authority and the remaining governance sets.
        """
        return cls(
            locator=locator,
            type=artifact_type,
            scope=scope,
            representation=representation,
            provenance=Provenance.AUTHORED,
            management_authority=ManagementAuthority.UNKNOWN,
            activation=Activation.UNKNOWN,
            activation_cause=ActivationCause.RUNTIME_STATE_NOT_READ,
            harness_relevant=True,
            sets=(GovernanceSet.INVENTORIED,),
        )

    def as_document(self) -> dict[str, object]:
        return {
            "locator": self.locator,
            "type": self.type.value,
            "scope": self.scope.value,
            "representation": self.representation.value,
            "provenance": self.provenance.value,
            "managementAuthority": (
                None if self.management_authority is None else self.management_authority.value
            ),
            "activation": self.activation.value,
            "activationCause": (
                None if self.activation_cause is None else self.activation_cause.value
            ),
            "harnessRelevant": self.harness_relevant,
            "sets": [member.value for member in self.sets],
        }


@dataclass(frozen=True)
class ArtifactContainer:
    """A file holding zero or more Artifacts addressed by pointer rather than by path.

    A container carries the Scope it was found in, so the same containing file at the same
    Locator in two Scopes is two entries rather than one, and the settings layer where it has
    one, so that a reader following a Hook to the container it is held in learns whether it is
    shared settings or a personal overlay without parsing a Locator. A container that is not a
    settings file has no layer.
    """

    locator: str
    format: ContainerFormat
    scope: Scope
    settings_layer: SettingsLayer | None = None
    holds: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.settings_layer is not None and SCOPE_BY_LAYER[self.settings_layer] != self.scope:
            raise ValueError(
                f"the {self.settings_layer.value} layer is in "
                f"{SCOPE_BY_LAYER[self.settings_layer].value} scope, not {self.scope.value}"
            )

    def as_document(self) -> dict[str, object]:
        return {
            "locator": self.locator,
            "format": self.format.value,
            "scope": self.scope.value,
            "settingsLayer": None if self.settings_layer is None else self.settings_layer.value,
            "holds": sorted(self.holds),
        }


@dataclass(frozen=True)
class RuntimeComponentObservation:
    """A runtime surface with no declared Artifact Type.

    Having no type is a question about which operations apply to the component, not about what
    the adapter may do with the Surface it sits on. ``capabilities`` is therefore the Surface's
    policy, looked up from ``scope`` and never composed here.
    """

    locator: str
    component: str
    scope: Scope
    capabilities: CapabilityPolicy

    def as_document(self) -> dict[str, object]:
        return {
            "locator": self.locator,
            "component": self.component,
            "scope": self.scope.value,
            "capabilities": self.capabilities.as_document(),
        }


@dataclass(frozen=True)
class DiscoveryReport:
    """What one scan produces. Every operation consumes this one primitive."""

    artifacts: tuple[InventoriedArtifact, ...] = ()
    containers: tuple[ArtifactContainer, ...] = ()
    observations: tuple[RuntimeComponentObservation, ...] = ()

    def as_document(self) -> dict[str, object]:
        """Every section is ordered, because a report is read, compared and diffed.

        A Locator alone does not order a report that composes several Surfaces: the same
        Locator can occur in more than one Scope. Each entry is therefore ordered by its Scope
        first, then its Locator, then what distinguishes two entries sharing both.
        """
        return {
            "artifacts": [
                entry.as_document()
                for entry in sorted(self.artifacts, key=lambda e: (e.scope, e.locator, e.type))
            ],
            "containers": [
                entry.as_document()
                for entry in sorted(self.containers, key=lambda e: (e.scope, e.locator))
            ],
            "observations": [
                entry.as_document()
                for entry in sorted(
                    self.observations, key=lambda e: (e.scope, e.locator, e.component)
                )
            ],
        }


@dataclass(frozen=True)
class HookDeclaration:
    """A hook declaration a scan read, with the digest that recognises it once it moves.

    A Locator is a position, so recognising the same declaration at a new one needs a value
    the declaration carries itself. That is the Declaration Digest, and it belongs to the lock
    rather than to a report: it resolves a lock-tracked hook, and an authored hook has no lock
    entry to resolve. Discovery computes it anyway, so that the reader of the lock never parses
    the container a second time and risks a second answer.
    """

    locator: str
    declaration_digest: str
    scope: Scope


@dataclass(frozen=True)
class Discovery:
    """One scan: the report it produced, the hook declarations standing behind its Container
    Inventory, and what it found wrong while producing them.

    ``hooks`` is deliberately outside ``report``, which is the serialised part.
    """

    report: DiscoveryReport
    diagnostics: tuple[Diagnostic, ...] = ()
    hooks: tuple[HookDeclaration, ...] = ()
