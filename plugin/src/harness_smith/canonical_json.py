"""Canonical JSON and the Declaration Digest taken over it, per RFC 8785 (JCS).

A hook declaration has no stable identity, only a Locator: a containing file and a JSON
Pointer. Recognising the same declaration after it moves therefore needs a value the
declaration carries with it, and that value has to be independent of how the containing file
happens to be written -- key order, whitespace and number spelling are all free to change
without the declaration changing.

RFC 8785 is that independence, written down: object properties sorted by UTF-16 code unit,
array order preserved, no whitespace, ECMAScript number and string serialisation, UTF-8 out.
The digest is taken over one declaration's canonical bytes. A digest of the file holding it is
a different measurement answering a different question -- whether the file moved under a
pending write (ADR-0008) -- and neither one stands in for the other.

Two properties of the RFC are the reason this is not ``json.dumps(sort_keys=True)``:

- sorting is by UTF-16 code unit, not code point, so a non-BMP property name sorts by its
  leading surrogate and lands before U+E000..U+FFFF rather than after them;
- numbers take ECMAScript's ``Number::toString`` form, which switches to exponential notation
  at different magnitudes than Python's ``repr`` and writes no leading zero in the exponent.

Data the RFC refuses is refused here rather than silently coerced: NaN, an infinity, a number
outside the IEEE 754 double range, and a lone surrogate all raise.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping

__all__ = ["CanonicalisationError", "canonicalise", "declaration_digest"]

# ECMAScript switches to exponential notation outside this range of decimal point positions.
MAX_PLAIN_EXPONENT = 21
MIN_PLAIN_EXPONENT = -6

# RFC 8785 3.2.2.2: the control characters JSON spells with a short escape.
SHORT_ESCAPES = {0x08: "b", 0x09: "t", 0x0A: "n", 0x0C: "f", 0x0D: "r"}
ASCII_CONTROL_CEILING = 0x20


class CanonicalisationError(ValueError):
    """A value RFC 8785 has no canonical form for."""


def canonicalise(value: object) -> bytes:
    """The RFC 8785 canonical UTF-8 bytes of ``value``."""
    text = _serialise(value)
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError as error:
        raise CanonicalisationError(f"the value holds text JSON cannot encode: {error}") from error


def declaration_digest(declaration: object) -> str:
    """The Declaration Digest of ``declaration``: the lowercase SHA-256 of its canonical bytes.

    Section 3.1 requires the input to carry no duplicate property names. A mapping cannot
    report its own repeats, so a caller reading a declaration off disk establishes that before
    calling -- ``json_document.repeated_names`` is what records it.
    """
    return hashlib.sha256(canonicalise(declaration)).hexdigest()


def _serialise(value: object) -> str:
    if value is None:
        return "null"
    # bool is a subclass of int, so it has to be answered before the number branch.
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, int | float):
        return _number(value)
    if isinstance(value, Mapping):
        return _object(value)
    # A JSON array only, spelled out: `bytes` is a Sequence too and would serialise as an
    # array of its byte values rather than being refused.
    if isinstance(value, list | tuple):
        return "[" + ",".join(_serialise(item) for item in value) + "]"
    raise CanonicalisationError(f"JSON has no representation for a {type(value).__name__}")


def _object(value: Mapping[object, object]) -> str:
    names = [name for name in value if isinstance(name, str)]
    if len(names) != len(value):
        raise CanonicalisationError("a JSON object property name must be text")
    members = (
        f"{_string(name)}:{_serialise(value[name])}" for name in sorted(names, key=_utf16_units)
    )
    return "{" + ",".join(members) + "}"


def _utf16_units(name: str) -> bytes:
    """The sort key RFC 8785 3.2.3 prescribes.

    Big-endian UTF-16 compares byte by byte exactly as the code units it encodes compare as
    unsigned integers, so the encoded bytes are the ordering without a separate conversion.
    """
    try:
        return name.encode("utf-16-be")
    except UnicodeEncodeError as error:
        raise CanonicalisationError(
            f"a JSON object property name holds text JSON cannot encode: {error}"
        ) from error


def _string(value: str) -> str:
    pieces = ['"']
    for character in value:
        code = ord(character)
        if character in {'"', "\\"}:
            pieces.append("\\" + character)
        elif code >= ASCII_CONTROL_CEILING:
            pieces.append(character)
        elif code in SHORT_ESCAPES:
            pieces.append("\\" + SHORT_ESCAPES[code])
        else:
            pieces.append(f"\\u{code:04x}")
    pieces.append('"')
    return "".join(pieces)


def _number(value: int | float) -> str:
    """ECMAScript ``Number::toString``, which is what RFC 8785 3.2.2.3 defers to.

    Every JSON number is an IEEE 754 double, so an arbitrary-precision integer is narrowed to
    one first rather than being written out at a precision ECMAScript could not have produced.
    """
    try:
        number = float(value)
    except OverflowError as error:
        raise CanonicalisationError("the number is outside the IEEE 754 double range") from error
    if math.isnan(number) or math.isinf(number):
        raise CanonicalisationError("JSON has no representation for NaN or an infinity")
    if number == 0:
        return "0"
    if number < 0:
        return "-" + _positive(-number)
    return _positive(number)


def _positive(number: float) -> str:
    digits, point = _shortest_digits(number)
    count = len(digits)
    if count <= point <= MAX_PLAIN_EXPONENT:
        return digits + "0" * (point - count)
    if 0 < point <= MAX_PLAIN_EXPONENT:
        return digits[:point] + "." + digits[point:]
    if MIN_PLAIN_EXPONENT < point <= 0:
        return "0." + "0" * -point + digits
    mantissa = digits if count == 1 else digits[0] + "." + digits[1:]
    exponent = point - 1
    return f"{mantissa}e{'+' if exponent >= 0 else '-'}{abs(exponent)}"


def _shortest_digits(number: float) -> tuple[str, int]:
    """``number``'s shortest round-tripping decimal digits, and where its point sits.

    The pair is ECMAScript's ``s`` and ``n``: ``number`` equals ``0.<digits> x 10**point``.
    Python's ``repr`` already chooses the shortest digit string that round-trips, which is the
    same choice ECMAScript makes, so only the placement of the point has to be recovered.
    """
    literal, _, exponent = repr(number).partition("e")
    whole, _, fraction = literal.partition(".")
    significant = (whole + fraction).lstrip("0")
    leading_zeros = len(whole + fraction) - len(significant)
    digits = significant.rstrip("0")
    point = len(whole) - leading_zeros + int(exponent or 0)
    return digits, point
