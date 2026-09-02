"""surface-audit: a thin report over the shared discovery primitive."""

from __future__ import annotations

from collections.abc import Mapping

from harness_smith.operations.base import (
    Operation,
    OperationOutcome,
    OperationRequest,
    OperationSpec,
)

# The three parts of a Discovery Report, in the order they are reported.
SECTIONS: tuple[str, ...] = ("artifacts", "containers", "observations")


class SurfaceAudit(Operation):
    spec = OperationSpec(
        name="surface-audit",
        kind="read",
        summary="Inventory the harness artifacts, artifact containers, and runtime components "
        "of a repository.",
    )

    def run(self, request: OperationRequest) -> OperationOutcome:
        return OperationOutcome(data={section: [] for section in SECTIONS})

    def render_text(self, data: Mapping[str, object]) -> str:
        return "\n".join(f"  {section}: {len(_entries(data, section))}" for section in SECTIONS)


def _entries(data: Mapping[str, object], section: str) -> list[object]:
    value = data.get(section, [])
    return list(value) if isinstance(value, list) else []
