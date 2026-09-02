"""The OperationResult envelope every operation emits."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from harness_smith.diagnostics import Diagnostic
from harness_smith.vocabulary import (
    EXIT_CODE_BY_STATUS,
    OUTCOME_PRIORITY,
    SCHEMA_VERSION,
    SEVERITY_ORDER,
    STATUS_BY_EXIT_CODE,
    ExitCode,
    Mode,
    Status,
)

__all__ = [
    "Change",
    "ChangeAction",
    "OperationResult",
    "Patch",
    "PatchFormat",
    "resolve_status",
]


class ChangeAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class PatchFormat(StrEnum):
    UNIFIED = "unified"
    JSON_POINTER_OPS = "json-pointer-ops"


@dataclass(frozen=True)
class Patch:
    """A reviewed diff. There is no format that omits the content."""

    format: PatchFormat
    content: str | tuple[Mapping[str, object], ...]

    def as_document(self) -> dict[str, object]:
        content: object = (
            self.content if isinstance(self.content, str) else [dict(op) for op in self.content]
        )
        return {"format": self.format.value, "content": content}


@dataclass(frozen=True)
class Change:
    path: str
    action: ChangeAction
    patch: Patch
    digest_before: str | None
    digest_after: str | None
    applied: bool = False

    def as_document(self) -> dict[str, object]:
        return {
            "path": self.path,
            "action": self.action.value,
            "digestBefore": self.digest_before,
            "digestAfter": self.digest_after,
            "applied": self.applied,
            "patch": self.patch.as_document(),
        }


def resolve_status(diagnostics: Sequence[Diagnostic]) -> Status:
    """The run's outcome is the highest-priority exit effect among its diagnostics."""
    effects = {diagnostic.exit_effect for diagnostic in diagnostics}
    for candidate in OUTCOME_PRIORITY:
        if candidate in effects:
            return STATUS_BY_EXIT_CODE[candidate]
    return Status.OK


def _diagnostic_sort_key(diagnostic: Diagnostic) -> tuple[int, str, str, str]:
    return (
        SEVERITY_ORDER[diagnostic.severity],
        diagnostic.code,
        diagnostic.subject.kind.value,
        diagnostic.subject.locator or "",
    )


@dataclass(frozen=True)
class OperationResult:
    operation: str | None
    mode: Mode
    diagnostics: tuple[Diagnostic, ...] = ()
    changes: tuple[Change, ...] = field(default=())
    data: Mapping[str, object] | None = None

    @property
    def status(self) -> Status:
        return resolve_status(self.diagnostics)

    @property
    def exit_code(self) -> ExitCode:
        return EXIT_CODE_BY_STATUS[self.status]

    def sorted_diagnostics(self) -> list[Diagnostic]:
        """Severity descending, then code, then subject."""
        return sorted(self.diagnostics, key=_diagnostic_sort_key)

    def sorted_changes(self) -> list[Change]:
        return sorted(self.changes, key=lambda change: change.path)

    def as_document(self) -> dict[str, object]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "operation": self.operation,
            "mode": self.mode.value,
            "status": self.status.value,
            "diagnostics": [diagnostic.as_document() for diagnostic in self.sorted_diagnostics()],
            "changes": [change.as_document() for change in self.sorted_changes()],
            "data": dict(self.data) if self.data is not None else None,
        }
