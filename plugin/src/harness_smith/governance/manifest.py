"""The governance manifest: the policy statements a person wrote down.

`harness.manifest.yaml` carries Management Authority, update policy, and the Consumer and
Writer relations somebody declared. Everything in it is a human choice, which is why it is
YAML, hand-editable and comment-bearing, and why the tool never writes it as a side effect.

What the tool computes about the same artifacts — provenance, where content came from, and the
approved drift baseline — lives in the lock instead. Splitting them by who decides the value is
what keeps a regenerated lock from overwriting a decision, and a hand edit from claiming a
measurement.

The key sets are closed at every level. An unknown key is a mistake somebody made rather than
an extension point, and reading past one would ignore a policy that was written down.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from harness_smith.governance.paths import normalised
from harness_smith.governance.shape import closed, listed, mapping, one_of, required, text
from harness_smith.text_file import TextFile, TextFileState
from harness_smith.yaml_document import YamlDocumentState, parse_yaml_document

__all__ = ["MANIFEST", "Manifest", "read_manifest"]

MANIFEST = "harness.manifest.yaml"

SCHEMA_VERSION = "schemaVersion"
SECTIONS = ("authority", "consumers", "writers")
TOP_LEVEL = (SCHEMA_VERSION, *SECTIONS)

AUTHORITY_KEYS = ("authority", "managed-by", "updatePolicy", "adopted-from", "rationale")
AUTHORITY_VALUES = ("local", "harness-smith")
UPDATE_POLICIES = ("pinned", "local")
MANAGED_BY_KEYS = ("plugin", "operation")
ADOPTED_FROM_KEYS = ("plugin", "version", "source-revision", "seed")

CONSUMER_REQUIRED = ("plugin", "version", "consumer", "binding", "evidence")
CONSUMER_KEYS = (*CONSUMER_REQUIRED, "source-revision", "resolution", "rationale")
BINDINGS = ("literal-path", "non-literal")
RESOLUTION_KEYS = ("kind", "confirmed-by", "rationale")

WRITER_REQUIRED = ("plugin", "version", "writer", "mode", "evidence", "confirmed-by")
WRITER_KEYS = (*WRITER_REQUIRED, "source-revision", "rationale")
MODES = ("regenerate", "append", "in-place-update")

EVIDENCE_KEYS = ("path", "locator")
LOCATOR_KEYS = ("type", "value")
LOCATOR_TYPES = ("contains-literal-path", "absent-literal-path", "contains-text")


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
    reason = closed(members, TOP_LEVEL, "the manifest") or _version(members)
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


def _version(members: Mapping[str, object]) -> str | None:
    if SCHEMA_VERSION not in members:
        return f"the manifest is missing `{SCHEMA_VERSION}`"
    version = members[SCHEMA_VERSION]
    if not isinstance(version, int) or isinstance(version, bool):
        return f"the manifest has a `{SCHEMA_VERSION}` that is not an integer"
    return None


def _section(members: Mapping[str, object], name: str) -> dict[str, object] | str:
    """One section's entries, keyed by the one spelling paths are compared by."""
    value = members.get(name)
    if value is None:
        return {}
    reason = mapping(value, f"the `{name}` section")
    if reason:
        return reason
    assert isinstance(value, dict)
    entries: dict[str, object] = {}
    for path, entry in value.items():
        key = normalised(str(path))
        if key in entries:
            return f"the `{name}` section names `{key}` twice"
        entries[key] = entry
    return entries


def _entries(sections: Mapping[str, dict[str, object]]) -> str | None:
    for path, entry in sections["authority"].items():
        reason = _authority(path, entry)
        if reason:
            return reason
    for name, check in (("consumers", _consumer), ("writers", _writer)):
        for path, entry in sections[name].items():
            where = f"the `{name}` entry for `{path}`"
            reason = listed(entry, where)
            if reason:
                return reason
            assert isinstance(entry, list)
            for item in entry:
                reason = check(where, item)
                if reason:
                    return reason
    return None


def _authority(path: str, entry: object) -> str | None:
    """Exactly one of `authority` and `managed-by`: an entry that says both, or neither, has
    not said who may write the file."""
    where = f"the `authority` entry for `{path}`"
    reason = mapping(entry, where) or None
    if reason:
        return reason
    assert isinstance(entry, dict)
    reason = closed(entry, AUTHORITY_KEYS, where) or text(entry, ("rationale",), where)
    if reason:
        return reason
    declared = [key for key in ("authority", "managed-by") if key in entry]
    if len(declared) != 1:
        return f"{where} carries exactly one of `authority` and `managed-by`"
    if "authority" in entry:
        reason = one_of(entry["authority"], AUTHORITY_VALUES, f"{where}'s `authority`")
    else:
        reason = _object(entry["managed-by"], MANAGED_BY_KEYS, ("plugin",), f"{where}'s owner")
    if reason:
        return reason
    if "updatePolicy" in entry:
        reason = one_of(entry["updatePolicy"], UPDATE_POLICIES, f"{where}'s `updatePolicy`")
        if reason:
            return reason
    if "adopted-from" in entry:
        return _object(
            entry["adopted-from"], ADOPTED_FROM_KEYS, ADOPTED_FROM_KEYS, f"{where}'s seed"
        )
    return None


def _consumer(where: str, item: object) -> str | None:
    reason = _relation(where, item, CONSUMER_KEYS, CONSUMER_REQUIRED)
    if reason:
        return reason
    assert isinstance(item, dict)
    reason = one_of(item["binding"], BINDINGS, f"{where}'s `binding`")
    if reason or "resolution" not in item:
        return reason
    return _object(
        item["resolution"], RESOLUTION_KEYS, ("kind", "confirmed-by"), f"{where}'s resolution"
    )


def _writer(where: str, item: object) -> str | None:
    reason = _relation(where, item, WRITER_KEYS, WRITER_REQUIRED)
    if reason:
        return reason
    assert isinstance(item, dict)
    return one_of(item["mode"], MODES, f"{where}'s `mode`")


def _relation(
    where: str, item: object, allowed: tuple[str, ...], needed: tuple[str, ...]
) -> str | None:
    reason = (
        mapping(item, where)
        or closed(item, allowed, where)  # type: ignore[arg-type]
        or required(item, needed, where)  # type: ignore[arg-type]
    )
    if reason:
        return reason
    assert isinstance(item, dict)
    return _evidence(item["evidence"], f"{where}'s evidence")


def _evidence(value: object, where: str) -> str | None:
    reason = _object(value, EVIDENCE_KEYS, EVIDENCE_KEYS, where)
    if reason:
        return reason
    assert isinstance(value, dict)
    reason = _object(value["locator"], LOCATOR_KEYS, LOCATOR_KEYS, f"{where}'s locator")
    if reason:
        return reason
    assert isinstance(value["locator"], dict)
    return one_of(value["locator"]["type"], LOCATOR_TYPES, f"{where}'s locator type")


def _object(
    value: object, allowed: tuple[str, ...], needed: tuple[str, ...], where: str
) -> str | None:
    return (
        mapping(value, where)
        or closed(value, allowed, where)  # type: ignore[arg-type]
        or required(value, needed, where)  # type: ignore[arg-type]
    )


def _typed(entries: Mapping[str, object]) -> Mapping[str, Mapping[str, object]]:
    return {path: entry for path, entry in entries.items() if isinstance(entry, dict)}


def _lists(entries: Mapping[str, object]) -> Mapping[str, list[object]]:
    return {path: entry for path, entry in entries.items() if isinstance(entry, list)}
