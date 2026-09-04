"""The governance lock: what the tool measured and computed.

`harness.lock.json` records where a non-authored artifact came from and the digest that was
approved for it. It is JSON, tool-authored, and regenerated rather than merged on a conflict,
which is only safe because nothing in it is a human choice: those live in the manifest.

`baselineSha256` is the approved drift baseline, the digest at the moment the content was last
generated, imported or adopted. It is not a current measurement, and no current measurement is
ever stored here, so a lock diff shows change somebody approved rather than change that merely
happened. Computing the digest of what is on disk now, and comparing it against this baseline,
is #36's.

The lock carries no timestamps, machine paths, user identity or session identifiers, for the
same reason: a diff that moves without the content moving is a diff nobody can read.

What an entry may hold depends on its provenance, so each provenance has its own closed shape
rather than one shape loose enough for all three. `sourceUrl` and `license` describe an import,
so a `generated` entry refuses them; an `adopted` entry keeps its origin under `adoptedFrom`
rather than beside its own baseline, where the two would be indistinguishable, and that origin
may have been an import, so the seed admits them too — adopting a file must not lose the URL
and licence it was taken under.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from harness_smith.governance.paths import normalised, refused
from harness_smith.governance.shape import Field, Kind, Shape
from harness_smith.json_document import JsonDocumentState, own_repeated_names, parse_json_document
from harness_smith.text_file import TextFile, TextFileState

__all__ = ["LOCK", "Lock", "read_lock"]

LOCK = "harness.lock.json"

SCHEMA_VERSION = "schemaVersion"

# The one version this tool reads, for the reason the manifest reads one: a version field says
# the rules can change, and reading a later file under these rules is guessing that they did not.
SUPPORTED_VERSION = 1

ARTIFACTS = "artifacts"
TOP_LEVEL = (SCHEMA_VERSION, "standard", "entrypoint", ARTIFACTS)

STANDARD = Shape((Field("id", required=True), Field("version", required=True)))

# `path` names the entry point inside this repository. It is refused where it could name a
# file anywhere else, and kept as written; #18 normalises it when it compares the entry point.
ENTRYPOINT = Shape(
    (
        Field("runtime", required=True),
        Field("path", Kind.PATH, required=True),
        Field("template", required=True),
        Field("version", required=True),
    )
)

PROVENANCES = ("generated", "imported", "adopted")
PROVENANCE = "provenance"
BASELINE = "baselineSha256"
ADOPTED_FROM = "adoptedFrom"

# The descriptor every provenance carries, so an artifact keeps its origin after adoption.
DESCRIPTOR: tuple[Field, ...] = (
    Field("source", required=True),
    Field("sourceVersion", required=True),
    Field("sha256", required=True),
    Field("sourceRevision"),
)
IMPORT_DESCRIPTOR: tuple[Field, ...] = (*DESCRIPTOR, Field("sourceUrl"), Field("license"))

# A hook fragment's entry carries the digest of the declaration alone, which is what recognises
# it after it has moved inside its container.
COMMON: tuple[Field, ...] = (
    Field(PROVENANCE, required=True, values=PROVENANCES),
    Field(BASELINE, required=True),
    Field("declarationDigest"),
)

SEED = Shape(IMPORT_DESCRIPTOR)

ENTRY_SHAPES: Mapping[str, Shape] = {
    "generated": Shape((*COMMON, *DESCRIPTOR)),
    "imported": Shape((*COMMON, *IMPORT_DESCRIPTOR)),
    "adopted": Shape((*COMMON, Field(ADOPTED_FROM, Kind.ENTRY, required=True, shape=SEED))),
}


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
        or _closed(members)
        or _missing(members)
        or _version(members)
        or STANDARD.check(members["standard"], "the lock's `standard`")
        or ENTRYPOINT.check(members["entrypoint"], "the lock's `entrypoint`")
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


def _closed(members: Mapping[str, object]) -> str | None:
    unknown = sorted(set(members) - set(TOP_LEVEL))
    return f"the lock has an unknown key `{unknown[0]}`" if unknown else None


def _missing(members: Mapping[str, object]) -> str | None:
    missing = [name for name in TOP_LEVEL if name not in members]
    return f"the lock is missing `{missing[0]}`" if missing else None


def _version(members: Mapping[str, object]) -> str | None:
    version = members[SCHEMA_VERSION]
    if isinstance(version, bool) or not isinstance(version, int):
        return f"the lock has a `{SCHEMA_VERSION}` that is not an integer"
    if version != SUPPORTED_VERSION:
        return (
            f"the lock declares `{SCHEMA_VERSION}` {version}, "
            f"and this tool reads version {SUPPORTED_VERSION}"
        )
    return None


def _artifacts(value: object) -> Mapping[str, Mapping[str, object]] | str:
    where = f"the lock's `{ARTIFACTS}`"
    if not isinstance(value, dict):
        return f"{where} is not a mapping"
    repeated = own_repeated_names(value)
    if repeated:
        return f"the lock names `{repeated[0]}` twice"
    entries: dict[str, Mapping[str, object]] = {}
    for path, entry in value.items():
        reason = refused(path, where, locator=True)
        if reason:
            return reason
        assert isinstance(path, str)
        key = normalised(path)
        if key in entries:
            return f"the lock names `{key}` twice"
        read = _entry(key, entry)
        if isinstance(read, str):
            return read
        entries[key] = read
    return entries


def _entry(path: str, entry: object) -> Mapping[str, object] | str:
    """One artifact's provenance and the descriptor that goes with it.

    The provenance decides which shape the rest of the entry has, so it is read first: a
    `generated` or `imported` entry carries its descriptor at the top, and an `adopted` one
    carries it under `adoptedFrom`, describing the state its local content diverged from while
    its own baseline records the approved local content.
    """
    where = f"the lock entry for `{path}`"
    if not isinstance(entry, dict):
        return f"{where} is not a mapping"
    if PROVENANCE not in entry:
        return f"{where} is missing `{PROVENANCE}`"
    provenance = entry[PROVENANCE]
    shape = ENTRY_SHAPES.get(provenance) if isinstance(provenance, str) else None
    if shape is None:
        allowed = ", ".join(PROVENANCES)
        return f"{where}'s `{PROVENANCE}` is `{provenance}`, which is not one of {allowed}"
    reason = shape.check(entry, where)
    return reason if reason else entry
