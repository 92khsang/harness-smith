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
from harness_smith.governance.paths import normalised, refused
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
    ("a schema version this tool does not read", "schemaVersion: 999\nauthority: {}\n"),
    ("a path key that is not text", "schemaVersion: 1\nauthority:\n  123: { authority: local }\n"),
    (
        "a path stepping outside the repository",
        "schemaVersion: 1\nauthority:\n  ../outside.md: { authority: local }\n",
    ),
    ("an absolute path", "schemaVersion: 1\nauthority:\n  /etc/passwd: { authority: local }\n"),
    (
        "a drive-qualified path",
        'schemaVersion: 1\nauthority:\n  "C:/x.md": { authority: local }\n',
    ),
    (
        "a network share path",
        'schemaVersion: 1\nauthority:\n  "//server/share/x.md": { authority: local }\n',
    ),
    ("a path naming nothing", 'schemaVersion: 1\nauthority:\n  "": { authority: local }\n'),
    (
        "a path holding a NUL",
        'schemaVersion: 1\nauthority:\n  "a\\0b.md": { authority: local }\n',
    ),
    (
        "a rationale that is not text",
        "schemaVersion: 1\nauthority:\n  a.md: { authority: local, rationale: 3 }\n",
    ),
    (
        "an owner naming a plugin that is not text",
        "schemaVersion: 1\nauthority:\n  a.md: { managed-by: { plugin: 3 } }\n",
    ),
    (
        "an owner with an operation that is not text",
        "schemaVersion: 1\nauthority:\n  a.md: { managed-by: { plugin: p, operation: 7 } }\n",
    ),
    (
        "a seed field that is not text",
        "schemaVersion: 1\nauthority:\n  a.md:\n    authority: local\n"
        "    adopted-from: { plugin: p, version: 1, source-revision: r, seed: s }\n",
    ),
    (
        "a consumer plugin that is not text",
        "schemaVersion: 1\nconsumers:\n  a.md:\n    - plugin: 3\n      version: v\n"
        "      consumer: c\n      binding: literal-path\n"
        "      evidence: { path: p.md, locator: { type: contains-text, value: x } }\n",
    ),
    (
        "a consumer version that is not text",
        "schemaVersion: 1\nconsumers:\n  a.md:\n    - plugin: p\n      version: 1\n"
        "      consumer: c\n      binding: literal-path\n"
        "      evidence: { path: p.md, locator: { type: contains-text, value: x } }\n",
    ),
    (
        "a consumer name that is not text",
        "schemaVersion: 1\nconsumers:\n  a.md:\n    - plugin: p\n      version: v\n"
        "      consumer: 9\n      binding: literal-path\n"
        "      evidence: { path: p.md, locator: { type: contains-text, value: x } }\n",
    ),
    (
        "an evidence path that is not text",
        "schemaVersion: 1\nconsumers:\n  a.md:\n    - plugin: p\n      version: v\n"
        "      consumer: c\n      binding: literal-path\n"
        "      evidence: { path: 4, locator: { type: contains-text, value: x } }\n",
    ),
    (
        "a locator value that is not text",
        "schemaVersion: 1\nconsumers:\n  a.md:\n    - plugin: p\n      version: v\n"
        "      consumer: c\n      binding: literal-path\n"
        "      evidence: { path: p.md, locator: { type: contains-text, value: 5 } }\n",
    ),
    (
        "a resolution field that is not text",
        "schemaVersion: 1\nconsumers:\n  a.md:\n    - plugin: p\n      version: v\n"
        "      consumer: c\n      binding: non-literal\n"
        "      resolution: { kind: k, confirmed-by: 2 }\n"
        "      evidence: { path: p.md, locator: { type: contains-text, value: x } }\n",
    ),
    (
        "a resolution with an unknown key",
        "schemaVersion: 1\nconsumers:\n  a.md:\n    - plugin: p\n      version: v\n"
        "      consumer: c\n      binding: non-literal\n"
        "      resolution: { kind: k, confirmed-by: human, guess: yes }\n"
        "      evidence: { path: p.md, locator: { type: contains-text, value: x } }\n",
    ),
    (
        "a writer confirmed-by that is not text",
        "schemaVersion: 1\nwriters:\n  a.md:\n    - plugin: p\n      version: v\n"
        "      writer: w\n      mode: regenerate\n      confirmed-by: 1\n"
        "      evidence: { path: p.md, locator: { type: contains-text, value: x } }\n",
    ),
    (
        "a writer source-revision that is not text",
        "schemaVersion: 1\nwriters:\n  a.md:\n    - plugin: p\n      version: v\n"
        "      writer: w\n      mode: regenerate\n      confirmed-by: human\n"
        "      source-revision: 6\n"
        "      evidence: { path: p.md, locator: { type: contains-text, value: x } }\n",
    ),
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

IMPORT_URL: dict[str, object] = {**GENERATED, "sourceUrl": "https://example.test/x.md"}

SEED: dict[str, object] = {"source": "s", "sourceVersion": "1", "sha256": "y"}

ADOPTED: dict[str, object] = {
    "provenance": "adopted",
    "baselineSha256": "x",
    "adoptedFrom": SEED,
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
    ("a schema version this tool does not read", {"schemaVersion": 999}),
    ("a standard id that is not text", {"standard": {"id": 1, "version": "1"}}),
    (
        "an entrypoint path that is not text",
        {"entrypoint": {"runtime": "r", "path": 1, "template": "t", "version": "1"}},
    ),
    ("a generated entry carrying an import URL", {"artifacts": {"a.md": IMPORT_URL}}),
    (
        "a generated entry carrying a licence",
        {"artifacts": {"a.md": {**GENERATED, "license": "MIT"}}},
    ),
    (
        "an imported entry whose URL is not text",
        {"artifacts": {"a.md": {**GENERATED, "provenance": "imported", "sourceUrl": 1}}},
    ),
    (
        "a source revision that is not text",
        {"artifacts": {"a.md": {**GENERATED, "sourceRevision": 1}}},
    ),
    (
        "a declaration digest that is not text",
        {"artifacts": {"a.md": {**GENERATED, "declarationDigest": 1}}},
    ),
    (
        "an adopted entry carrying its descriptor at the top",
        {"artifacts": {"a.md": {**ADOPTED, "source": "s"}}},
    ),
    (
        "an adopted seed carrying an import URL",
        {
            "artifacts": {
                "a.md": {**ADOPTED, "adoptedFrom": {**SEED, "sourceUrl": "https://example.test"}}
            }
        },
    ),
    (
        "an adopted seed missing its digest",
        {"artifacts": {"a.md": {**ADOPTED, "adoptedFrom": {"source": "s", "sourceVersion": "1"}}}},
    ),
    ("an artifact keyed by an absolute path", {"artifacts": {"/etc/passwd": GENERATED}}),
    ("an artifact keyed outside the repository", {"artifacts": {"../x.md": GENERATED}}),
    ("an artifact keyed by a drive", {"artifacts": {"C:/x.md": GENERATED}}),
    (
        "an artifact whose `#` is not followed by a pointer",
        {"artifacts": {"a.json#hooks": GENERATED}},
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


@pytest.mark.parametrize(
    "key",
    ["../x.md", "docs/../x.md", "/etc/passwd", "//server/share/x.md", "C:/x.md", "", "a\x00b.md"],
)
def test_a_key_that_is_not_a_repository_relative_path_is_refused(key: str) -> None:
    """Collapsing a `..` lexically names a different file whenever a symlink is in the way, and
    resolving it against this machine's filesystem would answer differently elsewhere. Neither
    answer is one to key a policy by, so the key is refused rather than repaired."""
    assert refused(key, "the `authority` section") is not None


def test_a_locator_keys_a_declaration_held_inside_a_container() -> None:
    """A hook is addressed by a pointer into the file that holds it, and the lock keys its
    entry the same way."""
    locator = ".claude/settings.json#/hooks/PostToolUse/0"

    assert refused(locator, "the lock", locator=True) is None
    assert normalised("./.claude//settings.json#/hooks/PostToolUse/0") == locator


def test_a_pointer_is_not_a_path_the_manifest_may_key_by() -> None:
    assert refused(".claude/settings.json#/hooks", "the `authority` section") is not None


def test_a_lock_records_a_hook_fragment_at_its_locator(tmp_path: Path) -> None:
    entry = {
        "provenance": "generated",
        "baselineSha256": "b" * 64,
        "declarationDigest": "d" * 64,
        "source": "harness-smith:standard/default",
        "sourceVersion": "1.0.0",
        "sha256": "a" * 64,
    }
    locator = ".claude/settings.json#/hooks/PostToolUse/0"

    governance = read(tmp_path, {LOCK: lock_with({"artifacts": {locator: entry}})})

    assert governance.lock.valid
    assert governance.diagnostics == ()
    assert governance.lock.artifacts[locator]["declarationDigest"] == "d" * 64


def test_an_imported_artifact_keeps_the_url_and_licence_it_was_taken_under(
    tmp_path: Path,
) -> None:
    """`sourceUrl` and `license` describe an import, and are refused under any other
    provenance."""
    entry = {
        "provenance": "imported",
        "baselineSha256": "b" * 64,
        "source": "example:doc",
        "sourceVersion": "2.0.0",
        "sha256": "a" * 64,
        "sourceUrl": "https://example.test/doc.md",
        "license": "CC-BY-4.0",
    }

    governance = read(tmp_path, {LOCK: lock_with({"artifacts": {"docs/x.md": entry}})})

    assert governance.lock.valid
    assert governance.lock.artifacts["docs/x.md"]["sourceUrl"] == "https://example.test/doc.md"


def test_a_governance_path_that_resolves_nowhere_is_not_a_repository_that_declared_nothing(
    tmp_path: Path,
) -> None:
    """A symbolic link with nothing at the other end is a file somebody meant to be there."""
    root = write_tree(tmp_path / "repository", {"README.md": "# readme\n"})
    (root / MANIFEST).symlink_to(root / "elsewhere.yaml")

    governance = read_governance(root)

    assert codes(governance) == ["HS-MANIFEST-INVALID"]
    assert governance.manifest.present is True


def test_a_governance_file_reached_through_a_link_is_read(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "repository", {"elsewhere.yaml": VALID_MANIFEST})
    (root / MANIFEST).symlink_to(root / "elsewhere.yaml")

    governance = read_governance(root)

    assert governance.manifest.valid
    assert governance.diagnostics == ()


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
