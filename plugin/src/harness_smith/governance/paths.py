"""The relative paths a governance file carries: the keys its entries sit under, and the
fields inside them that name a file.

A path is checked before it is used, and refused when it is not one this tool may act on,
rather than coerced into one. A key decides who may write a file, and a path field says where
a relation's evidence or an adopted seed lives, so either naming somewhere outside its root —
an absolute path, a drive, a network share, a step through `..` — would carry a decision to a
file nobody declared. Reading past one is worse than refusing the file it appears in.

A path is normalised lexically and never resolved against the filesystem: resolving would
follow symlinks and answer differently on different machines, and these files are compared,
diffed and merged by people who are not on the machine that wrote them. A `..` is refused for
the same reason rather than collapsed — with a symlink in the way the collapsed spelling and
the resolved one name two different files, and neither is an answer this tool can stand
behind. A `.` is dropped, because it names the same directory either way.

Keys are normalised here, because two spellings of one path are one key, and that is what
makes "a path appearing twice in one mapping" a rule with something to catch. A path field is
validated here and kept as written: the reader that compares it against a tree — a plugin's,
for evidence, or this repository's, for a seed or an entry point — normalises it with the same
``normalised`` at the point of comparison, so the manifest exposes what a person wrote and one
spelling is what gets compared.
"""

from __future__ import annotations

__all__ = ["flaw", "normalised", "refused"]

CURRENT = "."
PARENT = ".."
SEPARATOR = "/"
POINTER = "#"
NUL = "\x00"
ESCAPE = "~"
ESCAPED = ("0", "1")


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
        clause = _pointer_flaw(pointer)
        if clause:
            return f"{where} is keyed by `{key}`, {clause}"
    clause = flaw(path)
    if clause is None:
        return None
    if _shown(path):
        return f"{where} is keyed by `{key}`, which {clause}"
    return f"{where} is keyed by a path that {clause}"


def flaw(path: str) -> str | None:
    """What keeps ``path`` from being a relative path inside its root, as a clause that
    follows the path's name, or ``None``."""
    if NUL in path:
        return "holds a NUL"
    forward = path.replace("\\", SEPARATOR)
    if forward.startswith(SEPARATOR * 2):
        return "names a network share"
    if forward.startswith(SEPARATOR):
        return "is absolute"
    if _drive(forward):
        return "names a drive"
    segments = _segments(path)
    if not segments:
        return "names nothing"
    if PARENT in segments:
        return "steps outside its root"
    return None


def normalised(key: str) -> str:
    """``key`` as the one spelling paths are compared by.

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


def _pointer_flaw(pointer: str) -> str | None:
    """RFC 6901: a pointer that reaches into a document starts with `/`, and `~` appears only
    as `~0` or `~1`. A `~` escaping nothing is not a pointer #36 can resolve, and refusing it
    here keeps a malformed key from being read later as a declaration that drifted or moved."""
    if not pointer.startswith(SEPARATOR):
        return "whose `#` is not followed by a JSON Pointer"
    for index, character in enumerate(pointer):
        if character == ESCAPE and pointer[index + 1 : index + 2] not in ESCAPED:
            return "whose pointer holds a `~` that is not `~0` or `~1`"
    return None


def _shown(path: str) -> bool:
    """Whether a message may echo the path: an empty one says nothing, and one holding a NUL
    would put a NUL in a document."""
    return bool(path) and NUL not in path


def _drive(forward: str) -> bool:
    """A Windows drive-qualified path: one letter, a colon, and whatever follows."""
    return len(forward) >= 2 and forward[0].isalpha() and forward[1] == ":"
