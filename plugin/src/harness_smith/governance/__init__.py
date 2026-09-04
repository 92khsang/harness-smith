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
from harness_smith.text_file import read_text_file
from harness_smith.vocabulary import Subject, SubjectKind

__all__ = ["LOCK", "MANIFEST", "Governance", "Lock", "Manifest", "read_governance"]


@dataclass(frozen=True)
class Governance:
    """Both files as read, and what was found wrong reading them."""

    manifest: Manifest
    lock: Lock
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def invalid(self) -> bool:
        """A governance file is there and is not one: it would not read, it would not parse,
        or it does not satisfy the schema.

        Absent is not this state — a repository that declared nothing has declared nothing —
        and neither is the presence of a diagnostic, which a later finding of another severity
        would also satisfy. This is the configuration error a run stops on.
        """
        return (self.manifest.present and not self.manifest.valid) or (
            self.lock.present and not self.lock.valid
        )


def read_governance(root: Path) -> Governance:
    """Read and validate both governance files of the repository at ``root``.

    Each file is opened once, and that open is what decides whether the file is there. Asking
    the filesystem first and reading afterwards would be two answers about two moments, and a
    path that is not a regular file would answer the first question with silence.
    """
    manifest = read_manifest(read_text_file(root / MANIFEST))
    lock = read_lock(read_text_file(root / LOCK))
    diagnostics = (
        *_finding("HS-MANIFEST-INVALID", MANIFEST, manifest.reason),
        *_finding("HS-LOCK-INVALID", LOCK, lock.reason),
    )
    return Governance(manifest, lock, diagnostics)


def _finding(code: str, locator: str, reason: str) -> tuple[Diagnostic, ...]:
    if not reason:
        return ()
    return (Diagnostic.of(code, Subject(SubjectKind.ARTIFACT, locator), message=reason),)
