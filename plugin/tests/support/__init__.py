"""Test-only helpers for driving the command-line tool and inspecting its output."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PLUGIN_ROOT / "resources" / "schemas" / "operation-result.schema.json"
BOOTSTRAP_PATH = PLUGIN_ROOT / "bin" / "harness-smith"


@dataclass(frozen=True)
class CliRun:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def document(self) -> dict[str, Any]:
        """Every document a run emits is checked against the schema, not only the ones a
        test remembers to check."""
        parsed: dict[str, Any] = json.loads(self.stdout)
        validate_document(parsed)
        return parsed

    @property
    def diagnostic_codes(self) -> list[str]:
        codes: list[str] = [entry["code"] for entry in self.document["diagnostics"]]
        return codes


def run_cli(*arguments: str, cwd: Path) -> CliRun:
    """Run the tool the way automation does: as a subprocess, observed at its boundary.

    ``-P`` mirrors the launcher: the working directory is the repository under audit and must
    not reach ``sys.path``.
    """
    completed = subprocess.run(
        [sys.executable, "-P", "-m", "harness_smith", *arguments],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=False,
    )
    return CliRun(completed.returncode, completed.stdout, completed.stderr)


def make_repository(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch=main", str(path)],
        check=True,
        capture_output=True,
    )
    return path


def snapshot_tree(root: Path) -> dict[str, str]:
    """Digest every path under ``root`` except version-control internals."""
    entries: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if ".git" in relative.parts:
            continue
        entries[relative.as_posix()] = (
            "<dir>" if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest()
        )
    return entries


@cache
def schema() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return loaded


def validate_document(document: object) -> None:
    validator_class = jsonschema.validators.validator_for(schema())
    validator_class.check_schema(schema())
    validator_class(schema()).validate(document)


def sole_json_document(stdout: str) -> dict[str, Any]:
    """Parse stdout and assert it holds exactly one JSON document and nothing else."""
    document, end = json.JSONDecoder().raw_decode(stdout)
    assert stdout[end:].strip() == "", f"stdout carried trailing output: {stdout[end:]!r}"
    parsed: dict[str, Any] = document
    validate_document(parsed)
    return parsed
