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

from harness_smith.artifacts import SCOPE_BY_LAYER, Scope, SettingsLayer

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


# The sources with one expected location. A collection that was asked for them answers for
# each, present or not, so that a collector that skipped one cannot read as a machine that had
# none. Drop-in documents are not among them: how many there are is what the directory says.
SINGULAR_SOURCES: tuple[EvidenceSource, ...] = (
    EvidenceSource.USER_SETTINGS,
    EvidenceSource.PROJECT_LOCAL_SETTINGS,
    EvidenceSource.MANAGED_POLICY_BASE,
    EvidenceSource.MANAGED_POLICY_DROPIN_DIRECTORY,
)


def eligible_dropin(locator: str) -> bool:
    """Whether the runtime would read this entry of the drop-in directory.

    "Claude Code ignores hidden files and files that don't end in `.json`". The listing keeps
    every entry that was seen, so what was observed and what was adopted stay separate answers;
    this is the rule that separates them.
    """
    name = locator.rsplit("/", 1)[-1]
    return name.endswith(".json") and not name.startswith(".")


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
        _check(self.locator, self.status, self.cause, self.scope, self.layer)
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
        _check(self.locator, self.status, self.cause, self.scope, self.layer)
        if self.entries and self.status is not EvidenceStatus.PRESENT:
            raise ValueError("a directory that was not observed holds no entries")


@dataclass(frozen=True)
class RuntimeEvidenceSnapshot:
    """Everything a collector observed for one run, and nothing about what to do with it.

    ``requested`` is what the collector was asked to observe, and every one of those sources
    answers for itself. Without it an empty snapshot would read as "every runtime source was
    checked and none exists", which is what a collector that failed to run also looks like, and
    a missed collection would pass as a clean machine.
    """

    requested: tuple[EvidenceSource, ...] = ()
    documents: tuple[EvidenceDocument, ...] = ()
    directories: tuple[EvidenceDirectory, ...] = ()

    def __post_init__(self) -> None:
        records: tuple[EvidenceDocument | EvidenceDirectory, ...] = (
            *self.documents,
            *self.directories,
        )
        observed = {record.source for record in records}
        missing = [source for source in self.requested if source not in observed]
        if missing:
            raise ValueError(f"the {missing[0].value} source was requested and never answered for")
        _one_record_each(self.documents, self.directories)
        _dropins_belong_to_their_directory(self.documents, self.directories)


@dataclass(frozen=True)
class DiscoveryRequest:
    """The roots a scan is pointed at, and the runtime evidence it was given.

    ``plugin_roots`` is a product input rather than runtime evidence: the caller names the
    plugins it wants scanned, and which plugins those are is not something the scan decides.
    """

    repository_root: Path
    plugin_roots: tuple[Path, ...] = ()
    runtime_evidence: RuntimeEvidenceSnapshot | None = None

    def __post_init__(self) -> None:
        """The roots are canonical, so how a caller happened to spell one cannot change the
        report: the same directory named twice, or named through ``x/../x``, is one root."""
        canonical = dict.fromkeys(sorted(root.resolve() for root in self.plugin_roots))
        object.__setattr__(self, "plugin_roots", tuple(canonical))


def _check(
    locator: str,
    status: EvidenceStatus,
    cause: EvidenceCause | None,
    scope: Scope,
    layer: SettingsLayer,
) -> None:
    """The invariants that keep "we looked and found nothing" distinguishable from the rest."""
    if not locator:
        raise ValueError("evidence keeps the Locator it was expected at, even when absent")
    if SCOPE_BY_LAYER[layer] != scope:
        raise ValueError(
            f"the {layer.value} layer is in {SCOPE_BY_LAYER[layer].value} scope, not {scope.value}"
        )
    unresolved = {EvidenceStatus.UNREADABLE, EvidenceStatus.UNSUPPORTED}
    if (cause is not None) is not (status in unresolved):
        raise ValueError("a cause says why a source yielded nothing, and only then")


def _one_record_each(
    documents: tuple[EvidenceDocument, ...], directories: tuple[EvidenceDirectory, ...]
) -> None:
    """One source is observed once. A repeat is two answers to one question, and nothing here
    says which of them the run actually saw."""
    records: tuple[EvidenceDocument | EvidenceDirectory, ...] = (*documents, *directories)
    singular = [record.source for record in records if record.source in SINGULAR_SOURCES]
    repeated = {source for source in singular if singular.count(source) > 1}
    if repeated:
        raise ValueError(f"the {sorted(repeated)[0].value} source is observed more than once")
    locators = [document.locator for document in documents]
    if len(set(locators)) != len(locators):
        raise ValueError("two documents were observed at one Locator")


def _dropins_belong_to_their_directory(
    documents: tuple[EvidenceDocument, ...], directories: tuple[EvidenceDirectory, ...]
) -> None:
    """A drop-in exists because a directory listing named it, so the two agree or neither is
    trustworthy: every entry the runtime would read has been read, and nothing was read that
    the listing never showed."""
    dropins = {
        document.locator
        for document in documents
        if document.source is EvidenceSource.MANAGED_POLICY_DROPIN
    }
    listed = [
        directory
        for directory in directories
        if directory.source is EvidenceSource.MANAGED_POLICY_DROPIN_DIRECTORY
    ]
    if not listed:
        if dropins:
            raise ValueError("a drop-in was observed without the directory that lists it")
        return
    directory = listed[0]
    if tuple(sorted(set(directory.entries))) != directory.entries:
        raise ValueError("a directory listing is ordered and holds each entry once")
    expected = {entry for entry in directory.entries if eligible_dropin(entry)}
    if dropins != expected:
        unread = sorted(expected - dropins)
        unlisted = sorted(dropins - expected)
        missing = unread[0] if unread else unlisted[0]
        raise ValueError(f"the drop-in listing and the documents disagree about {missing}")
