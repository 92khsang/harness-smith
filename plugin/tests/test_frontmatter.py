"""The frontmatter reader at its own contract.

A rule's frontmatter is parsed, not scanned, so the cases below are the ones a line or regex
scanner gets wrong: a block scalar whose content looks like more fields, a quoted scalar
carrying a colon or a hash, flow and block sequences, nested mappings, and the boolean set.
Each case is the fixture that says the reader is a real YAML parser.

The schema is YAML 1.2 core, which is this project's decision rather than the runtime's:
harness-smith reads the keys from disk with its own parser (ADR-0006). Under 1.2 only `true`
and `false` and their capitalisations are booleans, and `yes`, `no`, `on` and `off` are text.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_smith.frontmatter import (
    Frontmatter,
    FrontmatterState,
    read_frontmatter,
    read_frontmatter_file,
)


def document(body: str) -> str:
    """A markdown file whose frontmatter block is ``body``."""
    return f"---\n{body}---\n\n# Heading\n\nProse.\n"


PARSED: list[tuple[str, str, dict[str, object]]] = [
    ("an empty block", "", {}),
    ("a comment only", "# nothing but a comment\n", {}),
    (
        "a literal scalar whose content looks like more fields",
        "summary: |\n  paths: not-a-field\n  ---\n  still one scalar\n",
        {"summary": "paths: not-a-field\n---\nstill one scalar\n"},
    ),
    (
        "a folded scalar",
        "description: >\n  one two\n  three\n",
        {"description": "one two three\n"},
    ),
    (
        "a double-quoted scalar carrying a colon and a hash",
        'description: "a rule: it is not a # comment"\n',
        {"description": "a rule: it is not a # comment"},
    ),
    (
        "a single-quoted scalar carrying a doubled quote",
        "note: 'it''s quoted'\n",
        {"note": "it's quoted"},
    ),
    (
        "a block sequence",
        "paths:\n  - \"src/api/**/*.ts\"\n  - 'docs/**'\n",
        {"paths": ["src/api/**/*.ts", "docs/**"]},
    ),
    ("a flow sequence", "tools: [Read, Grep]\n", {"tools": ["Read", "Grep"]}),
    (
        "a nested mapping",
        "x-harness-smith:\n  id: rule-one\n  enforced-by: tests/test_one.py\n",
        {"x-harness-smith": {"id": "rule-one", "enforced-by": "tests/test_one.py"}},
    ),
    (
        "the booleans YAML 1.2 recognises",
        "lower: true\nupper: TRUE\ntitle: False\n",
        {"lower": True, "upper": True, "title": False},
    ),
    (
        "the words YAML 1.2 leaves as text",
        "y: yes\nn: no\nup: on\ndown: off\n",
        {"y": "yes", "n": "no", "up": "on", "down": "off"},
    ),
    ("carriage returns", "name: windows\r\n", {"name": "windows"}),
]


@pytest.mark.parametrize(
    ("body", "expected"),
    [pytest.param(body, expected, id=name) for name, body, expected in PARSED],
)
def test_a_readable_block_yields_its_fields(body: str, expected: dict[str, object]) -> None:
    frontmatter = read_frontmatter(document(body))

    assert frontmatter.state is FrontmatterState.PARSED
    assert frontmatter.fields == expected


INVALID: list[tuple[str, str]] = [
    ("an unclosed block", "---\nname: never-closed\n\n# Heading\n"),
    ("invalid YAML", document("paths: [1, 2\n")),
    ("a duplicate field", document("name: one\nname: two\n")),
    ("a tab where YAML forbids one", document("outer:\n\tinner: 1\n")),
    ("a sequence instead of a mapping", document("- one\n- two\n")),
    ("a scalar instead of a mapping", document("just prose\n")),
    ("a field name that is not text", document("1: numbered\n")),
    ("a tag the safe loader will not construct", document("value: !!python/name:os.system\n")),
]


@pytest.mark.parametrize("text", [pytest.param(text, id=name) for name, text in INVALID])
def test_an_invalid_block_says_why(text: str) -> None:
    frontmatter = read_frontmatter(text)

    assert frontmatter.state is FrontmatterState.INVALID
    assert frontmatter.reason
    assert frontmatter.fields == {}


ABSENT: list[tuple[str, str]] = [
    ("no delimiter at all", "# Heading\n\nProse.\n"),
    ("a longer rule of dashes", "----\nname: not-frontmatter\n----\n"),
    ("a blank line before the delimiter", "\n---\nname: too-late\n---\n"),
    ("prose before the delimiter", "Prose.\n\n---\nname: too-late\n---\n"),
    ("an empty file", ""),
]


@pytest.mark.parametrize("text", [pytest.param(text, id=name) for name, text in ABSENT])
def test_a_file_without_a_block_is_not_an_error(text: str) -> None:
    """A rule with no frontmatter is a prose-only rule, not a broken one."""
    frontmatter = read_frontmatter(text)

    assert frontmatter.state is FrontmatterState.ABSENT
    assert frontmatter.fields == {}


def test_a_utf_8_byte_order_mark_does_not_hide_the_block() -> None:
    frontmatter = read_frontmatter("\ufeff" + document("name: with-a-bom\n"))

    assert frontmatter.state is FrontmatterState.PARSED
    assert frontmatter.fields == {"name": "with-a-bom"}


def test_the_delimiter_may_carry_trailing_whitespace() -> None:
    frontmatter = read_frontmatter("---  \nname: padded\n---\t\n\nProse.\n")

    assert frontmatter.state is FrontmatterState.PARSED
    assert frontmatter.fields == {"name": "padded"}


def test_a_reason_locates_the_problem_by_its_line_in_the_file() -> None:
    """The block starts on the file's second line, so the reported line is the file's."""
    frontmatter = read_frontmatter(document("name: one\nname: two\n"))

    assert frontmatter.state is FrontmatterState.INVALID
    assert "line 3" in frontmatter.reason


def test_reading_a_file_strips_a_byte_order_mark_the_encoding_left_behind(
    tmp_path: Path,
) -> None:
    path = tmp_path / "rule.md"
    path.write_bytes(b"\xef\xbb\xbf" + document("name: with-a-bom\n").encode("utf-8"))

    assert read_frontmatter_file(path).fields == {"name": "with-a-bom"}


def test_a_file_that_is_not_utf_8_never_became_text_to_parse(tmp_path: Path) -> None:
    """A file-level failure is a different finding from invalid YAML, so it is a different
    state: nothing here says anything about the YAML the bytes might have spelled out."""
    path = tmp_path / "rule.md"
    path.write_bytes(b"---\nname: \xff\xfe not utf-8\n---\n")

    frontmatter = read_frontmatter_file(path)

    assert frontmatter.state is FrontmatterState.FILE_UNREADABLE
    assert str(path) not in frontmatter.reason


def test_a_missing_file_is_a_file_level_failure_without_naming_its_path(tmp_path: Path) -> None:
    path = tmp_path / "absent.md"

    frontmatter = read_frontmatter_file(path)

    assert frontmatter.state is FrontmatterState.FILE_UNREADABLE
    assert str(path) not in frontmatter.reason


def test_reading_a_file_still_reports_invalid_yaml_as_invalid(tmp_path: Path) -> None:
    path = tmp_path / "rule.md"
    path.write_text(document("paths: [1, 2\n"), encoding="utf-8")

    assert read_frontmatter_file(path).state is FrontmatterState.INVALID


def test_a_parsed_block_reports_no_reason() -> None:
    assert Frontmatter.parsed({"name": "x"}).reason == ""
