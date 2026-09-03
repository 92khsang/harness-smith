"""RFC 8785 canonicalisation, checked against the RFC's own worked examples.

Every expected value here is copied from RFC 8785 rather than derived the way the
implementation derives it, so a test can disagree with the code. Inputs are spelled with
explicit code points so that what the RFC escapes is visible rather than transcribed.
"""

from __future__ import annotations

import hashlib
import json
import struct

import pytest

from harness_smith.canonical_json import CanonicalisationError, canonicalise, fingerprint

# RFC 8785, Section 3.2.2, the "string" member. The RFC writes its twelve code points as
# \u20ac$\u000F\u000aA'\u0042\u0022\u005c\\\"\/
RFC_EXAMPLE_STRING = (
    chr(0x20AC)
    + "$"
    + chr(0x0F)
    + chr(0x0A)
    + "A'B"
    + chr(0x22)
    + chr(0x5C)
    + chr(0x5C)
    + chr(0x22)
    + "/"
)

# The rest of that same document, with the numbers exactly as the RFC writes them.
RFC_EXAMPLE_VALUE = {
    "numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 0.000000000000000000000000001],
    "string": RFC_EXAMPLE_STRING,
    "literals": [None, True, False],
}

# RFC 8785, Section 3.2.4: the canonical form of that document, as bytes.
RFC_EXAMPLE_CANONICAL_HEX = (
    "7b 22 6c 69 74 65 72 61 6c 73 22 3a 5b 6e 75 6c 6c 2c 74 72"
    "75 65 2c 66 61 6c 73 65 5d 2c 22 6e 75 6d 62 65 72 73 22 3a"
    "5b 33 33 33 33 33 33 33 33 33 2e 33 33 33 33 33 33 33 2c 31"
    "65 2b 33 30 2c 34 2e 35 2c 30 2e 30 30 32 2c 31 65 2d 32 37"
    "5d 2c 22 73 74 72 69 6e 67 22 3a 22 e2 82 ac 24 5c 75 30 30"
    "30 66 5c 6e 41 27 42 5c 22 5c 5c 5c 5c 5c 22 2f 22 7d"
)

# RFC 8785, Section 3.2.3: the sorting test data, keyed by the code point the RFC escapes.
RFC_SORTING_VALUE = {
    chr(0x20AC): "Euro Sign",
    chr(0x0D): "Carriage Return",
    chr(0xFB33): "Hebrew Letter Dalet With Dagesh",
    "1": "One",
    chr(0x1F600): "Emoji: Grinning Face",
    chr(0x80): "Control",
    chr(0xF6): "Latin Small Letter O With Diaeresis",
}

# ... and the order the RFC says those property names take once sorted.
RFC_SORTED_VALUES = [
    "Carriage Return",
    "One",
    "Control",
    "Latin Small Letter O With Diaeresis",
    "Euro Sign",
    "Emoji: Grinning Face",
    "Hebrew Letter Dalet With Dagesh",
]

# RFC 8785, Appendix B: IEEE 754 bit patterns and the JSON number each one serialises as.
RFC_NUMBER_SAMPLES = [
    ("0000000000000000", "0"),
    ("8000000000000000", "0"),
    ("0000000000000001", "5e-324"),
    ("8000000000000001", "-5e-324"),
    ("7fefffffffffffff", "1.7976931348623157e+308"),
    ("ffefffffffffffff", "-1.7976931348623157e+308"),
    ("4340000000000000", "9007199254740992"),
    ("c340000000000000", "-9007199254740992"),
    ("4430000000000000", "295147905179352830000"),
    ("44b52d02c7e14af5", "9.999999999999997e+22"),
    ("44b52d02c7e14af6", "1e+23"),
    ("44b52d02c7e14af7", "1.0000000000000001e+23"),
    ("444b1ae4d6e2ef4e", "999999999999999700000"),
    ("444b1ae4d6e2ef4f", "999999999999999900000"),
    ("444b1ae4d6e2ef50", "1e+21"),
    ("3eb0c6f7a0b5ed8c", "9.999999999999997e-7"),
    ("3eb0c6f7a0b5ed8d", "0.000001"),
    ("41b3de4355555553", "333333333.3333332"),
    ("41b3de4355555554", "333333333.33333325"),
    ("41b3de4355555555", "333333333.3333333"),
    ("41b3de4355555556", "333333333.3333334"),
    ("41b3de4355555557", "333333333.33333343"),
    ("becbf647612f3696", "-0.0000033333333333333333"),
    ("43143ff3c1cb0959", "1424953923781206.2"),
]


def double(bits: str) -> float:
    unpacked: float = struct.unpack(">d", bytes.fromhex(bits))[0]
    return unpacked


def test_the_rfcs_worked_example_canonicalises_to_the_bytes_the_rfc_documents() -> None:
    assert canonicalise(RFC_EXAMPLE_VALUE) == bytes.fromhex(
        RFC_EXAMPLE_CANONICAL_HEX.replace(" ", "")
    )


def test_property_names_sort_by_utf_16_code_unit_rather_than_code_point() -> None:
    """The RFC's own sorting sample. An emoji is one code point above U+FFFF but two UTF-16
    code units starting at U+D83D, so it sorts before U+FB33 rather than after it."""
    canonical = json.loads(canonicalise(RFC_SORTING_VALUE).decode("utf-8"))

    assert list(canonical.values()) == RFC_SORTED_VALUES


@pytest.mark.parametrize(("bits", "expected"), RFC_NUMBER_SAMPLES)
def test_numbers_serialise_the_way_the_rfcs_sample_table_says(bits: str, expected: str) -> None:
    assert canonicalise(double(bits)) == expected.encode("utf-8")


def test_a_json_integer_is_serialised_as_the_double_it_denotes() -> None:
    """JCS numbers are IEEE 754 doubles, so a parser that hands back an arbitrary-precision
    integer must not be allowed to widen the value space."""
    assert canonicalise(json.loads("295147905179352825856")) == b"295147905179352830000"
    assert canonicalise(json.loads("120")) == b"120"


def test_object_properties_are_sorted_recursively_and_array_order_is_kept() -> None:
    document = {"b": 1, "a": [{"d": 2, "c": 3}, {"f": 4, "e": 5}]}

    assert canonicalise(document) == b'{"a":[{"c":3,"d":2},{"e":5,"f":4}],"b":1}'


def test_a_boolean_is_not_serialised_as_the_integer_python_stores_it_as() -> None:
    assert canonicalise({"async": True, "timeout": 1}) == b'{"async":true,"timeout":1}'


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_a_number_json_cannot_represent_is_refused(literal: str) -> None:
    value = json.loads(literal)

    with pytest.raises(CanonicalisationError):
        canonicalise(value)


def test_an_integer_beyond_the_double_range_is_refused() -> None:
    with pytest.raises(CanonicalisationError):
        canonicalise(json.loads("1" + "0" * 400))


def test_a_lone_surrogate_is_refused() -> None:
    """RFC 8785, Section 3.2.2.2: such data must terminate a compliant implementation."""
    with pytest.raises(CanonicalisationError):
        canonicalise({"command": chr(0xD800)})


def test_a_lone_surrogate_in_a_property_name_is_refused() -> None:
    with pytest.raises(CanonicalisationError):
        canonicalise({chr(0xDEAD): 1})


def test_a_value_json_has_no_representation_for_is_refused() -> None:
    with pytest.raises(CanonicalisationError):
        canonicalise({"command": object()})


def test_the_fingerprint_is_the_sha_256_of_the_canonical_bytes() -> None:
    declaration = {"matcher": "Write", "hooks": [{"type": "command", "command": "fmt.sh"}]}

    expected = hashlib.sha256(canonicalise(declaration)).hexdigest()

    assert fingerprint(declaration) == expected


def test_two_declarations_differing_only_in_key_order_share_a_fingerprint() -> None:
    written_one_way = json.loads('{"matcher":"Write","hooks":[{"type":"command"}]}')
    written_the_other = json.loads('{"hooks":[{"type":"command"}],"matcher":"Write"}')

    assert fingerprint(written_one_way) == fingerprint(written_the_other)


def test_reordering_the_commands_of_a_declaration_changes_its_fingerprint() -> None:
    """Array order is execution order, so a reordered hooks array is a different declaration."""
    first = {"hooks": [{"command": "a.sh"}, {"command": "b.sh"}]}
    second = {"hooks": [{"command": "b.sh"}, {"command": "a.sh"}]}

    assert fingerprint(first) != fingerprint(second)
