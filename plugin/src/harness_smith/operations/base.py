"""The operation contract every subcommand satisfies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from harness_smith.diagnostics import Diagnostic
from harness_smith.result import Change
from harness_smith.vocabulary import Mode

OperationKind = Literal["read", "write"]


@dataclass(frozen=True)
class OperationSpec:
    name: str
    kind: OperationKind
    summary: str

    @property
    def default_mode(self) -> Mode:
        """Dry-run is the default: a write operation plans until ``--apply`` says otherwise."""
        return Mode.READ if self.kind == "read" else Mode.PLAN


@dataclass(frozen=True)
class OperationRequest:
    repository_root: Path


@dataclass(frozen=True)
class OperationOutcome:
    data: Mapping[str, object]
    diagnostics: tuple[Diagnostic, ...] = ()
    changes: tuple[Change, ...] = ()


class Operation(ABC):
    spec: OperationSpec

    @abstractmethod
    def run(self, request: OperationRequest) -> OperationOutcome:
        """Produce this operation's data, diagnostics, and proposed changes."""

    @abstractmethod
    def render_text(self, data: Mapping[str, object]) -> str:
        """The human-readable body for the default output format."""
