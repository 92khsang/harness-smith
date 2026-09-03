"""How a plugin manifest decides where a plugin's components live.

The manifest is optional and its component path fields override the runtime's default
locations. Resolving those overrides is the whole of this module's job: it answers *where*,
and the scan that consumes the answer decides what is there.

The merge semantics are the runtime's, from https://code.claude.com/docs/en/plugins-reference:

- ``commands``, ``agents``, ``workflows``, ``outputStyles``, ``experimental.themes`` and
  ``experimental.monitors`` **replace** the default location, so declaring one stops the
  default from being scanned
- ``skills`` **adds** to the default, which is always scanned
- ``hooks``, ``mcpServers`` and ``lspServers`` **add** to the default. The reference says only
  that they combine by their own rules and does not write those rules down, so the semantics
  below were read out of the runtime itself, Claude Code 2.1.259, and are recorded here with
  the evidence:

  - ``hooks``: the manifest schema describes the field as "Path to file with additional hooks
    (in addition to those in ``hooks/hooks.json``, if it exists), relative to the plugin root",
    and the loader refuses a manifest path that resolves to the default with "The standard
    ``hooks/hooks.json`` is loaded automatically, so ``manifest.hooks`` should only reference
    additional hook files"
  - ``mcpServers``: "MCP servers to include in the plugin (in addition to those in the
    ``.mcp.json`` file, if it exists)"
  - ``lspServers``: the loader reads ``.lsp.json`` first and merges the manifest's servers over
    it by name, so both locations load and the manifest wins a name collision

  Discovery locates; it does not resolve a name collision between two locations, so the
  precedence above is recorded rather than applied
- ``themes`` and ``monitors`` are read under ``experimental`` first and at the top level only
  as a fallback, because the loader coalesces them that way: ``experimental?.themes ?? themes``
  and ``experimental?.monitors ?? monitors``. A manifest carrying both loads the experimental
  one alone. ``monitors`` **replaces** the default: "When omitted,
  ``monitors/monitors.json`` at the plugin root is loaded if present"

A field that accepts an inline declaration holds the component in the manifest rather than at a
path of its own, and the shape that declares one differs by field:

- ``hooks``, ``mcpServers`` and ``lspServers`` take an object, and their lists may mix paths
  with inline objects
- ``monitors`` takes the monitors array itself, so a list there is never a list of paths. The
  validator refuses ``["./monitors.json"]`` and any list mixing paths with entries, so neither
  declares a location
- ``mcpServers`` also takes a URL naming a remote MCPB bundle. The bundle is not in the plugin,
  so the component is located where it is declared, at the manifest
- ``commands`` takes an object mapping command names to definitions. A definition's ``source``
  names a Markdown file and resolves like any other path. A definition's ``content`` writes the
  command out in the manifest instead, which makes it an artifact addressed by a pointer into
  the manifest; that is not discovered here, and #35 owns it

Every other field takes a path or a list of them, so an object or an array of objects there
declares no location at all.

Every path must be relative to the plugin root and start with ``./``, and ``skills`` alone also
accepts ``"."``; both spellings denote the plugin root. A declared path that is inside the root
but does not follow that syntax resolves to no location, because reading it as a path anyway
would let ``""`` scan the whole plugin root. Which spellings are valid is the official
validator's question, so no finding is raised for one here.

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
import re
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

# A command definition names its Markdown file here; a definition that writes the command out in
# the manifest instead is addressed by a pointer into it, which #35 owns.
DEFINITION_SOURCE = "source"

# A declared value carrying a scheme names something outside the plugin, such as the remote MCPB
# bundle `mcpServers` accepts. It is not a path in the plugin, so it resolves to no Locator there.
REMOTE_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://")

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


class Inline(StrEnum):
    """The shape that declares a component inside the manifest, where a field accepts one."""

    NONE = "none"
    OBJECT = "object"
    ARRAY = "array"


@dataclass(frozen=True)
class ComponentSpec:
    default: str
    merge: Merge
    experimental: bool = False
    inline: Inline = Inline.NONE
    definitions: bool = False
    remote: bool = False


SPECS: Mapping[Component, ComponentSpec] = {
    Component.SKILLS: ComponentSpec("skills", Merge.KEEPS_DEFAULT),
    Component.COMMANDS: ComponentSpec("commands", Merge.REPLACES, definitions=True),
    Component.AGENTS: ComponentSpec("agents", Merge.REPLACES),
    Component.WORKFLOWS: ComponentSpec("workflows", Merge.REPLACES),
    Component.OUTPUT_STYLES: ComponentSpec("output-styles", Merge.REPLACES),
    Component.THEMES: ComponentSpec("themes", Merge.REPLACES, experimental=True),
    Component.MONITORS: ComponentSpec(
        "monitors/monitors.json", Merge.REPLACES, experimental=True, inline=Inline.ARRAY
    ),
    Component.HOOKS: ComponentSpec("hooks/hooks.json", Merge.KEEPS_DEFAULT, inline=Inline.OBJECT),
    Component.MCP_SERVERS: ComponentSpec(
        ".mcp.json", Merge.KEEPS_DEFAULT, inline=Inline.OBJECT, remote=True
    ),
    Component.LSP_SERVERS: ComponentSpec(".lsp.json", Merge.KEEPS_DEFAULT, inline=Inline.OBJECT),
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
    """What the manifest said about one component, once the winning key has been read."""

    present: bool = False
    paths: tuple[str, ...] = ()
    inline: bool = False
    ambiguous: bool = False


@dataclass(frozen=True)
class _Source:
    """The one key that decides a component's location, and whether it can be read at all."""

    present: bool = False
    value: object = None
    ambiguous: bool = False


def resolve(root: Path) -> Resolution:
    """Resolve every component's locations against the manifest at ``root``."""
    document = read_json_document(root / MANIFEST)
    members = document.members if document.state is JsonDocumentState.PARSED else {}
    locations: dict[Component, tuple[str, ...]] = {}
    diagnostics: list[Diagnostic] = []

    for component, spec in SPECS.items():
        declared = _declaration(members, component, spec)
        if declared.ambiguous:
            diagnostics.append(_ambiguity(component))
            locations[component] = _kept_default(spec)
            continue
        resolved: list[str] = []
        for path in declared.paths:
            inside = _inside(root, path)
            if inside is None:
                diagnostics.append(_escape(component, path))
                continue
            if _accepted(component, path):
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
    """What ``members`` declares for one component, read at the shapes the field accepts.

    A value of a shape the field does not accept declares no location. Its shape is the
    official validator's question, and the key still counts as declared.
    """
    source = _source(members, component, spec)
    if not source.present or source.ambiguous:
        return _Declaration(source.present, ambiguous=source.ambiguous)
    value = source.value
    if isinstance(value, list):
        return _from_list(spec, value)
    if isinstance(value, dict):
        paths = _definition_paths(value) if spec.definitions else ()
        return _Declaration(True, paths, spec.inline is Inline.OBJECT)
    if isinstance(value, str):
        paths, remote = _split(spec, (value,))
        return _Declaration(True, paths, remote)
    return _Declaration(True)


def _from_list(spec: ComponentSpec, value: list[object]) -> _Declaration:
    """A list of paths, or the inline declaration a list itself can be.

    Where a field takes the inline component as an array, a list is that array and never a list
    of paths: the validator refuses a list of path strings there, and refuses one mixing paths
    with entries, so neither declares a location.
    """
    if spec.inline is Inline.ARRAY:
        return _Declaration(True, inline=all(isinstance(entry, dict) for entry in value))
    paths, remote = _split(spec, tuple(entry for entry in value if isinstance(entry, str)))
    holds_object = spec.inline is Inline.OBJECT and any(isinstance(entry, dict) for entry in value)
    return _Declaration(True, paths, remote or holds_object)


def _split(spec: ComponentSpec, declared: tuple[str, ...]) -> tuple[tuple[str, ...], bool]:
    """``declared`` split into the paths inside the plugin and whether any of it is remote.

    A remote value names something the plugin does not contain, so it resolves to no Locator
    there and the component is located where it is declared instead. One list may carry both.
    """
    if not spec.remote:
        return declared, False
    paths = tuple(entry for entry in declared if not _remote(entry))
    return paths, len(paths) < len(declared)


def _definition_paths(definitions: Mapping[str, object]) -> tuple[str, ...]:
    """The Markdown files a command-definition map names.

    A definition that writes its command out in the manifest instead of naming a file is an
    artifact addressed by a pointer into the manifest, which #35 owns; it names no path here.
    """
    found = []
    for definition in definitions.values():
        if not isinstance(definition, dict):
            continue
        source = definition.get(DEFINITION_SOURCE)
        if isinstance(source, str):
            found.append(source)
    return tuple(found)


def _source(members: Mapping[str, object], component: Component, spec: ComponentSpec) -> _Source:
    """The one key the runtime reads a component's location from.

    An experimental component is coalesced, ``experimental?.<key> ?? <key>``, so declaring the
    experimental key makes the top-level one dead rather than additional. Whether the key
    repeated is asked of the key that wins, because a repeat only matters where it decides.
    """
    key = component.value
    if spec.experimental:
        if EXPERIMENTAL_MEMBER in own_repeated_names(members):
            return _Source(present=True, ambiguous=True)
        experimental = members.get(EXPERIMENTAL_MEMBER)
        if isinstance(experimental, dict) and key in experimental:
            if key in own_repeated_names(experimental):
                return _Source(present=True, ambiguous=True)
            return _Source(present=True, value=experimental[key])
    if key not in members:
        return _Source()
    if key in own_repeated_names(members):
        return _Source(present=True, ambiguous=True)
    return _Source(present=True, value=members[key])


def _remote(declared: str) -> str | None:
    """The scheme of a declared value that names something outside the plugin, if it has one."""
    match = REMOTE_SCHEME.match(declared)
    return match.group(0) if match else None


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


def _accepted(component: Component, declared: str) -> bool:
    """Whether ``declared`` follows the path syntax the runtime requires of a manifest path.

    A path inside the root that does not follow it is dropped rather than reported: which
    spellings are valid is the official validator's question. Dropping it is what stops ``""``,
    which normalises to the plugin root, from turning a component into a scan of the whole
    plugin.
    """
    if declared.startswith(f"{PLUGIN_ROOT}/"):
        return True
    return declared == PLUGIN_ROOT and component is Component.SKILLS


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
