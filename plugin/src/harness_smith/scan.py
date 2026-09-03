"""What one scan is asked to look at.

A scan reads the roots it is pointed at and, where someone asked for it, a snapshot of runtime
evidence collected before the scan began. It never consults the ambient environment itself: no
``HOME``, no system policy directory, no registry. Two things follow from that. An offline run
cannot depend on the machine it ran on, and a scan is reproducible from its inputs alone, which
is what makes a fixture a real substitute for a machine.

Asking for runtime evidence and observing it are different events, and the snapshot keeps them
apart. ``runtime_evidence`` is ``None`` when nobody asked. A snapshot that was collected says,
per source, whether the source was there, was missing, could not be read, or is not something a
static scan can reach on this platform — and an expected source that is missing keeps the
Locator it was expected at, because "we looked and found nothing" is not "we never looked".

A snapshot carries the bytes that were observed rather than the paths to read them from. A
scan that re-opened a path could disagree with the collector about what is there, and the
report would then describe a state that never existed at one moment.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from harness_smith.artifacts import Scope

__all__ = [
    "DiscoveryRequest",
    "EvidenceCause",
    "EvidenceDirectory",
    "EvidenceDocument",
    "EvidenceSource",
    "EvidenceStatus",
    "RuntimeEvidenceSnapshot",
    "SettingsLayer",
]


class EvidenceStatus(StrEnum):
    """What the collector found when it looked. ``UNREADABLE`` is never collapsed into
    ``ABSENT``: one says the source is not there, the other says it is there and we could not
    say what it holds, and they call for different repairs."""

    PRESENT = "present"
    ABSENT = "absent"
    UNREADABLE = "unreadable"
    UNSUPPORTED = "unsupported"


class EvidenceCause(StrEnum):
    """Why a source yielded nothing, normalised.

    A raw OS error string is a message, not a contract: it varies by platform, locale and
    libc. These are the causes a caller can branch on.
    """

    PERMISSION_DENIED = "permission-denied"
    NOT_A_FILE = "not-a-file"
    NOT_A_DIRECTORY = "not-a-directory"
    READ_FAILED = "read-failed"
    DELIVERY_NOT_FILE_BASED = "delivery-not-file-based"
    PLATFORM_UNSUPPORTED = "platform-unsupported"


class EvidenceSource(StrEnum):
    """A runtime source a scan cannot reach on its own, named by what it is rather than by the
    path it happens to have on one machine."""

    USER_SETTINGS = "user-settings"
    PROJECT_LOCAL_SETTINGS = "project-local-settings"
    MANAGED_POLICY_BASE = "managed-policy-base"
    MANAGED_POLICY_DROPIN = "managed-policy-dropin"
    MANAGED_POLICY_DROPIN_DIRECTORY = "managed-policy-dropin-directory"


class SettingsLayer(StrEnum):
    """Which settings layer a file belongs to, which is a different question from Scope.

    Scope says which project a file affects and where it sits in ownership. The layer says
    whether it is settings a project shares, a personal overlay, a user's own global
    configuration, or an administrator's policy. Neither answers the other, and neither
    changes the Capability Policy of the Surface, which is a function of Scope alone.
    """

    PROJECT = "project"
    PROJECT_LOCAL = "project-local"
    USER = "user"
    POLICY = "policy"


@dataclass(frozen=True)
class EvidenceDocument:
    """One observed runtime source, and what was in it at the moment it was observed."""

    source: EvidenceSource
    scope: Scope
    layer: SettingsLayer
    locator: str
    status: EvidenceStatus
    content: bytes | None = None
    cause: EvidenceCause | None = None

    def __post_init__(self) -> None:
        _check(self.locator, self.status, self.cause)
        if (self.content is not None) is not (self.status is EvidenceStatus.PRESENT):
            raise ValueError(
                "content is exactly what was observed, so only a present source has it"
            )


@dataclass(frozen=True)
class EvidenceDirectory:
    """A directory a source is spread across, and the entries observed in it.

    The drop-in directory is a source in its own right: whether it was missing, unreadable, or
    present and empty are three different answers, and the entries it held are what the
    documents beside it can be checked against.
    """

    source: EvidenceSource
    scope: Scope
    layer: SettingsLayer
    locator: str
    status: EvidenceStatus
    entries: tuple[str, ...] = ()
    cause: EvidenceCause | None = None

    def __post_init__(self) -> None:
        _check(self.locator, self.status, self.cause)
        if self.entries and self.status is not EvidenceStatus.PRESENT:
            raise ValueError("a directory that was not observed holds no entries")


@dataclass(frozen=True)
class RuntimeEvidenceSnapshot:
    """Everything a collector observed for one run, and nothing about what to do with it."""

    documents: tuple[EvidenceDocument, ...] = ()
    directories: tuple[EvidenceDirectory, ...] = ()


@dataclass(frozen=True)
class DiscoveryRequest:
    """The roots a scan is pointed at, and the runtime evidence it was given.

    ``plugin_roots`` is a product input rather than runtime evidence: the caller names the
    plugins it wants scanned, and which plugins those are is not something the scan decides.
    """

    repository_root: Path
    plugin_roots: tuple[Path, ...] = ()
    runtime_evidence: RuntimeEvidenceSnapshot | None = None


def _check(locator: str, status: EvidenceStatus, cause: EvidenceCause | None) -> None:
    """The invariants that keep "we looked and found nothing" distinguishable from the rest."""
    if not locator:
        raise ValueError("evidence keeps the Locator it was expected at, even when absent")
    unresolved = {EvidenceStatus.UNREADABLE, EvidenceStatus.UNSUPPORTED}
    if (cause is not None) is not (status in unresolved):
        raise ValueError("a cause says why a source yielded nothing, and only then")
