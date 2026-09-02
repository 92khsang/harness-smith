"""Rendering an OperationResult, one format per audience.

``--format json`` puts exactly one document on stdout and nothing else; everything a person
would want to read goes to stderr instead. The default text format is separate.
"""

from __future__ import annotations

import json

from harness_smith.operations.base import Operation, OperationOutcome
from harness_smith.result import OperationResult

JSON = "json"
TEXT = "text"
FORMATS = (TEXT, JSON)


def render_json(result: OperationResult) -> str:
    return json.dumps(result.as_document(), ensure_ascii=False, indent=2) + "\n"


def render_text(
    result: OperationResult,
    operation: Operation | None = None,
    outcome: OperationOutcome | None = None,
) -> str:
    lines = [f"{result.operation or 'harness-smith'}: {result.status.value}"]
    for diagnostic in result.sorted_diagnostics():
        locator = diagnostic.subject.locator
        where = f" [{locator}]" if locator else ""
        lines.append(f"{diagnostic.severity.value}  {diagnostic.code}{where}  {diagnostic.message}")
        lines.append(f"  remediation: {diagnostic.spec.remediation}")
        if diagnostic.affected:
            lines.extend(f"    affected: {locator}" for locator in diagnostic.affected)
    for change in result.sorted_changes():
        lines.append(f"{change.action.value}  {change.path}")
    if operation is not None and outcome is not None:
        body = operation.render_text(outcome)
        if body:
            lines.append(body)
    return "\n".join(lines) + "\n"
