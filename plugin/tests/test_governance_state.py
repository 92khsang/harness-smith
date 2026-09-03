"""The repository's governance state files, read and validated.

Two files split by who decides the value: the manifest holds what a person declared, the lock
holds what the tool measured. Neither being there is ordinary; one being there and unreadable
is a usage error, because every later answer about authority or provenance would rest on it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from harness_smith.governance import LOCK, MANIFEST, Governance, read_governance
from harness_smith.governance.paths import normalised
from tests.support import write_tree

VALID_MANIFEST = """schemaVersion: 1

authority:
  docs/agents/issue-tracker.md:
    managed-by: { plugin: mattpocock-skills, operation: setup-matt-pocock-skills }
    rationale: "Setup regenerates this file."
  docs/harness/HARNESS_STANDARD.md:
    authority: harness-smith
    updatePolicy: pinned

consumers:
  docs/agents/issue-tracker.md:
    - plugin: mattpocock-skills
      version: "1.2.3"
      consumer: code-review
      binding: literal-path
      evidence:
        path: skills/engineering/code-review/SKILL.md
        locator: { type: contains-literal-path, value: "docs/agents/issue-tracker.md" }

writers:
  docs/agents/issue-tracker.md:
    - plugin: mattpocock-skills
      version: "1.2.3"
      writer: setup-matt-pocock-skills
      mode: regenerate
      confirmed-by: human
      evidence:
        path: skills/engineering/setup-matt-pocock-skills/SKILL.md
        locator: { type: contains-literal-path, value: "docs/agents/issue-tracker.md" }
"""

VALID_LOCK = json.dumps(
    {
        "schemaVersion": 1,
        "standard": {"id": "harness-smith", "version": "1.0.0"},
        "entrypoint": {
            "runtime": "claude-code",
            "path": "CLAUDE.md",
            "template": "claude-root",
            "version": "1.0.0",
        },
        "artifacts": {
            "docs/harness/HARNESS_STANDARD.md": {
                "provenance": "generated",
                "source": "harness-smith:standard/default",
                "sourceVersion": "1.0.0",
                "sha256": "a" * 64,
                "baselineSha256": "b" * 64,
            },
            "docs/agents/domain.md": {
                "provenance": "adopted",
                "baselineSha256": "c" * 64,
                "adoptedFrom": {
                    "source": "mattpocock-skills:setup/domain",
                    "sourceVersion": "1.2.3",
                    "sourceRevision": "0ab1b63",
                    "sha256": "d" * 64,
                },
            },
        },
    },
    indent=2,
)


def read(tmp_path: Path, files: Mapping[str, str]) -> Governance:
    return read_governance(write_tree(tmp_path / "repository", files))


def codes(governance: Governance) -> list[str]:
    return [diagnostic.code for diagnostic in governance.diagnostics]


def test_a_repository_with_neither_file_is_an_ordinary_repository(tmp_path: Path) -> None:
    """Declaring nothing is a state, not a failure."""
    governance = read(tmp_path, {"README.md": "# readme\n"})

    assert governance.manifest.present is False
    assert governance.lock.present is False
    assert governance.diagnostics == ()


def test_a_valid_pair_reads(tmp_path: Path) -> None:
    governance = read(tmp_path, {MANIFEST: VALID_MANIFEST, LOCK: VALID_LOCK})

    assert governance.manifest.valid
    assert governance.lock.valid
    assert governance.diagnostics == ()
    assert sorted(governance.manifest.authority) == [
        "docs/agents/issue-tracker.md",
        "docs/harness/HARNESS_STANDARD.md",
    ]
    assert sorted(governance.lock.artifacts) == [
        "docs/agents/domain.md",
        "docs/harness/HARNESS_STANDARD.md",
    ]


def test_one_file_alone_is_read_on_its_own(tmp_path: Path) -> None:
    governance = read(tmp_path, {MANIFEST: VALID_MANIFEST})

    assert governance.manifest.valid
    assert governance.lock.present is False
    assert governance.diagnostics == ()


BROKEN_MANIFESTS = [
    ("no schema version", "authority: {}\n"),
    ("a schema version that is not an integer", 'schemaVersion: "1"\n'),
    ("an unknown top-level key", "schemaVersion: 1\nrelations: {}\n"),
    ("a section that is not a mapping", "schemaVersion: 1\nauthority: []\n"),
    (
        "an unknown key inside an entry",
        "schemaVersion: 1\nauthority:\n  a.md: { authority: local, owner: me }\n",
    ),
    (
        "an entry claiming both owners",
        "schemaVersion: 1\nauthority:\n  a.md: { authority: local, managed-by: { plugin: p } }\n",
    ),
    ("an entry claiming neither", "schemaVersion: 1\nauthority:\n  a.md: { rationale: why }\n"),
    (
        "an authority outside the enum",
        "schemaVersion: 1\nauthority:\n  a.md: { authority: mine }\n",
    ),
    (
        "an update policy outside the enum",
        "schemaVersion: 1\nauthority:\n  a.md: { authority: local, updatePolicy: forever }\n",
    ),
    ("a duplicate key", "schemaVersion: 1\nauthority: {}\nauthority: {}\n"),
    (
        "one path written two ways",
        "schemaVersion: 1\nauthority:\n"
        "  a.md: { authority: local }\n  ./a.md: { authority: local }\n",
    ),
    ("a consumers entry that is not a list", "schemaVersion: 1\nconsumers:\n  a.md: {}\n"),
    (
        "a consumer missing evidence",
        "schemaVersion: 1\nconsumers:\n  a.md:\n"
        "    - { plugin: p, version: v, consumer: c, binding: literal-path }\n",
    ),
    (
        "a binding outside the enum",
        "schemaVersion: 1\nconsumers:\n  a.md:\n    - plugin: p\n      version: v\n"
        "      consumer: c\n      binding: guessing\n"
        "      evidence: { path: p.md, locator: { type: contains-text, value: x } }\n",
    ),
    (
        "a locator type outside the enum",
        "schemaVersion: 1\nconsumers:\n  a.md:\n    - plugin: p\n      version: v\n"
        "      consumer: c\n      binding: non-literal\n"
        "      evidence: { path: p.md, locator: { type: vibes, value: x } }\n",
    ),
    (
        "a writer mode outside the enum",
        "schemaVersion: 1\nwriters:\n  a.md:\n    - plugin: p\n      version: v\n"
        "      writer: w\n      mode: whenever\n      confirmed-by: human\n"
        "      evidence: { path: p.md, locator: { type: contains-text, value: x } }\n",
    ),
    ("a file that is not a mapping", "- one\n- two\n"),
    ("text that is not YAML", "schemaVersion: [1\n"),
]


@pytest.mark.parametrize(
    ("what", "content"), BROKEN_MANIFESTS, ids=[case[0] for case in BROKEN_MANIFESTS]
)
def test_a_manifest_that_does_not_read_is_a_usage_error(
    tmp_path: Path, what: str, content: str
) -> None:
    governance = read(tmp_path, {MANIFEST: content})

    assert codes(governance) == ["HS-MANIFEST-INVALID"], what
    assert governance.manifest.present is True
    assert governance.manifest.valid is False
    assert governance.diagnostics[0].exit_effect == 2
    assert governance.diagnostics[0].message


GENERATED: dict[str, object] = {
    "provenance": "generated",
    "baselineSha256": "x",
    "source": "s",
    "sourceVersion": "1",
    "sha256": "y",
}


def _without(entry: Mapping[str, object], key: str) -> dict[str, object]:
    return {name: value for name, value in entry.items() if name != key}


BROKEN_LOCKS = [
    ("an unknown top-level key", {"extra": 1}),
    ("a missing section", {"standard": None}),
    (
        "an unknown key inside an entry",
        {
            "artifacts": {
                "a.md": {
                    "provenance": "generated",
                    "baselineSha256": "x",
                    "source": "s",
                    "sourceVersion": "1",
                    "sha256": "y",
                    "extra": 1,
                }
            }
        },
    ),
    (
        "a provenance outside the enum",
        {"artifacts": {"a.md": {"provenance": "invented", "baselineSha256": "x"}}},
    ),
    (
        "an entry with no baseline",
        {
            "artifacts": {
                "a.md": {
                    "provenance": "generated",
                    "source": "s",
                    "sourceVersion": "1",
                    "sha256": "y",
                }
            }
        },
    ),
    (
        "a generated entry with no descriptor",
        {"artifacts": {"a.md": {"provenance": "generated", "baselineSha256": "x"}}},
    ),
    (
        "an adopted entry with no seed",
        {"artifacts": {"a.md": {"provenance": "adopted", "baselineSha256": "x"}}},
    ),
    (
        "a generated entry carrying a seed",
        {
            "artifacts": {
                "a.md": {
                    "provenance": "generated",
                    "baselineSha256": "x",
                    "source": "s",
                    "sourceVersion": "1",
                    "sha256": "y",
                    "adoptedFrom": {},
                }
            }
        },
    ),
    (
        "a baseline that is not text",
        {
            "artifacts": {
                "a.md": {
                    "provenance": "generated",
                    "baselineSha256": 1,
                    "source": "s",
                    "sourceVersion": "1",
                    "sha256": "y",
                }
            }
        },
    ),
]


def lock_with(changes: Mapping[str, object]) -> str:
    document = json.loads(VALID_LOCK)
    for key, value in changes.items():
        if value is None:
            document.pop(key)
        else:
            document[key] = value
    return json.dumps(document, indent=2)


@pytest.mark.parametrize(("what", "changes"), BROKEN_LOCKS, ids=[case[0] for case in BROKEN_LOCKS])
def test_a_lock_that_does_not_read_is_a_usage_error(
    tmp_path: Path, what: str, changes: Mapping[str, object]
) -> None:
    governance = read(tmp_path, {LOCK: lock_with(changes)})

    assert codes(governance) == ["HS-LOCK-INVALID"], what
    assert governance.lock.present is True
    assert governance.lock.valid is False
    assert governance.diagnostics[0].exit_effect == 2


def test_a_lock_naming_one_path_twice_is_refused(tmp_path: Path) -> None:
    """A repeated JSON property is refused rather than resolved by keeping one."""
    entry = json.dumps(GENERATED)
    content = (
        '{"schemaVersion": 1, "standard": {"id": "s", "version": "1"},'
        ' "entrypoint": {"runtime": "r", "path": "p", "template": "t", "version": "1"},'
        f' "artifacts": {{"a.md": {entry}, "./a.md": {entry}}}}}'
    )

    governance = read(tmp_path, {LOCK: content})

    assert codes(governance) == ["HS-LOCK-INVALID"]
    assert "twice" in governance.diagnostics[0].message


def test_a_lock_that_is_not_json_is_a_usage_error(tmp_path: Path) -> None:
    governance = read(tmp_path, {LOCK: "{not json\n"})

    assert codes(governance) == ["HS-LOCK-INVALID"]


def test_both_files_broken_are_reported_separately(tmp_path: Path) -> None:
    governance = read(tmp_path, {MANIFEST: "- one\n", LOCK: "[]\n"})

    assert codes(governance) == ["HS-MANIFEST-INVALID", "HS-LOCK-INVALID"]


@pytest.mark.parametrize(
    ("written", "compared"),
    [
        ("./docs/x.md", "docs/x.md"),
        ("docs//x.md", "docs/x.md"),
        ("docs\\\\x.md", "docs/x.md"),
        ("././docs/x.md", "docs/x.md"),
        ("docs/x.md", "docs/x.md"),
    ],
)
def test_a_path_is_compared_by_one_spelling(written: str, compared: str) -> None:
    assert normalised(written) == compared


def test_normalisation_keeps_a_parent_step() -> None:
    """Removing a `..` lexically names a different file whenever a symlink is in the way, and
    resolving it against this machine's filesystem would answer differently elsewhere."""
    assert normalised("./docs/../x.md") == "docs/../x.md"


def test_the_lock_records_an_approved_baseline_and_no_current_digest(tmp_path: Path) -> None:
    """`baselineSha256` is the digest approved when the content was last generated, imported or
    adopted. What is on disk now is measured at scan time and never written here."""
    governance = read(tmp_path, {LOCK: VALID_LOCK})

    entry = governance.lock.artifacts["docs/harness/HARNESS_STANDARD.md"]

    assert entry["baselineSha256"] == "b" * 64
    assert "currentSha256" not in entry
    assert entry["sha256"] == "a" * 64


def test_a_path_that_is_not_a_readable_file_is_not_a_repository_that_declared_nothing(
    tmp_path: Path,
) -> None:
    """Whether a governance file is there and what it says are one read. A directory at the
    manifest's path answers "no file" to a separate existence check, while holding something
    somebody meant as policy."""
    root = write_tree(tmp_path / "repository", {"README.md": "# readme\n"})
    (root / MANIFEST).mkdir()

    governance = read_governance(root)

    assert codes(governance) == ["HS-MANIFEST-INVALID"]
    assert governance.manifest.present is True
    assert governance.manifest.valid is False
