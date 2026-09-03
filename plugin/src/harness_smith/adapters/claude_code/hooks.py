"""Reading hook declarations out of a JSON Artifact Container.

Every settings file the runtime reads hooks from — the project's, the user's, the managed
policy's — and a plugin's own hook file are the same shape, so they are read one way. What
differs is the container's Locator and the Scope it was found in, which the caller supplies
because the file alone does not say.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from harness_smith.artifacts import HookDeclaration, Scope
from harness_smith.canonical_json import CanonicalisationError, declaration_digest
from harness_smith.json_document import (
    JsonDocument,
    JsonDocumentState,
    own_repeated_names,
    repeated_names,
)

__all__ = ["CONTAINER_FINDINGS", "HOOKS_MEMBER", "Hooks", "read"]

# The one member of a settings file this adapter reads; everything else in it is
# configuration the runtime owns and harness-smith leaves alone.
HOOKS_MEMBER = "hooks"

# What went wrong before the container's members could be read at all. The three are separate
# codes because they are separate fixes: repair the file, repair its JSON, or repair its shape.
CONTAINER_FINDINGS: Mapping[JsonDocumentState, str] = {
    JsonDocumentState.FILE_UNREADABLE: "HS-HOOK-CONTAINER-FILE-UNREADABLE",
    JsonDocumentState.UNPARSEABLE: "HS-HOOK-CONTAINER-UNPARSEABLE",
    JsonDocumentState.NOT_AN_OBJECT: "HS-HOOK-CONTAINER-INVALID",
}

INVALID = "HS-HOOK-CONTAINER-INVALID"


@dataclass(frozen=True)
class Hooks:
    """A container's hook declarations, or the finding that says why there are none."""

    declarations: tuple[HookDeclaration, ...] = ()
    code: str = ""
    reason: str = ""


def read(document: JsonDocument, container: str, scope: Scope) -> Hooks:
    """Every hook declaration in ``document``, each addressed by a JSON Pointer and digested.

    One declaration is one matcher group. The matcher and the ordered actions it runs are a
    single execution declaration, and reordering those actions changes what runs, so the group
    is addressed whole at ``<container>#/hooks/<event>/<index>`` rather than per action.

    Reading is all or nothing. A container read only in part would hand out pointers computed
    past a shape the reader did not expect, and those pointers would address something other
    than the declarations they name; and a declaration whose digest cannot be computed would
    leave the container half identified. Either way no hook in it resolves.

    A repeated property name is refused everywhere it would decide what is discovered: the
    ``hooks`` member itself, an event inside it, and anything inside a declaration. Which of
    two same-named members the runtime keeps is not recorded anywhere this project has
    verified, so a repeat there is reported rather than resolved by picking one. A repeat in
    configuration that is not a hook decides nothing here and is left alone.
    """
    if document.state is not JsonDocumentState.PARSED:
        return Hooks(code=CONTAINER_FINDINGS[document.state], reason=document.reason)
    if HOOKS_MEMBER in own_repeated_names(document.members):
        return _invalid(f"the `{HOOKS_MEMBER}` member is declared more than once")
    events = document.members.get(HOOKS_MEMBER)
    if events is None:
        return Hooks()
    if not isinstance(events, dict):
        return _invalid(f"the `{HOOKS_MEMBER}` member is not an object of hook events")
    repeated_events = own_repeated_names(events)
    if repeated_events:
        return _invalid(f"the `{repeated_events[0]}` hook event is declared more than once")
    declarations: list[HookDeclaration] = []
    for event in sorted(events):
        group = events[event]
        if not isinstance(group, list):
            return _invalid(f"the `{event}` hook event is not an array of declarations")
        for index, declaration in enumerate(group):
            if not isinstance(declaration, dict):
                return _invalid(
                    f"the `{event}` hook event holds a declaration that is not an object"
                )
            locator = f"{container}#/{HOOKS_MEMBER}/{_pointer_token(event)}/{index}"
            digested = _digest(locator, declaration, scope)
            if digested is None:
                return _invalid(_digest_reason(event, index, declaration))
            declarations.append(digested)
    return Hooks(tuple(declarations))


def _digest(
    locator: str, declaration: Mapping[str, object], scope: Scope
) -> HookDeclaration | None:
    """``declaration`` with its Declaration Digest, or nothing when RFC 8785 refuses it.

    Section 3.1 admits only declarations with no duplicate property names, whose strings are
    Unicode and whose numbers are IEEE 754 doubles. Digesting one that fails those conditions
    and calling the result an RFC 8785 digest would be a false claim, so it is refused instead.
    """
    if repeated_names(declaration):
        return None
    try:
        return HookDeclaration(locator, declaration_digest(declaration), scope)
    except CanonicalisationError:
        return None


def _digest_reason(event: str, index: int, declaration: Mapping[str, object]) -> str:
    where = f"the declaration at index {index} of the `{event}` hook event"
    repeated = repeated_names(declaration)
    if repeated:
        return f"{where} repeats the property name `{repeated[0]}`"
    return f"{where} holds a value that has no canonical JSON form"


def _invalid(reason: str) -> Hooks:
    return Hooks(code=INVALID, reason=reason)


def _pointer_token(name: str) -> str:
    """One JSON Pointer reference token, per RFC 6901: ``~`` becomes ``~0`` and ``/`` becomes
    ``~1``, in that order, so that a name carrying either stays one segment."""
    return name.replace("~", "~0").replace("/", "~1")
