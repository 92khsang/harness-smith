"""The repository's governance state: what a person declared, and what the tool measured.

Two files, split by who decides the value. The manifest holds policy somebody wrote down; the
lock holds what the tool computed. Neither being present is an ordinary state — a repository
that has declared nothing has declared nothing — while one that is present and unreadable is a
usage error, because every later answer about authority or provenance would be built on a file
nobody could read.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from harness_smith.diagnostics import Diagnostic
from harness_smith.governance.lock import LOCK, Lock, read_lock
from harness_smith.governance.manifest import MANIFEST, Manifest, read_manifest
from harness_smith.json_document import read_json_document
from harness_smith.vocabulary import Subject, SubjectKind
from harness_smith.yaml_document import read_yaml_document

__all__ = ["LOCK", "MANIFEST", "Governance", "Lock", "Manifest", "read_governance"]


@dataclass(frozen=True)
class Governance:
    """Both files as read, and what was found wrong reading them."""

    manifest: Manifest
    lock: Lock
    diagnostics: tuple[Diagnostic, ...] = ()


def read_governance(root: Path) -> Governance:
    """Read and validate both governance files of the repository at ``root``."""
    manifest_path = root / MANIFEST
    lock_path = root / LOCK
    manifest = read_manifest(read_yaml_document(manifest_path), manifest_path.is_file())
    lock = read_lock(read_json_document(lock_path), lock_path.is_file())
    diagnostics = (
        *_finding("HS-MANIFEST-INVALID", MANIFEST, manifest.reason),
        *_finding("HS-LOCK-INVALID", LOCK, lock.reason),
    )
    return Governance(manifest, lock, diagnostics)


def _finding(code: str, locator: str, reason: str) -> tuple[Diagnostic, ...]:
    if not reason:
        return ()
    return (Diagnostic.of(code, Subject(SubjectKind.ARTIFACT, locator), message=reason),)
