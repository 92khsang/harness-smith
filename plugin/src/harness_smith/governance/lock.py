"""The governance lock: what the tool measured and computed.

`harness.lock.json` records where a non-authored artifact came from and the digest that was
approved for it. It is JSON, tool-authored, and regenerated rather than merged on a conflict,
which is only safe because nothing in it is a human choice: those live in the manifest.

`baselineSha256` is the approved drift baseline, the digest at the moment the content was last
generated, imported or adopted. It is not a current measurement. The digest of what is on disk
now is computed at scan time and never written here, so a lock diff shows change somebody
approved rather than change that merely happened.

The lock carries no timestamps, machine paths, user identity or session identifiers, for the
same reason: a diff that moves without the content moving is a diff nobody can read.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from harness_smith.governance.paths import normalised
from harness_smith.governance.shape import closed, mapping, one_of, required, text
from harness_smith.json_document import JsonDocumentState, own_repeated_names, parse_json_document
from harness_smith.text_file import TextFile, TextFileState

__all__ = ["LOCK", "Lock", "read_lock"]

LOCK = "harness.lock.json"

SCHEMA_VERSION = "schemaVersion"
ARTIFACTS = "artifacts"
TOP_LEVEL = (SCHEMA_VERSION, "standard", "entrypoint", ARTIFACTS)
STANDARD_KEYS = ("id", "version")
ENTRYPOINT_KEYS = ("runtime", "path", "template", "version")

PROVENANCES = ("generated", "imported", "adopted")
BASELINE = "baselineSha256"
ADOPTED_FROM = "adoptedFrom"

# The one descriptor shape every provenance carries, so an artifact keeps its origin after it
# has been adopted. `sourceUrl` and `license` describe an import and appear only there.
DESCRIPTOR_REQUIRED = ("source", "sourceVersion", "sha256")
DESCRIPTOR_KEYS = (*DESCRIPTOR_REQUIRED, "sourceRevision", "sourceUrl", "license")

ENTRY_KEYS = ("provenance", BASELINE, ADOPTED_FROM, "declarationDigest", *DESCRIPTOR_KEYS)


@dataclass(frozen=True)
class Lock:
    """The lock as read. Absent is a state: a repository with nothing non-authored in it has
    nothing to record."""

    present: bool = False
    schema_version: int = 0
    standard: Mapping[str, object] = field(default_factory=dict)
    entrypoint: Mapping[str, object] = field(default_factory=dict)
    artifacts: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    reason: str = ""

    @property
    def valid(self) -> bool:
        return self.present and not self.reason


def read_lock(file: TextFile) -> Lock:
    """Validate what was read from the lock's path, or say why it is not a lock.

    Whether there is a lock at all is what that read answered. Nothing at the path is a
    repository with nothing non-authored in it; anything else there is a lock, whether or not
    it turns out to be readable.
    """
    if file.state is TextFileState.ABSENT:
        return Lock()
    if file.state is TextFileState.UNREADABLE:
        return Lock(present=True, reason=file.reason)
    document = parse_json_document(file.text)
    if document.state is not JsonDocumentState.PARSED:
        return Lock(present=True, reason=document.reason)
    members = document.members
    repeated = own_repeated_names(members)
    reason = (
        (f"the lock declares `{repeated[0]}` more than once" if repeated else None)
        or closed(members, TOP_LEVEL, "the lock")
        or required(members, TOP_LEVEL, "the lock")
        or _version(members)
        or _object(members["standard"], STANDARD_KEYS, "the lock's `standard`")
        or _object(members["entrypoint"], ENTRYPOINT_KEYS, "the lock's `entrypoint`")
    )
    if reason:
        return Lock(present=True, reason=reason)
    entries = _artifacts(members[ARTIFACTS])
    if isinstance(entries, str):
        return Lock(present=True, reason=entries)
    version = members[SCHEMA_VERSION]
    assert isinstance(version, int)
    assert isinstance(members["standard"], dict)
    assert isinstance(members["entrypoint"], dict)
    return Lock(
        present=True,
        schema_version=version,
        standard=members["standard"],
        entrypoint=members["entrypoint"],
        artifacts=entries,
    )


def _version(members: Mapping[str, object]) -> str | None:
    version = members[SCHEMA_VERSION]
    if not isinstance(version, int) or isinstance(version, bool):
        return f"the lock has a `{SCHEMA_VERSION}` that is not an integer"
    return None


def _artifacts(value: object) -> Mapping[str, Mapping[str, object]] | str:
    reason = mapping(value, f"the lock's `{ARTIFACTS}`")
    if reason:
        return reason
    assert isinstance(value, dict)
    repeated = own_repeated_names(value)
    if repeated:
        return f"the lock names `{repeated[0]}` twice"
    entries: dict[str, Mapping[str, object]] = {}
    for path, entry in value.items():
        key = normalised(str(path))
        if key in entries:
            return f"the lock names `{key}` twice"
        read = _entry(key, entry)
        if isinstance(read, str):
            return read
        entries[key] = read
    return entries


def _entry(path: str, entry: object) -> Mapping[str, object] | str:
    """One artifact's provenance and the descriptor that goes with it.

    A `generated` or `imported` entry carries its descriptor at the top; an `adopted` one
    carries it under `adoptedFrom`, describing the state its local content diverged from, while
    its own baseline records the approved local content.
    """
    where = f"the lock entry for `{path}`"
    reason = (
        mapping(entry, where)
        or closed(entry, ENTRY_KEYS, where)  # type: ignore[arg-type]
        or required(entry, ("provenance", BASELINE), where)  # type: ignore[arg-type]
    )
    if reason:
        return reason
    assert isinstance(entry, dict)
    reason = (
        one_of(entry["provenance"], PROVENANCES, f"{where}'s `provenance`")
        or text(entry, (BASELINE, "declarationDigest"), where)
        or _descriptor(entry, where)
    )
    return reason if reason else entry


def _descriptor(entry: Mapping[str, object], where: str) -> str | None:
    if entry["provenance"] == "adopted":
        if ADOPTED_FROM not in entry:
            return f"{where} is adopted and is missing `{ADOPTED_FROM}`"
        return _object(entry[ADOPTED_FROM], DESCRIPTOR_KEYS, f"{where}'s `{ADOPTED_FROM}`", True)
    if ADOPTED_FROM in entry:
        return f"{where} is not adopted and carries `{ADOPTED_FROM}`"
    return _object(entry, DESCRIPTOR_KEYS, where, True, ENTRY_KEYS)


def _object(
    value: object,
    allowed: tuple[str, ...],
    where: str,
    descriptor: bool = False,
    keys: tuple[str, ...] | None = None,
) -> str | None:
    reason = mapping(value, where) or closed(value, keys or allowed, where)  # type: ignore[arg-type]
    if reason:
        return reason
    assert isinstance(value, dict)
    needed = DESCRIPTOR_REQUIRED if descriptor else allowed
    return required(value, needed, where) or text(value, needed, where)
