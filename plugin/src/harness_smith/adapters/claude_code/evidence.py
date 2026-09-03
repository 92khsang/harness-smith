"""Turning observed runtime evidence into the artifacts it declares.

The settings files the runtime reads outside a repository — the user's own, the project-local
overlay, and the administrator's policy files — are all hook containers of the same shape, so
they are read the same way. What separates them is the Scope they were found in and the
settings layer they belong to, and the collector recorded both.

This reads the snapshot and nothing else. It never opens the Locator a document names, because
the collector already observed what was there and reopening it would let the report describe
two different moments.

What comes out is a raw inventory: the declarations a readable file holds. It is not the policy
in force. The managed tier picks one of four ranked sources, a merge setting can change that,
and a policy helper can replace the lot for one session, so whether a declaration is in effect
is a projection made elsewhere, out of evidence this does not have.
"""

from __future__ import annotations

from dataclasses import dataclass

from harness_smith.adapters.claude_code import hooks as hook_container
from harness_smith.artifacts import (
    ArtifactContainer,
    ArtifactType,
    ContainerFormat,
    Discovery,
    DiscoveryReport,
    HookDeclaration,
    InventoriedArtifact,
    Representation,
)
from harness_smith.json_document import parse_json_bytes
from harness_smith.scan import EvidenceDocument, EvidenceStatus, RuntimeEvidenceSnapshot

__all__ = ["discover_evidence"]


@dataclass(frozen=True)
class _Read:
    container: ArtifactContainer
    artifacts: tuple[InventoriedArtifact, ...] = ()
    hooks: tuple[HookDeclaration, ...] = ()


def discover_evidence(snapshot: RuntimeEvidenceSnapshot) -> Discovery:
    """Every hook the observed documents declare, with the container each was declared in."""
    reads = [_read(document) for document in snapshot.documents if _observed(document)]
    return Discovery(
        report=DiscoveryReport(
            artifacts=tuple(entry for read in reads for entry in read.artifacts),
            containers=tuple(read.container for read in reads),
        ),
        hooks=tuple(entry for read in reads for entry in read.hooks),
    )


def _observed(document: EvidenceDocument) -> bool:
    """A source that was absent declares nothing. One that was there and could not be read is
    a container whose contents are unknown, which is not the same as an empty one."""
    return document.status in {EvidenceStatus.PRESENT, EvidenceStatus.UNREADABLE}


def _read(document: EvidenceDocument) -> _Read:
    if document.content is None:
        return _Read(_container(document, ()))
    found = hook_container.read(
        parse_json_bytes(document.content), document.locator, document.scope
    )
    artifacts = tuple(
        InventoriedArtifact.runtime_native(
            declaration.locator, ArtifactType.HOOK, document.scope, Representation.CONTAINER_ENTRY
        )
        for declaration in found.declarations
    )
    holds = tuple(declaration.locator for declaration in found.declarations)
    return _Read(_container(document, holds), artifacts, found.declarations)


def _container(document: EvidenceDocument, holds: tuple[str, ...]) -> ArtifactContainer:
    """A managed policy is spread across a base file and the drop-ins beside it, and each stays
    its own container: a declaration keeps the file it came from, and which of them the runtime
    would merge first is a question for whoever computes the effective policy."""
    return ArtifactContainer(
        document.locator, ContainerFormat.JSON, document.scope, document.layer, holds
    )
