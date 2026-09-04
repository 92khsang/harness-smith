"""The closed shape of one entry in a governance file.

Both files close their key sets at every level: an unknown key is a mistake somebody made
rather than an extension point, and reading past one would ignore a policy that was written
down. Every value in them decides something too, so a field of the wrong type is refused
rather than carried into a decision as though somebody had written what it is read as.

Each kind of entry declares its fields once, as a table, and one reader applies them. A check
written per field at each call site is a check that gets forgotten at the next one, and the
fields a governance file admits are exactly the ones its schema documents.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

__all__ = ["Field", "Kind", "Shape", "listed", "mapping"]


class Kind(StrEnum):
    TEXT = "text"
    INTEGER = "integer"
    ENTRY = "entry"


@dataclass(frozen=True)
class Field:
    """One field of an entry: what it is called, what it may hold, and whether it is needed."""

    name: str
    kind: Kind = Kind.TEXT
    required: bool = False
    values: tuple[str, ...] = ()
    shape: Shape | None = None

    def check(self, value: object, where: str) -> str | None:
        if self.kind is Kind.ENTRY:
            assert self.shape is not None
            return self.shape.check(value, f"{where}'s `{self.name}`")
        if self.kind is Kind.INTEGER:
            if isinstance(value, bool) or not isinstance(value, int):
                return f"{where}'s `{self.name}` is not an integer"
            return None
        if not isinstance(value, str):
            return f"{where}'s `{self.name}` is not text"
        if self.values and value not in self.values:
            allowed = ", ".join(self.values)
            return f"{where}'s `{self.name}` is `{value}`, which is not one of {allowed}"
        return None


@dataclass(frozen=True)
class Shape:
    """The fields one kind of entry may hold, and which of them it must."""

    fields: tuple[Field, ...]

    def check(self, value: object, where: str) -> str | None:
        """Why ``value`` is not an entry of this shape, or ``None``."""
        reason = mapping(value, where)
        if reason:
            return reason
        assert isinstance(value, dict)
        return self._closed(value, where) or self._members(value, where)

    def _closed(self, entry: Mapping[str, object], where: str) -> str | None:
        unknown = sorted(set(entry) - {field.name for field in self.fields})
        return f"{where} has an unknown key `{unknown[0]}`" if unknown else None

    def _members(self, entry: Mapping[str, object], where: str) -> str | None:
        for field in self.fields:
            if field.name not in entry:
                if field.required:
                    return f"{where} is missing `{field.name}`"
                continue
            reason = field.check(entry[field.name], where)
            if reason:
                return reason
        return None


def mapping(value: object, where: str) -> str | None:
    return None if isinstance(value, dict) else f"{where} is not a mapping"


def listed(value: object, where: str) -> str | None:
    return None if isinstance(value, list) else f"{where} is not a list"
