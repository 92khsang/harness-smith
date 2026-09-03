"""Checking the shape of a governance file's entries.

Both files close their key sets: an unknown key is a mistake someone made, not an extension
point, and reading past one would silently ignore a policy somebody wrote down. These are the
few checks both readers need, each returning the reason a caller reports rather than raising,
so that one file's first problem is the one reported.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

__all__ = ["closed", "listed", "mapping", "one_of", "required", "text"]


def closed(entry: Mapping[str, object], allowed: Iterable[str], where: str) -> str | None:
    """No key beyond the ones this kind of entry defines."""
    unknown = sorted(set(entry) - set(allowed))
    return f"{where} has an unknown key `{unknown[0]}`" if unknown else None


def required(entry: Mapping[str, object], names: Iterable[str], where: str) -> str | None:
    missing = [name for name in names if name not in entry]
    return f"{where} is missing `{missing[0]}`" if missing else None


def mapping(value: object, where: str) -> str | None:
    return None if isinstance(value, dict) else f"{where} is not a mapping"


def listed(value: object, where: str) -> str | None:
    return None if isinstance(value, list) else f"{where} is not a list"


def text(entry: Mapping[str, object], names: Iterable[str], where: str) -> str | None:
    wrong = [name for name in names if name in entry and not isinstance(entry[name], str)]
    return f"{where} has a `{wrong[0]}` that is not text" if wrong else None


def one_of(value: object, allowed: Iterable[str], where: str) -> str | None:
    if isinstance(value, str) and value in set(allowed):
        return None
    return f"{where} is `{value!r}`, which is not one of {', '.join(sorted(allowed))}"
