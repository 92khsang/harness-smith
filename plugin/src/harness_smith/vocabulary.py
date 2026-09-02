"""The vocabulary of the OperationResult envelope: modes, statuses, exit codes, subjects.

These terms have one home so that a name has one import path. The envelope that carries them
lives in ``result``, which depends on this module and on ``diagnostics``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum

SCHEMA_VERSION = 1


class Mode(StrEnum):
    READ = "read"
    PLAN = "plan"
    APPLY = "apply"


class Status(StrEnum):
    OK = "ok"
    VIOLATIONS = "violations"
    USAGE_ERROR = "usage-error"
    ENVIRONMENT_ERROR = "environment-error"


class ExitCode(IntEnum):
    SUCCESS = 0
    VIOLATIONS = 1
    USAGE_ERROR = 2
    ENVIRONMENT_ERROR = 3


STATUS_BY_EXIT_CODE: dict[ExitCode, Status] = {
    ExitCode.SUCCESS: Status.OK,
    ExitCode.VIOLATIONS: Status.VIOLATIONS,
    ExitCode.USAGE_ERROR: Status.USAGE_ERROR,
    ExitCode.ENVIRONMENT_ERROR: Status.ENVIRONMENT_ERROR,
}

EXIT_CODE_BY_STATUS: dict[Status, ExitCode] = {
    status: code for code, status in STATUS_BY_EXIT_CODE.items()
}

# A usage error short-circuits before any check runs, so it outranks everything. Among runs
# that did execute, an environment failure outranks a policy violation: a run that could not
# complete its checks cannot claim its violation list is complete.
OUTCOME_PRIORITY: tuple[ExitCode, ...] = (
    ExitCode.USAGE_ERROR,
    ExitCode.ENVIRONMENT_ERROR,
    ExitCode.VIOLATIONS,
    ExitCode.SUCCESS,
)


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


SEVERITY_ORDER: dict[Severity, int] = {
    Severity.ERROR: 0,
    Severity.WARNING: 1,
    Severity.INFO: 2,
}


class SubjectKind(StrEnum):
    ARTIFACT = "artifact"
    CONTAINER = "container"
    SURFACE = "surface"
    RELATION = "relation"
    ENVIRONMENT = "environment"


@dataclass(frozen=True)
class Subject:
    """What a diagnostic is about. ``locator`` is null for an environment finding."""

    kind: SubjectKind
    locator: str | None = None

    def as_document(self) -> dict[str, object]:
        return {"kind": self.kind.value, "locator": self.locator}


ENVIRONMENT_SUBJECT = Subject(SubjectKind.ENVIRONMENT, None)
