"""The repository-relative paths a governance file keys its entries by.

A key is checked before it is used, and refused when it is not a path this tool may act on,
rather than coerced into one. A key decides who may write a file, so a key naming somewhere
outside the repository — an absolute path, a drive, a network share, a step through `..` —
would decide that for a file nobody declared. Reading past one is worse than refusing the
file it appears in.

A path is normalised lexically and never resolved against the filesystem: resolving would
follow symlinks and answer differently on different machines, and these files are compared,
diffed and merged by people who are not on the machine that wrote them. A `..` is refused for
the same reason rather than collapsed — with a symlink in the way the collapsed spelling and
the resolved one name two different files, and neither is an answer this tool can stand
behind. A `.` is dropped, because it names the same directory either way.

Two spellings of one path are one key. That is what makes "a path appearing twice in one
mapping" a rule with something to catch: `docs/x.md` and `./docs/x.md` name one file.
"""

from __future__ import annotations

__all__ = ["normalised", "refused"]

CURRENT = "."
PARENT = ".."
SEPARATOR = "/"
POINTER = "#"
NUL = "\x00"


def refused(key: object, where: str, *, locator: bool = False) -> str | None:
    """Why ``key`` is not a path an entry may be keyed by, or ``None``.

    ``locator`` also admits a Locator: a path, then `#` and a JSON Pointer into the file it
    names, which is how the lock keys a declaration held inside an Artifact Container.
    """
    if not isinstance(key, str):
        return f"{where} has a key that is not text: {key!r}"
    path, pointer = _split(key)
    if pointer is not None:
        if not locator:
            return f"{where} is keyed by `{key}`, and a path here holds no pointer"
        if not pointer.startswith(SEPARATOR):
            return f"{where} is keyed by `{key}`, whose `#` is not followed by a JSON Pointer"
    return _path_refused(path, key, where)


def normalised(key: str) -> str:
    """``key`` as the one spelling entries are compared by.

    Separators become forward slashes, `.` segments and empty ones drop out, and a Locator's
    pointer is kept as it was written: it addresses a position inside a document rather than a
    place in the filesystem.
    """
    path, pointer = _split(key)
    normal = SEPARATOR.join(_segments(path))
    return normal if pointer is None else f"{normal}{POINTER}{pointer}"


def _split(key: str) -> tuple[str, str | None]:
    path, marker, pointer = key.partition(POINTER)
    return (path, pointer) if marker else (path, None)


def _segments(path: str) -> list[str]:
    forward = path.replace("\\", SEPARATOR)
    return [segment for segment in forward.split(SEPARATOR) if segment not in ("", CURRENT)]


def _path_refused(path: str, key: str, where: str) -> str | None:
    if NUL in path:
        return f"{where} is keyed by a path holding a NUL"
    forward = path.replace("\\", SEPARATOR)
    if forward.startswith(SEPARATOR * 2):
        return f"{where} is keyed by `{key}`, which names a network share"
    if forward.startswith(SEPARATOR):
        return f"{where} is keyed by `{key}`, which is absolute"
    if _drive(forward):
        return f"{where} is keyed by `{key}`, which names a drive"
    segments = _segments(path)
    if not segments:
        return f"{where} is keyed by a path naming nothing"
    if PARENT in segments:
        return f"{where} is keyed by `{key}`, which steps outside the repository"
    return None


def _drive(forward: str) -> bool:
    """A Windows drive-qualified path: one letter, a colon, and whatever follows."""
    return len(forward) >= 2 and forward[0].isalpha() and forward[1] == ":"
