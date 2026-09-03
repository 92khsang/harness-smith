"""Manifest-aware plugin discovery, at the adapter's own contract.

A plugin is scanned at the locations its manifest and the runtime's defaults put its
components in, and nowhere else. The adapter promises no compatibility to anything outside the
package, so it is tested directly rather than only through a golden document.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from harness_smith.adapters.claude_code import discover_plugin
from harness_smith.adapters.claude_code.manifest import PLUGIN_ROOT, Component, resolve
from harness_smith.artifacts import (
    Activation,
    ActivationCause,
    ArtifactType,
    CapabilityPolicy,
    CapabilityValue,
    Discovery,
    GovernanceSet,
    ManagementAuthority,
    Provenance,
    Representation,
    Scope,
)
from harness_smith.vocabulary import SubjectKind
from tests.support import write_tree

MANIFEST = ".claude-plugin/plugin.json"

AMBIGUOUS = "HS-PLUGIN-MANIFEST-AMBIGUOUS"
ESCAPES = "HS-PLUGIN-COMPONENT-PATH-ESCAPES-ROOT"
SHADOWED = "HS-PLUGIN-SHADOWED-DEFAULT-DIR"

SKILL = "---\nname: audit\n---\n\n# audit\n"


def manifest(**members: object) -> str:
    return json.dumps(members, indent=2) + "\n"


def scan(tmp_path: Path, files: Mapping[str, str]) -> Discovery:
    return discover_plugin(write_tree(tmp_path / "plugin", files))


def locators(discovery: Discovery, artifact_type: ArtifactType | None = None) -> list[str]:
    return sorted(
        artifact.locator
        for artifact in discovery.report.artifacts
        if artifact_type is None or artifact.type is artifact_type
    )


def codes(discovery: Discovery) -> list[str]:
    return [diagnostic.code for diagnostic in discovery.diagnostics]


def observed(discovery: Discovery) -> list[tuple[str, str]]:
    return sorted((entry.component, entry.locator) for entry in discovery.report.observations)


def components(discovery: Discovery) -> list[str]:
    return sorted(entry.component for entry in discovery.report.observations)


def test_a_plugin_with_no_components_discovers_nothing(tmp_path: Path) -> None:
    discovery = scan(tmp_path, {"README.md": "# readme\n"})

    assert discovery.report.artifacts == ()
    assert discovery.report.containers == ()
    assert discovery.report.observations == ()
    assert discovery.diagnostics == ()


def test_the_default_component_directories_are_scanned_without_a_manifest(
    tmp_path: Path,
) -> None:
    """The manifest is optional; the runtime discovers components at their default locations
    when there is none."""
    discovery = scan(
        tmp_path,
        {
            "skills/audit/SKILL.md": SKILL,
            "commands/status.md": "# status\n",
            "agents/reviewer.md": "# reviewer\n",
        },
    )

    assert locators(discovery, ArtifactType.SKILL) == [
        "commands/status.md",
        "skills/audit/SKILL.md",
    ]
    assert locators(discovery, ArtifactType.AGENT) == ["agents/reviewer.md"]
    assert codes(discovery) == []


def test_a_discovered_plugin_artifact_is_inventoried_in_plugin_scope(tmp_path: Path) -> None:
    discovery = scan(tmp_path, {"skills/audit/SKILL.md": SKILL})

    (skill,) = discovery.report.artifacts

    assert skill.scope is Scope.PLUGIN
    assert skill.representation is Representation.DIRECTORY
    assert skill.provenance is Provenance.AUTHORED
    assert skill.management_authority is ManagementAuthority.UNKNOWN
    assert skill.activation is Activation.UNKNOWN
    assert skill.activation_cause is ActivationCause.RUNTIME_STATE_NOT_READ
    assert skill.harness_relevant is True
    assert skill.sets == (GovernanceSet.INVENTORIED,)


def test_a_command_form_skill_keeps_its_legacy_representation(tmp_path: Path) -> None:
    discovery = scan(tmp_path, {"commands/status.md": "# status\n"})

    (command,) = discovery.report.artifacts

    assert command.type is ArtifactType.SKILL
    assert command.representation is Representation.LEGACY_COMMAND


def test_only_declared_components_are_read_from_a_plugin_tree(tmp_path: Path) -> None:
    """A plugin cache holds far more than its components. Everything that is not a component
    location is excluded by rule rather than by pattern."""
    discovery = scan(
        tmp_path,
        {
            "skills/audit/SKILL.md": SKILL,
            "README.md": "# readme\n",
            "CHANGELOG.md": "# changelog\n",
            "CLAUDE.md": "# not project context\n",
            "docs/guide.md": "# guide\n",
            "scripts/deploy.sh": "#!/bin/sh\n",
            "node_modules/left-pad/index.md": "# vendored\n",
            "src/agents/impostor.md": "# not an agent\n",
        },
    )

    assert locators(discovery) == ["skills/audit/SKILL.md"]
    assert discovery.report.observations == ()


def test_declaring_commands_replaces_the_default_directory(tmp_path: Path) -> None:
    discovery = scan(
        tmp_path,
        {
            MANIFEST: manifest(name="p", commands=["./custom/commands/"]),
            "custom/commands/special.md": "# special\n",
            "commands/status.md": "# status\n",
        },
    )

    assert locators(discovery, ArtifactType.SKILL) == ["custom/commands/special.md"]


def test_declaring_agents_replaces_the_default_directory(tmp_path: Path) -> None:
    discovery = scan(
        tmp_path,
        {
            MANIFEST: manifest(name="p", agents=["./custom/agents/reviewer.md"]),
            "custom/agents/reviewer.md": "# reviewer\n",
            "agents/ignored.md": "# ignored\n",
        },
    )

    assert locators(discovery, ArtifactType.AGENT) == ["custom/agents/reviewer.md"]


def test_a_declared_component_path_may_name_one_file(tmp_path: Path) -> None:
    discovery = scan(
        tmp_path,
        {
            MANIFEST: manifest(name="p", commands="./custom/special.md"),
            "custom/special.md": "# special\n",
            "custom/sibling.md": "# not declared\n",
        },
    )

    assert locators(discovery, ArtifactType.SKILL) == ["custom/special.md"]


def test_a_declared_path_naming_a_file_that_is_not_markdown_holds_no_component(
    tmp_path: Path,
) -> None:
    """A command-form skill and a subagent are Markdown files, so a declared path naming
    anything else names no component of that type."""
    discovery = scan(
        tmp_path,
        {
            MANIFEST: manifest(name="p", commands=["./custom/special.md", "./custom/notes.txt"]),
            "custom/special.md": "# special\n",
            "custom/notes.txt": "notes\n",
        },
    )

    assert locators(discovery, ArtifactType.SKILL) == ["custom/special.md"]


def test_declaring_skills_adds_to_the_default_directory(tmp_path: Path) -> None:
    discovery = scan(
        tmp_path,
        {
            MANIFEST: manifest(name="p", skills=["./extra-skills/"]),
            "skills/audit/SKILL.md": SKILL,
            "extra-skills/route/SKILL.md": SKILL,
        },
    )

    assert locators(discovery, ArtifactType.SKILL) == [
        "extra-skills/route/SKILL.md",
        "skills/audit/SKILL.md",
    ]


def test_a_skills_path_holding_a_skill_file_is_itself_one_skill(tmp_path: Path) -> None:
    """A skills path is either one skill or a directory of them, decided by whether it holds a
    `SKILL.md` of its own."""
    discovery = scan(
        tmp_path,
        {
            MANIFEST: manifest(name="p", skills=["./skills/code-review"]),
            "skills/code-review/SKILL.md": SKILL,
            "skills/code-review/reference/SKILL.md": "# supporting material\n",
        },
    )

    assert locators(discovery, ArtifactType.SKILL) == ["skills/code-review/SKILL.md"]


def test_a_skill_file_at_the_plugin_root_is_a_single_skill_plugin(tmp_path: Path) -> None:
    discovery = scan(tmp_path, {"SKILL.md": SKILL})

    assert locators(discovery, ArtifactType.SKILL) == ["SKILL.md"]


@pytest.mark.parametrize(
    ("files", "reason"),
    [
        ({"skills/audit/SKILL.md": SKILL}, "a skills directory"),
        ({MANIFEST: manifest(name="p", skills=["./extra/"]), "extra/a/SKILL.md": SKILL}, "a key"),
    ],
)
def test_the_root_skill_file_is_not_a_skill_once_skills_are_declared(
    tmp_path: Path, files: Mapping[str, str], reason: str
) -> None:
    discovery = scan(tmp_path, {**files, "SKILL.md": SKILL})

    assert "SKILL.md" not in locators(discovery, ArtifactType.SKILL), reason


def test_a_manifest_key_hiding_an_existing_default_directory_is_reported(
    tmp_path: Path,
) -> None:
    discovery = scan(
        tmp_path,
        {
            MANIFEST: manifest(name="p", commands=["./custom/"]),
            "custom/special.md": "# special\n",
            "commands/status.md": "# status\n",
        },
    )

    assert codes(discovery) == [SHADOWED]
    finding = discovery.diagnostics[0]
    assert finding.subject.kind is SubjectKind.SURFACE
    assert finding.subject.locator == PLUGIN_ROOT
    assert finding.affected == ("commands",)
    assert MANIFEST in finding.message


def test_a_manifest_key_hides_nothing_when_the_default_directory_is_absent(
    tmp_path: Path,
) -> None:
    discovery = scan(
        tmp_path,
        {MANIFEST: manifest(name="p", commands=["./custom/"]), "custom/special.md": "# s\n"},
    )

    assert codes(discovery) == []


def test_listing_the_default_directory_explicitly_hides_nothing(tmp_path: Path) -> None:
    discovery = scan(
        tmp_path,
        {
            MANIFEST: manifest(name="p", commands=["./commands/", "./extras/"]),
            "commands/status.md": "# status\n",
            "extras/more.md": "# more\n",
        },
    )

    assert codes(discovery) == []
    assert locators(discovery, ArtifactType.SKILL) == ["commands/status.md", "extras/more.md"]


def test_a_skills_key_hides_nothing_because_it_adds(tmp_path: Path) -> None:
    discovery = scan(
        tmp_path,
        {
            MANIFEST: manifest(name="p", skills=["./extra-skills/"]),
            "skills/audit/SKILL.md": SKILL,
            "extra-skills/route/SKILL.md": SKILL,
        },
    )

    assert codes(discovery) == []


@pytest.mark.parametrize("key", ["hooks", "mcpServers", "lspServers"])
def test_a_key_whose_merge_rule_is_undocumented_hides_nothing(tmp_path: Path, key: str) -> None:
    """The runtime documents that these three combine by their own rules and does not say what
    those rules are, so discovery keeps both locations and claims neither hides the other."""
    discovery = scan(
        tmp_path,
        {
            MANIFEST: manifest(name="p", **{key: "./config/custom.json"}),
            "config/custom.json": "{}\n",
            "hooks/hooks.json": "{}\n",
            ".mcp.json": "{}\n",
            ".lsp.json": "{}\n",
        },
    )

    assert SHADOWED not in codes(discovery)


@pytest.mark.parametrize("declared", ["", ".", "commands", "custom/commands"])
def test_a_manifest_path_that_is_not_dot_slash_relative_locates_nothing(
    tmp_path: Path, declared: str
) -> None:
    """The runtime requires a manifest path to start with `./`. One that does not is dropped
    rather than read as a path: `""` normalises to the plugin root, and reading it would turn
    a component into a scan of the whole plugin."""
    discovery = scan(
        tmp_path,
        {
            MANIFEST: manifest(name="p", commands=[declared]),
            "README.md": "# readme\n",
            "docs/guide.md": "# guide\n",
            "custom/commands/special.md": "# special\n",
        },
    )

    assert locators(discovery, ArtifactType.SKILL) == []


@pytest.mark.parametrize("declared", [".", "./"])
def test_the_skills_field_accepts_the_plugin_root_in_both_spellings(
    tmp_path: Path, declared: str
) -> None:
    discovery = scan(tmp_path, {MANIFEST: manifest(name="p", skills=[declared]), "SKILL.md": SKILL})

    assert locators(discovery, ArtifactType.SKILL) == ["SKILL.md"]


def test_only_the_skills_field_accepts_the_bare_plugin_root(tmp_path: Path) -> None:
    discovery = scan(
        tmp_path, {MANIFEST: manifest(name="p", agents=["."]), "reviewer.md": "# reviewer\n"}
    )

    assert locators(discovery, ArtifactType.AGENT) == []


@pytest.mark.parametrize("declared", ["../shared-utils", "./nested/../../escape", "/etc"])
def test_a_component_path_escaping_the_plugin_root_is_reported_not_raised(
    tmp_path: Path, declared: str
) -> None:
    """The runtime rejects such a path and loads the plugin without that component, so this is
    a report about a component, never an error the scan fails with."""
    write_tree(tmp_path / "shared-utils", {"reviewer.md": "# outside\n"})

    discovery = scan(
        tmp_path,
        {MANIFEST: manifest(name="p", agents=[declared]), "agents/kept.md": "# kept\n"},
    )

    assert ESCAPES in codes(discovery)
    finding = next(entry for entry in discovery.diagnostics if entry.code == ESCAPES)
    assert finding.subject.kind is SubjectKind.SURFACE
    assert finding.subject.locator == PLUGIN_ROOT
    assert declared in finding.message
    assert locators(discovery, ArtifactType.AGENT) == []


def test_an_escaping_path_leaves_the_declared_paths_beside_it_scanned(tmp_path: Path) -> None:
    discovery = scan(
        tmp_path,
        {
            MANIFEST: manifest(name="p", agents=["../outside/", "./custom/"]),
            "custom/reviewer.md": "# reviewer\n",
        },
    )

    assert locators(discovery, ArtifactType.AGENT) == ["custom/reviewer.md"]
    assert codes(discovery) == [ESCAPES]


OBSERVED_COMPONENTS = {
    "workflows": "workflows/release-audit.js",
    "outputStyles": "output-styles/terse.md",
    "themes": "themes/dracula.json",
    "monitors": "monitors/monitors.json",
    "mcpServers": ".mcp.json",
    "lspServers": ".lsp.json",
    "executables": "bin/my-tool",
    "manifest": MANIFEST,
}

OBSERVED_LOCATIONS = {
    "workflows": "workflows",
    "outputStyles": "output-styles",
    "themes": "themes",
    "monitors": "monitors/monitors.json",
    "mcpServers": ".mcp.json",
    "lspServers": ".lsp.json",
    "executables": "bin",
    "manifest": MANIFEST,
}


def test_every_runtime_component_with_no_artifact_type_is_observed(tmp_path: Path) -> None:
    discovery = scan(
        tmp_path,
        {path: "x\n" for path in OBSERVED_COMPONENTS.values()} | {MANIFEST: manifest(name="p")},
    )

    assert observed(discovery) == sorted(OBSERVED_LOCATIONS.items())
    assert locators(discovery) == []


MANAGED = CapabilityValue.MANAGED
PLUGIN_SURFACE = CapabilityPolicy(MANAGED, MANAGED, MANAGED, MANAGED)


def test_an_observed_component_carries_the_policy_of_the_surface_it_sits_on(
    tmp_path: Path,
) -> None:
    """Capability Policy is keyed by Surface alone. Having no Artifact Type decides which
    operations apply to a component, not what the adapter may do with its Surface."""
    discovery = scan(tmp_path, {".mcp.json": "{}\n"})

    (observation,) = discovery.report.observations

    assert observation.scope is Scope.PLUGIN
    assert observation.capabilities == PLUGIN_SURFACE


def test_the_kind_of_component_never_changes_the_policy_within_one_surface(
    tmp_path: Path,
) -> None:
    discovery = scan(
        tmp_path,
        {path: "x\n" for path in OBSERVED_COMPONENTS.values()} | {MANIFEST: manifest(name="p")},
    )

    assert len(discovery.report.observations) == len(OBSERVED_LOCATIONS)
    assert {entry.scope for entry in discovery.report.observations} == {Scope.PLUGIN}
    assert {entry.capabilities for entry in discovery.report.observations} == {PLUGIN_SURFACE}


def test_a_component_location_that_does_not_exist_is_not_observed(tmp_path: Path) -> None:
    discovery = scan(tmp_path, {MANIFEST: manifest(name="p", workflows=["./flows/"])})

    assert components(discovery) == ["manifest"]


def test_a_declared_component_location_is_observed_where_the_manifest_puts_it(
    tmp_path: Path,
) -> None:
    discovery = scan(
        tmp_path,
        {
            MANIFEST: manifest(name="p", workflows=["./flows/"], mcpServers="./config/mcp.json"),
            "flows/release.js": "// release\n",
            "config/mcp.json": "{}\n",
        },
    )

    assert observed(discovery) == [
        ("manifest", MANIFEST),
        ("mcpServers", "config/mcp.json"),
        ("workflows", "flows"),
    ]


@pytest.mark.parametrize(
    ("declared", "expected"),
    [
        ({"experimental": {"themes": "./palettes/"}}, "palettes"),
        ({"themes": "./palettes/"}, "palettes"),
    ],
)
def test_an_experimental_component_is_read_under_either_accepted_key(
    tmp_path: Path, declared: Mapping[str, object], expected: str
) -> None:
    """The runtime documents that the top-level key still works while `experimental.*` becomes
    required, so a plugin written either way resolves the same."""
    discovery = scan(
        tmp_path, {MANIFEST: manifest(name="p", **declared), f"{expected}/dracula.json": "{}\n"}
    )

    assert ("themes", expected) in observed(discovery)


@pytest.mark.parametrize("key", ["workflows", "outputStyles", "themes"])
@pytest.mark.parametrize("value", [{"docs": "x"}, [{"name": "x"}]], ids=["object", "array"])
def test_a_field_that_takes_only_paths_declares_nothing_when_given_objects(
    tmp_path: Path, key: str, value: object
) -> None:
    """Only `hooks`, `mcpServers`, `lspServers` and `monitors` accept an inline declaration.
    Reading one on a field that takes a path would locate a component where the runtime never
    loads it."""
    discovery = scan(tmp_path, {MANIFEST: manifest(name="p", **{key: value})})

    assert components(discovery) == ["manifest"]
    assert locators(discovery) == []


MONITOR = {"name": "deploy-status", "command": "./poll.sh", "description": "Deployment status"}


@pytest.mark.parametrize(
    "declared",
    [{"experimental": {"monitors": [MONITOR]}}, {"monitors": [MONITOR]}],
    ids=["experimental", "legacy-top-level"],
)
def test_an_inline_monitor_array_is_located_at_the_manifest(
    tmp_path: Path, declared: Mapping[str, object]
) -> None:
    """`monitors` takes the monitors array itself, not only a path to a file holding one."""
    discovery = scan(tmp_path, {MANIFEST: manifest(name="p", **declared)})

    assert ("monitors", MANIFEST) in observed(discovery)


def test_a_monitors_path_locates_the_file_it_names(tmp_path: Path) -> None:
    discovery = scan(
        tmp_path,
        {
            MANIFEST: manifest(name="p", experimental={"monitors": "./config/monitors.json"}),
            "config/monitors.json": "[]\n",
        },
    )

    assert ("monitors", "config/monitors.json") in observed(discovery)
    assert ("monitors", MANIFEST) not in observed(discovery)


@pytest.mark.parametrize(
    "declared",
    [["./config/monitors.json"], ["./config/monitors.json", MONITOR]],
    ids=["paths", "mixed"],
)
def test_a_monitors_list_is_the_monitors_array_and_never_a_list_of_paths(
    tmp_path: Path, declared: list[object]
) -> None:
    """`monitors` is a path string or the monitors array itself. The validator refuses a list of
    paths and a list mixing paths with entries, so neither declares a location."""
    discovery = scan(
        tmp_path,
        {
            MANIFEST: manifest(name="p", experimental={"monitors": declared}),
            "config/monitors.json": "[]\n",
        },
    )

    assert components(discovery) == ["manifest"]


@pytest.mark.parametrize("key", ["themes", "monitors"])
def test_the_experimental_key_makes_the_top_level_one_dead_rather_than_additional(
    tmp_path: Path, key: str
) -> None:
    """The loader coalesces the two, `experimental?.<key> ?? <key>`, so a manifest carrying both
    loads the experimental one alone."""
    discovery = scan(
        tmp_path,
        {
            MANIFEST: manifest(name="p", experimental={key: "./new/"}, **{key: "./old/"}),
            "new/entry.json": "{}\n",
            "old/entry.json": "{}\n",
        },
    )

    assert (key, "new") in observed(discovery)
    assert (key, "old") not in observed(discovery)


def test_a_repeat_in_the_key_that_lost_decides_nothing(tmp_path: Path) -> None:
    """A repeat only matters where it decides. The experimental key wins outright, so a repeated
    top-level one is dead text rather than an ambiguity."""
    repeated = (
        '{"name": "p", "themes": "./old/", "themes": "./older/", '
        '"experimental": {"themes": "./new/"}}\n'
    )

    discovery = scan(tmp_path, {MANIFEST: repeated, "new/dracula.json": "{}\n"})

    assert codes(discovery) == []
    assert ("themes", "new") in observed(discovery)


def test_a_command_definition_map_locates_the_markdown_each_definition_names(
    tmp_path: Path,
) -> None:
    """`commands` also takes an object mapping command names to definitions, and a definition's
    `source` names the Markdown file the command is written in."""
    discovery = scan(
        tmp_path,
        {
            MANIFEST: manifest(
                name="p",
                commands={
                    "about": {"source": "./custom/about.md"},
                    "inline": {"content": "Explain this plugin"},
                },
            ),
            "custom/about.md": "# about\n",
        },
    )

    assert locators(discovery, ArtifactType.SKILL) == ["custom/about.md"]
    assert codes(discovery) == []


def test_a_remote_bundle_is_located_where_it_is_declared(tmp_path: Path) -> None:
    """`mcpServers` also takes a URL naming a remote MCPB bundle. The bundle is not in the
    plugin, so the only Locator it has is the manifest that declares it."""
    discovery = scan(
        tmp_path,
        {MANIFEST: manifest(name="p", mcpServers="https://example.com/server.mcpb")},
    )

    assert observed(discovery) == [("manifest", MANIFEST), ("mcpServers", MANIFEST)]


def test_an_inline_component_declaration_is_observed_at_the_manifest(tmp_path: Path) -> None:
    """A component declared inline has no path of its own; it is held in the manifest."""
    discovery = scan(
        tmp_path,
        {MANIFEST: manifest(name="p", mcpServers={"docs": {"command": "serve"}})},
    )

    assert observed(discovery) == [("manifest", MANIFEST), ("mcpServers", MANIFEST)]


@pytest.mark.parametrize(
    "content",
    ["not json at all\n", "[]\n", '{"name": "p"\n'],
)
def test_a_manifest_that_cannot_be_read_as_an_object_declares_no_overrides(
    tmp_path: Path, content: str
) -> None:
    """Whether a manifest is valid is the official validator's question, and harness-smith does
    not answer it a second time. A manifest that says nothing readable overrides nothing."""
    discovery = scan(tmp_path, {MANIFEST: content, "agents/reviewer.md": "# reviewer\n"})

    assert locators(discovery, ArtifactType.AGENT) == ["agents/reviewer.md"]
    assert codes(discovery) == []


def test_a_repeated_component_key_refuses_to_decide_where_that_component_lives(
    tmp_path: Path,
) -> None:
    """Which of two same-named members the runtime keeps is not recorded anywhere this project
    has verified, so a repeat that decides what is discovered is reported rather than resolved
    by picking one."""
    repeated = '{"name": "p", "agents": ["./one/"], "agents": ["./two/"]}\n'

    discovery = scan(
        tmp_path,
        {
            MANIFEST: repeated,
            "one/reviewer.md": "# one\n",
            "two/reviewer.md": "# two\n",
            "agents/default.md": "# default\n",
        },
    )

    assert codes(discovery) == [AMBIGUOUS]
    assert discovery.diagnostics[0].subject.locator == PLUGIN_ROOT
    assert "agents" in discovery.diagnostics[0].message
    assert locators(discovery, ArtifactType.AGENT) == []


def test_a_repeated_skills_key_still_leaves_the_default_directory_scanned(
    tmp_path: Path,
) -> None:
    """The default `skills/` directory is scanned whatever the key says, so an unresolvable
    key costs the additions it declared and nothing else."""
    repeated = '{"name": "p", "skills": ["./one/"], "skills": ["./two/"]}\n'

    discovery = scan(
        tmp_path,
        {MANIFEST: repeated, "skills/audit/SKILL.md": SKILL, "one/route/SKILL.md": SKILL},
    )

    assert codes(discovery) == [AMBIGUOUS]
    assert locators(discovery, ArtifactType.SKILL) == ["skills/audit/SKILL.md"]


def test_a_repeat_outside_the_component_keys_decides_nothing_here(tmp_path: Path) -> None:
    repeated = '{"name": "p", "keywords": ["a"], "keywords": ["b"]}\n'

    discovery = scan(tmp_path, {MANIFEST: repeated, "agents/reviewer.md": "# reviewer\n"})

    assert codes(discovery) == []
    assert locators(discovery, ArtifactType.AGENT) == ["agents/reviewer.md"]


ADDING = [
    ("hooks", "hooks/hooks.json", "config/extra-hooks.json", {"PreToolUse": []}),
    ("mcpServers", ".mcp.json", "config/mcp.json", {"docs": {"command": "serve"}}),
    ("lspServers", ".lsp.json", "config/lsp.json", {"go": {"command": "gopls"}}),
]


@pytest.mark.parametrize(("key", "default", "custom", "inline"), ADDING)
def test_a_declared_path_is_added_to_the_default_the_runtime_always_loads(
    tmp_path: Path, key: str, default: str, custom: str, inline: Mapping[str, object]
) -> None:
    """Claude Code 2.1.259 describes each of these fields as declaring components *in addition
    to* the ones at its default location, so both locations are where the component lives."""
    root = write_tree(
        tmp_path / "plugin",
        {MANIFEST: manifest(name="p", **{key: f"./{custom}"}), default: "{}\n", custom: "{}\n"},
    )

    assert resolve(root).locations[Component(key)] == (default, custom)


@pytest.mark.parametrize(("key", "default", "custom", "inline"), ADDING)
def test_an_inline_declaration_is_added_to_the_default_too(
    tmp_path: Path, key: str, default: str, custom: str, inline: Mapping[str, object]
) -> None:
    root = write_tree(
        tmp_path / "plugin", {MANIFEST: manifest(name="p", **{key: inline}), default: "{}\n"}
    )

    assert resolve(root).locations[Component(key)] == (default, MANIFEST)


def test_the_manifest_shapes_published_plugins_use(tmp_path: Path) -> None:
    """One fixture in the shapes real plugins are written in: a bare `skills` string, a
    `commands` list that keeps the default beside another directory, an individual skill
    directory named directly, and a hooks path declared next to the default."""
    discovery = scan(
        tmp_path,
        {
            MANIFEST: manifest(
                name="p",
                skills=["./skills/engineering/tdd", "./.claude/skills/"],
                commands=["./.claude/commands", "./commands"],
                hooks="./hooks/extra-hooks.json",
            ),
            "skills/engineering/tdd/SKILL.md": SKILL,
            ".claude/skills/brand/SKILL.md": SKILL,
            ".claude/commands/plan.md": "# plan\n",
            "commands/ship.md": "# ship\n",
            "hooks/extra-hooks.json": "{}\n",
            "hooks/hooks.json": "{}\n",
        },
    )

    assert locators(discovery, ArtifactType.SKILL) == [
        ".claude/commands/plan.md",
        ".claude/skills/brand/SKILL.md",
        "commands/ship.md",
        "skills/engineering/tdd/SKILL.md",
    ]
    assert codes(discovery) == []


def test_hook_locations_resolve_for_the_scan_that_reads_them(tmp_path: Path) -> None:
    """Discovering the hooks a plugin declares is a separate scan; resolving where they live is
    this one's job."""
    root = write_tree(
        tmp_path / "plugin",
        {MANIFEST: manifest(name="p", hooks="./config/hooks.json"), "config/hooks.json": "{}\n"},
    )

    resolution = resolve(root)

    assert resolution.locations[Component.HOOKS] == ("hooks/hooks.json", "config/hooks.json")
