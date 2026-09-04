"""The governance manifest: the policy statements a person wrote down.

`harness.manifest.yaml` carries Management Authority, update policy, and the Consumer and
Writer relations somebody declared. Everything in it is a human choice, which is why it is
YAML, hand-editable and comment-bearing, and why the tool never writes it as a side effect.

What the tool computes about the same artifacts — provenance, where content came from, and the
approved drift baseline — lives in the lock instead. Splitting them by who decides the value is
what keeps a regenerated lock from overwriting a decision, and a hand edit from claiming a
measurement.

The key sets are closed at every level and every field is typed. An unknown key is a mistake
somebody made rather than an extension point, and a field of the wrong type would be read as a
policy nobody wrote: a `managed-by` naming plugin `3` says nothing about who may write a file.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from harness_smith.governance.paths import normalised, refused
from harness_smith.governance.shape import Field, Kind, Shape, listed
from harness_smith.text_file import TextFile, TextFileState
from harness_smith.yaml_document import YamlDocumentState, parse_yaml_document

__all__ = ["MANIFEST", "Manifest", "read_manifest"]

MANIFEST = "harness.manifest.yaml"

SCHEMA_VERSION = "schemaVersion"

# The one version this tool reads. A file that declares another version is refused rather than
# read under these rules: the version field exists to say the rules changed, and guessing that
# they did not is how a later schema's file is silently misread.
SUPPORTED_VERSION = 1

SECTIONS = ("authority", "consumers", "writers")
TOP_LEVEL = (SCHEMA_VERSION, *SECTIONS)

AUTHORITY_VALUES = ("local", "harness-smith")
UPDATE_POLICIES = ("pinned", "local")
BINDINGS = ("literal-path", "non-literal")
MODES = ("regenerate", "append", "in-place-update")
LOCATOR_TYPES = ("contains-literal-path", "absent-literal-path", "contains-text")

MANAGED_BY = Shape((Field("plugin", required=True), Field("operation")))

# `seed` names the file in the plugin the adopted content was taken from, relative to that
# plugin's root at the recorded revision. It is refused where it could name a file anywhere
# else, and kept as written; #8 and #13 normalise it when they resolve it against the plugin.
ADOPTED_FROM = Shape(
    (
        Field("plugin", required=True),
        Field("version", required=True),
        Field("source-revision", required=True),
        Field("seed", Kind.PATH, required=True),
    )
)

AUTHORITY = Shape(
    (
        Field("authority", values=AUTHORITY_VALUES),
        Field("managed-by", Kind.ENTRY, shape=MANAGED_BY),
        Field("updatePolicy", values=UPDATE_POLICIES),
        Field("adopted-from", Kind.ENTRY, shape=ADOPTED_FROM),
        Field("rationale"),
    )
)

# `path` is relative to the plugin root at the recorded revision rather than to this
# repository. It is refused where it could name a file outside that root, and kept as written;
# #13 normalises it when it resolves the evidence against the installed plugin.
LOCATOR = Shape((Field("type", required=True, values=LOCATOR_TYPES), Field("value", required=True)))
EVIDENCE = Shape(
    (
        Field("path", Kind.PATH, required=True),
        Field("locator", Kind.ENTRY, required=True, shape=LOCATOR),
    )
)

RESOLUTION = Shape(
    (Field("kind", required=True), Field("confirmed-by", required=True), Field("rationale"))
)

CONSUMER = Shape(
    (
        Field("plugin", required=True),
        Field("version", required=True),
        Field("consumer", required=True),
        Field("binding", required=True, values=BINDINGS),
        Field("evidence", Kind.ENTRY, required=True, shape=EVIDENCE),
        Field("source-revision"),
        Field("resolution", Kind.ENTRY, shape=RESOLUTION),
        Field("rationale"),
    )
)

WRITER = Shape(
    (
        Field("plugin", required=True),
        Field("version", required=True),
        Field("writer", required=True),
        Field("mode", required=True, values=MODES),
        Field("evidence", Kind.ENTRY, required=True, shape=EVIDENCE),
        Field("confirmed-by", required=True),
        Field("source-revision"),
        Field("rationale"),
    )
)

RELATIONS: Mapping[str, Shape] = {"consumers": CONSUMER, "writers": WRITER}


@dataclass(frozen=True)
class Manifest:
    """The manifest as read. Absent is a state, not a failure: a repository that has declared
    nothing is a repository that has declared nothing."""

    present: bool = False
    schema_version: int = 0
    authority: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    consumers: Mapping[str, list[object]] = field(default_factory=dict)
    writers: Mapping[str, list[object]] = field(default_factory=dict)
    reason: str = ""

    @property
    def valid(self) -> bool:
        return self.present and not self.reason


def read_manifest(file: TextFile) -> Manifest:
    """Validate what was read from the manifest's path, or say why it is not a manifest.

    Whether there is a manifest at all is what that read answered. Nothing at the path is a
    repository that declared nothing; anything else there is a manifest, whether or not it
    turns out to be readable.
    """
    if file.state is TextFileState.ABSENT:
        return Manifest()
    if file.state is TextFileState.UNREADABLE:
        return Manifest(present=True, reason=file.reason)
    document = parse_yaml_document(file.text)
    if document.state is not YamlDocumentState.PARSED:
        return Manifest(present=True, reason=document.reason)
    members = document.members
    reason = _closed(members) or _version(members)
    if reason:
        return Manifest(present=True, reason=reason)
    sections: dict[str, dict[str, object]] = {}
    for name in SECTIONS:
        read = _section(members, name)
        if isinstance(read, str):
            return Manifest(present=True, reason=read)
        sections[name] = read
    reason = _entries(sections)
    version = members[SCHEMA_VERSION]
    assert isinstance(version, int)
    return Manifest(
        present=True,
        schema_version=version,
        authority=_typed(sections["authority"]),
        consumers=_lists(sections["consumers"]),
        writers=_lists(sections["writers"]),
        reason=reason or "",
    )


def _closed(members: Mapping[str, object]) -> str | None:
    unknown = sorted(set(members) - set(TOP_LEVEL))
    return f"the manifest has an unknown key `{unknown[0]}`" if unknown else None


def _version(members: Mapping[str, object]) -> str | None:
    if SCHEMA_VERSION not in members:
        return f"the manifest is missing `{SCHEMA_VERSION}`"
    version = members[SCHEMA_VERSION]
    if isinstance(version, bool) or not isinstance(version, int):
        return f"the manifest has a `{SCHEMA_VERSION}` that is not an integer"
    if version != SUPPORTED_VERSION:
        return (
            f"the manifest declares `{SCHEMA_VERSION}` {version}, "
            f"and this tool reads version {SUPPORTED_VERSION}"
        )
    return None


def _section(members: Mapping[str, object], name: str) -> dict[str, object] | str:
    """One section's entries, keyed by the one spelling paths are compared by."""
    value = members.get(name)
    if value is None:
        return {}
    where = f"the `{name}` section"
    if not isinstance(value, dict):
        return f"{where} is not a mapping"
    entries: dict[str, object] = {}
    for path, entry in value.items():
        reason = refused(path, where)
        if reason:
            return reason
        assert isinstance(path, str)
        key = normalised(path)
        if key in entries:
            return f"{where} names `{key}` twice"
        entries[key] = entry
    return entries


def _entries(sections: Mapping[str, dict[str, object]]) -> str | None:
    for path, entry in sections["authority"].items():
        reason = _authority(path, entry)
        if reason:
            return reason
    for name, shape in RELATIONS.items():
        for path, entry in sections[name].items():
            where = f"the `{name}` entry for `{path}`"
            reason = listed(entry, where)
            if reason:
                return reason
            assert isinstance(entry, list)
            for item in entry:
                reason = shape.check(item, where)
                if reason:
                    return reason
    return None


def _authority(path: str, entry: object) -> str | None:
    """Exactly one of `authority` and `managed-by`: an entry that says both, or neither, has
    not said who may write the file."""
    where = f"the `authority` entry for `{path}`"
    reason = AUTHORITY.check(entry, where)
    if reason:
        return reason
    assert isinstance(entry, dict)
    declared = [key for key in ("authority", "managed-by") if key in entry]
    if len(declared) != 1:
        return f"{where} carries exactly one of `authority` and `managed-by`"
    return None


def _typed(entries: Mapping[str, object]) -> Mapping[str, Mapping[str, object]]:
    return {path: entry for path, entry in entries.items() if isinstance(entry, dict)}


def _lists(entries: Mapping[str, object]) -> Mapping[str, list[object]]:
    return {path: entry for path, entry in entries.items() if isinstance(entry, list)}
