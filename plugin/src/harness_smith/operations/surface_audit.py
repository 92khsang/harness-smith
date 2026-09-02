"""surface-audit: a thin report over the shared discovery primitive."""

from __future__ import annotations

from harness_smith.operations.base import (
    Operation,
    OperationOutcome,
    OperationRequest,
    OperationSpec,
)

EMPTY_REPORT: dict[str, object] = {"artifacts": [], "containers": [], "observations": []}


class SurfaceAudit(Operation):
    spec = OperationSpec(
        name="surface-audit",
        kind="read",
        summary="Inventory the harness artifacts, artifact containers, and runtime components "
        "of a repository.",
    )

    def run(self, request: OperationRequest) -> OperationOutcome:
        return OperationOutcome(data=dict(EMPTY_REPORT))

    def render_text(self, outcome: OperationOutcome) -> str:
        counts = {section: len(_entries(outcome, section)) for section in EMPTY_REPORT}
        return "\n".join(f"  {section}: {count}" for section, count in counts.items())


def _entries(outcome: OperationOutcome, section: str) -> list[object]:
    value = outcome.data.get(section, [])
    return list(value) if isinstance(value, list) else []
