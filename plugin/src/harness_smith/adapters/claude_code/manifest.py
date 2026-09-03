"""How a plugin manifest decides where a plugin's components live.

The manifest is optional and its component path fields override the runtime's default
locations. Resolving those overrides is the whole of this module's job: it answers *where*,
and the scan that consumes the answer decides what is there.

The merge semantics are the runtime's, from https://code.claude.com/docs/en/plugins-reference:

- ``commands``, ``agents``, ``workflows``, ``outputStyles``, ``experimental.themes`` and
  ``experimental.monitors`` **replace** the default location, so declaring one stops the
  default from being scanned
- ``skills`` **adds** to the default, which is always scanned
- ``hooks``, ``mcpServers`` and ``lspServers`` are documented as combining by their own rules,
  and those rules are not written down anywhere this project has verified. Discovery keeps the
  default alongside whatever the manifest declares rather than inventing a precedence, and
  never reports one as hiding the other
- ``themes`` and ``monitors`` are read under ``experimental`` and at the top level, because the
  documentation says the top-level spelling still works while ``experimental.*`` becomes
  required, and does not say which wins when a manifest carries both
- ``hooks``, ``mcpServers`` and ``lspServers`` also accept an inline object, which declares the
  component in the manifest rather than at a path of its own. The remaining fields take a path
  or a list of them, so an object there declares no location at all

One documented exception is out of this scan's reach. A marketplace entry whose ``source``
resolves to the marketplace root makes ``skills`` replace the default rather than add to it,
and that condition lives in the marketplace entry, which a plugin root does not carry.

Two rules bound the paths themselves. Every path is relative to the plugin root, and the
runtime rejects one that resolves outside it, loading the plugin without that component. And
whether the manifest is *valid* is `claude plugin validate`'s question: a manifest that cannot
be read as an object declares no overrides here, and no finding is raised in the validator's
place.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePath

from harness_smith.adapters.claude_code import tree
from harness_smith.diagnostics import Diagnostic
from harness_smith.json_document import JsonDocumentState, own_repeated_names, read_json_document
from harness_smith.vocabulary import Subject, SubjectKind

__all__ = ["MANIFEST", "Component", "Merge", "Resolution", "resolve"]

MANIFEST = ".claude-plugin/plugin.json"
EXPERIMENTAL_MEMBER = "experimental"

# The plugin root, as a location and as the Locator of the Surface a manifest finding is about.
PLUGIN_ROOT = "."


class Component(StrEnum):
    """A component whose location the manifest may override, named by the key that does it."""

    SKILLS = "skills"
    COMMANDS = "commands"
    AGENTS = "agents"
    WORKFLOWS = "workflows"
    OUTPUT_STYLES = "outputStyles"
    THEMES = "themes"
    MONITORS = "monitors"
    HOOKS = "hooks"
    MCP_SERVERS = "mcpServers"
    LSP_SERVERS = "lspServers"


class Merge(StrEnum):
    """What declaring a key does to the default location."""

    REPLACES = "replaces"
    KEEPS_DEFAULT = "keeps-default"


@dataclass(frozen=True)
class ComponentSpec:
    default: str
    merge: Merge
    experimental: bool = False
    accepts_inline: bool = False


SPECS: Mapping[Component, ComponentSpec] = {
    Component.SKILLS: ComponentSpec("skills", Merge.KEEPS_DEFAULT),
    Component.COMMANDS: ComponentSpec("commands", Merge.REPLACES),
    Component.AGENTS: ComponentSpec("agents", Merge.REPLACES),
    Component.WORKFLOWS: ComponentSpec("workflows", Merge.REPLACES),
    Component.OUTPUT_STYLES: ComponentSpec("output-styles", Merge.REPLACES),
    Component.THEMES: ComponentSpec("themes", Merge.REPLACES, experimental=True),
    Component.MONITORS: ComponentSpec("monitors/monitors.json", Merge.REPLACES, experimental=True),
    Component.HOOKS: ComponentSpec("hooks/hooks.json", Merge.KEEPS_DEFAULT, accepts_inline=True),
    Component.MCP_SERVERS: ComponentSpec(".mcp.json", Merge.KEEPS_DEFAULT, accepts_inline=True),
    Component.LSP_SERVERS: ComponentSpec(".lsp.json", Merge.KEEPS_DEFAULT, accepts_inline=True),
}


@dataclass(frozen=True)
class Resolution:
    """Where each component's locations are, once the manifest has had its say.

    A location is a Locator relative to the plugin root, and is where the component would be
    rather than a claim that anything is there.
    """

    locations: Mapping[Component, tuple[str, ...]]
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class _Declaration:
    """What the manifest said about one component."""

    present: bool = False
    paths: tuple[str, ...] = ()
    inline: bool = False


def resolve(root: Path) -> Resolution:
    """Resolve every component's locations against the manifest at ``root``."""
    document = read_json_document(root / MANIFEST)
    members = document.members if document.state is JsonDocumentState.PARSED else {}
    ambiguous = _ambiguous(members)
    locations: dict[Component, tuple[str, ...]] = {}
    diagnostics: list[Diagnostic] = []

    for component, spec in SPECS.items():
        if component in ambiguous:
            diagnostics.append(_ambiguity(component))
            locations[component] = _kept_default(spec)
            continue
        declared = _declaration(members, component, spec)
        resolved: list[str] = []
        for path in declared.paths:
            inside = _inside(root, path)
            if inside is None:
                diagnostics.append(_escape(component, path))
                continue
            resolved.append(inside)
        if declared.inline:
            resolved.append(MANIFEST)
        default = () if declared.present and spec.merge is Merge.REPLACES else (spec.default,)
        locations[component] = _unique(
            (*default, *resolved, *_root_skill(root, component, spec, declared))
        )
        shadowed = _shadow(root, component, spec, declared, locations[component])
        if shadowed is not None:
            diagnostics.append(shadowed)

    return Resolution(locations, tuple(diagnostics))


def _kept_default(spec: ComponentSpec) -> tuple[str, ...]:
    """What survives a key that cannot be read. A key that replaces the default takes the
    default with it, because whether it listed the default is exactly what is unknown; a key
    that adds to one costs only the additions it declared."""
    return () if spec.merge is Merge.REPLACES else (spec.default,)


def _declaration(
    members: Mapping[str, object], component: Component, spec: ComponentSpec
) -> _Declaration:
    """What ``members`` declares for one component, under every key the runtime accepts.

    A value that is neither a path, a list of paths, nor an inline object the field accepts
    declares no location. Its shape is the official validator's question, and the key still
    counts as declared.
    """
    present = False
    paths: list[str] = []
    inline = False
    for value in _declared_values(members, component, spec):
        present = True
        if isinstance(value, str):
            paths.append(value)
        elif isinstance(value, list):
            paths.extend(entry for entry in value if isinstance(entry, str))
        elif isinstance(value, dict) and spec.accepts_inline:
            inline = True
    return _Declaration(present, tuple(paths), inline)


def _declared_values(
    members: Mapping[str, object], component: Component, spec: ComponentSpec
) -> list[object]:
    values = [members[component.value]] if component.value in members else []
    if not spec.experimental:
        return values
    experimental = members.get(EXPERIMENTAL_MEMBER)
    if isinstance(experimental, dict) and component.value in experimental:
        values.append(experimental[component.value])
    return values


def _root_skill(
    root: Path, component: Component, spec: ComponentSpec, declared: _Declaration
) -> tuple[str, ...]:
    """The plugin root, where a plugin that ships exactly one skill puts its ``SKILL.md``.

    The runtime loads that layout only when there is no ``skills/`` directory and no ``skills``
    key, so a plugin written this way needs no declaration of its own.
    """
    if component is not Component.SKILLS or declared.present:
        return ()
    if (root / spec.default).is_dir() or not (root / tree.SKILL_FILE).is_file():
        return ()
    return (PLUGIN_ROOT,)


def _shadow(
    root: Path,
    component: Component,
    spec: ComponentSpec,
    declared: _Declaration,
    locations: tuple[str, ...],
) -> Diagnostic | None:
    """A key that replaces the default hides whatever is at the default location. Keeping it
    is one line of manifest, and losing it silently is the failure worth reporting."""
    if spec.merge is not Merge.REPLACES or not declared.present:
        return None
    if spec.default in locations or not (root / spec.default).exists():
        return None
    return _finding(
        "HS-PLUGIN-SHADOWED-DEFAULT-DIR",
        f"the `{component.value}` key in `{MANIFEST}` does not list the default "
        f"`{spec.default}`, which exists and is no longer loaded",
        affected=(spec.default,),
    )


def _escape(component: Component, declared: str) -> Diagnostic:
    return _finding(
        "HS-PLUGIN-COMPONENT-PATH-ESCAPES-ROOT",
        f"the `{component.value}` path `{declared}` in `{MANIFEST}` resolves outside the "
        "plugin root, so the runtime loads the plugin without that component",
    )


def _ambiguity(component: Component) -> Diagnostic:
    return _finding(
        "HS-PLUGIN-MANIFEST-AMBIGUOUS",
        f"`{MANIFEST}` declares the `{component.value}` key more than once, so where the "
        "runtime loads that component from is not decided",
    )


def _finding(code: str, message: str, affected: Iterable[str] = ()) -> Diagnostic:
    """A manifest finding is about the plugin Surface's component layout rather than about any
    one artifact, so the Surface is its subject and the plugin root locates it. The manifest to
    repair is named in the message, because a Surface is a scope boundary and not a file."""
    return Diagnostic.of(
        code, Subject(SubjectKind.SURFACE, PLUGIN_ROOT), message=message, affected=affected
    )


def _ambiguous(members: Mapping[str, object]) -> frozenset[Component]:
    """The components whose key repeated, anywhere that decides where they are loaded from.

    Which of two same-named members the runtime keeps is not recorded anywhere this project has
    verified, so a repeat there is reported rather than resolved by picking one.
    """
    repeated = set(own_repeated_names(members))
    inside = set(own_repeated_names(members.get(EXPERIMENTAL_MEMBER)))
    return frozenset(
        component
        for component, spec in SPECS.items()
        if component.value in repeated
        or (spec.experimental and (EXPERIMENTAL_MEMBER in repeated or component.value in inside))
    )


def _inside(root: Path, declared: str) -> str | None:
    """``declared`` as a Locator inside the plugin root, or nothing when it leaves.

    Resolution is lexical: ``..`` is collapsed without asking the filesystem, so the answer is
    the same whether or not the path exists and does not turn on a symlink somewhere along it.
    """
    base = os.path.normpath(root)
    candidate = os.path.normpath(os.path.join(base, declared))
    if candidate != base and not candidate.startswith(base + os.sep):
        return None
    return PurePath(os.path.relpath(candidate, base)).as_posix()


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))
