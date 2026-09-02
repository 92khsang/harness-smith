"""The operation registry.

``DECLARED_OPERATIONS`` is the full v1 vocabulary of command-line names, which the result
schema pins. ``REGISTRY`` holds the ones that are implemented; the two are deliberately
separate so a declared-but-unimplemented name is a usage error rather than a silent success.
"""

from __future__ import annotations

from collections.abc import Mapping

from harness_smith.operations.base import (
    Operation,
    OperationKind,
    OperationOutcome,
    OperationRequest,
    OperationSpec,
)
from harness_smith.operations.surface_audit import SurfaceAudit

__all__ = [
    "DECLARED_OPERATIONS",
    "REGISTRY",
    "Operation",
    "OperationKind",
    "OperationOutcome",
    "OperationRequest",
    "OperationSpec",
]

DECLARED_OPERATIONS: tuple[str, ...] = (
    "init",
    "surface-audit",
    "artifact-route",
    "artifact-manage",
    "entrypoint-manage",
    "harness-validate",
    "config-gc",
    "context-audit",
    "skill-stocktake",
    "skill-scout",
    "skill-create",
    "rules-distill",
)

_IMPLEMENTED: tuple[Operation, ...] = (SurfaceAudit(),)

REGISTRY: Mapping[str, Operation] = {operation.spec.name: operation for operation in _IMPLEMENTED}
