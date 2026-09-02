"""Rendering an OperationResult, one format per audience.

``--format json`` puts exactly one document on stdout and nothing else, so anything that is
not part of the document -- progress, prompts, tracebacks -- goes to stderr. The default text
format is separate and is the only one that renders prose on stdout.
"""

from __future__ import annotations

import json

from harness_smith.operations.base import Operation
from harness_smith.result import OperationResult

JSON = "json"
TEXT = "text"
FORMATS = (TEXT, JSON)


def render_json(result: OperationResult) -> str:
    return json.dumps(result.as_document(), ensure_ascii=False, indent=2) + "\n"


def render_text(result: OperationResult, operation: Operation | None = None) -> str:
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
    if operation is not None and result.data is not None:
        body = operation.render_text(result.data)
        if body:
            lines.append(body)
    return "\n".join(lines) + "\n"
