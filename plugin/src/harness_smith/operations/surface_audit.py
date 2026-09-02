"""surface-audit: a thin report over the shared discovery primitive."""

from __future__ import annotations

from collections.abc import Mapping

from harness_smith.adapters import claude_code
from harness_smith.operations.base import (
    Operation,
    OperationOutcome,
    OperationRequest,
    OperationSpec,
)

# The three parts of a Discovery Report, in report order, with the columns each of a section's
# entries is printed as. Every section ends with its Locator, so the ragged column is the last.
SECTIONS: Mapping[str, tuple[str, ...]] = {
    "artifacts": ("type", "scope", "locator"),
    "containers": ("format", "locator"),
    "observations": ("component", "locator"),
}

COLUMN_WIDTH = 16


class SurfaceAudit(Operation):
    spec = OperationSpec(
        name="surface-audit",
        kind="read",
        summary="Inventory the harness artifacts, artifact containers, and runtime components "
        "of a repository.",
    )

    def run(self, request: OperationRequest) -> OperationOutcome:
        discovery = claude_code.discover(request.repository_root)
        return OperationOutcome(
            data=discovery.report.as_document(), diagnostics=discovery.diagnostics
        )

    def render_text(self, data: Mapping[str, object]) -> str:
        lines: list[str] = []
        for section, columns in SECTIONS.items():
            entries = _entries(data, section)
            lines.append(f"  {section}: {len(entries)}")
            lines.extend(f"    {_summarise(columns, entry)}" for entry in entries)
        return "\n".join(lines)


def _entries(data: Mapping[str, object], section: str) -> list[object]:
    value = data.get(section, [])
    return list(value) if isinstance(value, list) else []


def _summarise(columns: tuple[str, ...], entry: object) -> str:
    if not isinstance(entry, Mapping):
        return str(entry)
    return "".join(f"{entry.get(name, '')!s:<{COLUMN_WIDTH}}" for name in columns).rstrip()
