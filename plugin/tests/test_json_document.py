"""The JSON container reader at its own contract.

An Artifact Container is read before anything inside it can be addressed, so the cases below
are the three ways that read can fail: bytes that never became text, text that is not JSON,
and JSON that is not an object and therefore holds no members to point at. Each is its own
state, because each answers to its own finding.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_smith.json_document import (
    BYTE_ORDER_MARK,
    JsonDocumentState,
    own_repeated_names,
    parse_json_document,
    read_json_document,
    repeated_names,
)


def test_an_object_is_parsed_into_its_members() -> None:
    document = parse_json_document('{"hooks": {"Stop": []}, "permissions": {"allow": []}}')

    assert document.state is JsonDocumentState.PARSED
    assert document.members == {"hooks": {"Stop": []}, "permissions": {"allow": []}}
    assert document.reason == ""


def test_an_empty_object_is_parsed_rather_than_treated_as_absent() -> None:
    document = parse_json_document("{}")

    assert document.state is JsonDocumentState.PARSED
    assert document.members == {}


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("a truncated object", '{"hooks": {'),
        ("a trailing comma", '{"hooks": {},}'),
        ("a single-quoted name", "{'hooks': {}}"),
        ("an unquoted name", "{hooks: {}}"),
        ("nothing at all", ""),
    ],
)
def test_text_that_is_not_json_is_unparseable_and_says_where(name: str, text: str) -> None:
    document = parse_json_document(text)

    assert document.state is JsonDocumentState.UNPARSEABLE, name
    assert "line" in document.reason


@pytest.mark.parametrize("text", ["NaN", '{"timeout": NaN}', '{"timeout": Infinity}'])
def test_a_number_json_does_not_define_is_unparseable(text: str) -> None:
    """Python's parser accepts these by default; the runtime's does not, so neither does this."""
    document = parse_json_document(text)

    assert document.state is JsonDocumentState.UNPARSEABLE
    assert "NaN" in document.reason or "Infinity" in document.reason


@pytest.mark.parametrize(
    ("shape", "text"), [("array", "[1, 2]"), ("scalar", "42"), ("scalar", "null")]
)
def test_json_that_is_not_an_object_holds_no_members_to_address(shape: str, text: str) -> None:
    document = parse_json_document(text)

    assert document.state is JsonDocumentState.NOT_AN_OBJECT
    assert shape in document.reason


def test_a_leading_byte_order_mark_does_not_make_the_container_unreadable() -> None:
    document = parse_json_document(BYTE_ORDER_MARK + '{"hooks": {}}')

    assert document.state is JsonDocumentState.PARSED
    assert document.members == {"hooks": {}}


def test_a_repeated_member_keeps_its_last_value_and_is_recorded_as_repeated() -> None:
    """What a repeat means is the caller's decision; the parser only records that it happened."""
    document = parse_json_document('{"model": "a", "model": "b"}')

    assert document.members == {"model": "b"}
    assert own_repeated_names(document.members) == ("model",)


def test_a_file_whose_bytes_are_not_text_is_a_file_finding_not_a_json_one(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b'{"model": "\xff\xfe"}')

    document = read_json_document(path)

    assert document.state is JsonDocumentState.FILE_UNREADABLE
    assert "UTF-8" in document.reason


def test_a_file_that_cannot_be_opened_is_a_file_finding(tmp_path: Path) -> None:
    document = read_json_document(tmp_path / "absent.json")

    assert document.state is JsonDocumentState.FILE_UNREADABLE


def test_no_reason_names_the_path_it_came_from(tmp_path: Path) -> None:
    """A diagnostic carries the Locator in its subject, so a message stays free of paths."""
    path = tmp_path / "settings.json"
    path.write_text('{"hooks": {', encoding="utf-8")

    assert str(tmp_path) not in read_json_document(path).reason
    assert "settings.json" not in read_json_document(path).reason


def test_a_file_that_reads_is_parsed(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"hooks": {"Stop": []}}', encoding="utf-8")

    assert read_json_document(path).members == {"hooks": {"Stop": []}}


def test_a_repeated_property_name_is_recorded_even_though_the_last_value_wins() -> None:
    """RFC 8785 Section 3.1 forbids duplicates in canonicalisation input, and the repeat is
    gone once the object is a mapping, so the parser is the only place it can be seen."""
    document = parse_json_document('{"model": "a", "model": "b", "other": 1}')

    assert document.members == {"model": "b", "other": 1}
    assert repeated_names(document.members) == ("model",)


def test_a_repeated_name_is_found_however_deeply_it_is_nested() -> None:
    document = parse_json_document('{"hooks": {"Stop": [{"matcher": "a", "matcher": "b"}]}}')

    assert repeated_names(document.members) == ("matcher",)
    assert repeated_names(document.members["hooks"]) == ("matcher",)


def test_an_object_whose_names_are_unique_repeats_nothing() -> None:
    document = parse_json_document('{"hooks": {"Stop": [{"matcher": "a", "timeout": 1}]}}')

    assert repeated_names(document.members) == ()


def test_a_mapping_this_module_did_not_parse_reports_no_repeats() -> None:
    """It carries no record of its own repeats, and inventing one would be a guess."""
    assert repeated_names({"model": "b"}) == ()


def test_a_nested_repeat_is_not_counted_as_the_outer_objects_own() -> None:
    document = parse_json_document('{"hooks": {"Stop": [{"matcher": "a", "matcher": "b"}]}}')

    assert own_repeated_names(document.members) == ()
    assert repeated_names(document.members) == ("matcher",)
