"""surface-audit over fixture repository trees, observed at the command line.

The observation is the exit code and the canonical JSON document, which is what automation
consumes. Every document a run emits is validated against the result schema.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from tests.support import CliRun, make_repository, run_cli, write_tree

POPULATED: Mapping[str, str] = {
    "CLAUDE.md": "# entry point\n",
    ".claude/rules/style.md": "# style\n",
    ".claude/rules/python/typing.md": '---\npaths:\n  - "**/*.py"\n---\n\n# typing\n',
    ".claude/skills/audit/SKILL.md": "---\nname: audit\n---\n\n# audit\n",
    ".claude/commands/report.md": "Write the report.\n",
    ".claude/agents/reviewer.md": "---\nname: reviewer\n---\n\n# reviewer\n",
    ".claude/settings.json": (
        "{\n"
        '  "hooks": {\n'
        '    "PostToolUse": [\n'
        '      {"matcher": "Edit|Write", "hooks": [{"type": "command", "command": "fmt.sh"}]}\n'
        "    ]\n"
        "  },\n"
        '  "permissions": {"allow": ["Bash(ls:*)"]}\n'
        "}\n"
    ),
    "README.md": "# not part of the harness\n",
}


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    return make_repository(tmp_path / "repository")


def audit(repository: Path, files: Mapping[str, str]) -> CliRun:
    write_tree(repository, files)
    return run_cli("surface-audit", "--format", "json", cwd=repository)


def artifacts(run: CliRun) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = run.document["data"]["artifacts"]
    return entries


def test_a_populated_repository_reports_every_runtime_native_artifact(
    repository: Path,
) -> None:
    run = audit(repository, POPULATED)

    assert run.exit_code == 0
    assert [(entry["locator"], entry["type"]) for entry in artifacts(run)] == [
        (".claude/agents/reviewer.md", "agent"),
        (".claude/commands/report.md", "skill"),
        (".claude/rules/python/typing.md", "rule"),
        (".claude/rules/style.md", "rule"),
        (".claude/settings.json#/hooks/PostToolUse/0", "hook"),
        (".claude/skills/audit/SKILL.md", "skill"),
        ("CLAUDE.md", "entry-point"),
    ]


def test_every_reported_artifact_carries_its_locator_type_and_scope(repository: Path) -> None:
    run = audit(repository, POPULATED)

    for entry in artifacts(run):
        assert entry["locator"]
        assert entry["type"]
        assert entry["scope"] == "repository"


def test_a_repository_artifact_holds_an_authority_value_rather_than_none(
    repository: Path,
) -> None:
    """A repository artifact is inside the scope where authority applies, so an unresolved one
    is reported as `unknown` and refuses mutation."""
    run = audit(repository, POPULATED)

    for entry in artifacts(run):
        assert entry["managementAuthority"] == "unknown"
        assert entry["sets"] == ["inventoried"]


def test_a_rule_whose_bytes_are_not_text_is_not_reported_as_broken_yaml(
    repository: Path,
) -> None:
    write_tree(repository, {".claude/rules/keep.md": "# keep\n"})
    (repository / ".claude" / "rules" / "broken.md").write_bytes(b"---\nname: \xff\xfe\n---\n")

    run = run_cli("surface-audit", "--format", "json", cwd=repository)

    assert run.exit_code == 1
    assert run.diagnostic_codes == ["HS-RULE-FILE-UNREADABLE"]
    finding = run.document["diagnostics"][0]
    assert finding["remediation"] == "Make the rule readable UTF-8 text, then rerun"
    assert "UTF-8" in finding["message"]


def test_the_settings_file_is_a_container_holding_the_hooks_it_declares(
    repository: Path,
) -> None:
    """The file holds a hook and unrelated configuration. It is a container either way, and
    the configuration next to the hook produces nothing."""
    run = audit(repository, POPULATED)

    assert run.document["data"]["containers"] == [
        {
            "locator": ".claude/settings.json",
            "format": "json",
            "source": "shared-project-settings",
            "scope": "repository",
            "settingsLayer": "shared-project",
            "holds": [".claude/settings.json#/hooks/PostToolUse/0"],
        }
    ]


def test_a_command_form_skill_carries_its_legacy_representation(repository: Path) -> None:
    run = audit(repository, POPULATED)

    representations = {entry["locator"]: entry["representation"] for entry in artifacts(run)}

    assert representations[".claude/commands/report.md"] == "legacy-command"
    assert representations[".claude/skills/audit/SKILL.md"] == "directory"
    assert representations["CLAUDE.md"] == "file"
    assert representations[".claude/settings.json#/hooks/PostToolUse/0"] == "container-entry"


def test_two_project_entry_points_is_a_violation_that_still_reports_the_inventory(
    repository: Path,
) -> None:
    run = audit(repository, {"CLAUDE.md": "# one\n", ".claude/CLAUDE.md": "# two\n"})

    assert run.exit_code == 1
    assert run.document["status"] == "violations"
    assert run.diagnostic_codes == ["HS-ENTRYPOINT-DUPLICATE"]
    assert len(artifacts(run)) == 2


def test_unparseable_rule_frontmatter_is_a_violation(repository: Path) -> None:
    run = audit(repository, {".claude/rules/broken.md": "---\npaths: [1, 2\n---\n"})

    assert run.exit_code == 1
    assert run.diagnostic_codes == ["HS-RULE-FRONTMATTER-INVALID"]
    assert run.document["diagnostics"][0]["remediation"] == "Fix the YAML"


def test_a_shadowed_command_is_a_warning_that_does_not_fail_the_run(repository: Path) -> None:
    run = audit(
        repository,
        {".claude/skills/audit/SKILL.md": "# audit\n", ".claude/commands/audit.md": "audit\n"},
    )

    assert run.exit_code == 0
    assert run.document["status"] == "ok"
    assert run.diagnostic_codes == ["HS-SKILL-NAME-SHADOWED"]


def test_a_populated_repository_reads_the_same_way_twice(repository: Path) -> None:
    first = audit(repository, POPULATED)
    second = run_cli("surface-audit", "--format", "json", cwd=repository)

    assert first.stdout == second.stdout


def test_the_text_format_names_each_discovered_artifact(repository: Path) -> None:
    write_tree(repository, POPULATED)

    run = run_cli("surface-audit", cwd=repository)

    assert run.exit_code == 0
    assert "artifacts: 7" in run.stdout
    assert "entry-point" in run.stdout
    assert "CLAUDE.md" in run.stdout


def test_a_hook_declared_in_project_settings_is_reported_as_an_artifact(
    repository: Path,
) -> None:
    run = audit(repository, POPULATED)

    hooks = [entry for entry in artifacts(run) if entry["type"] == "hook"]

    assert [entry["locator"] for entry in hooks] == [".claude/settings.json#/hooks/PostToolUse/0"]
    assert hooks[0]["scope"] == "repository"
    assert hooks[0]["managementAuthority"] == "unknown"


def test_two_identical_declarations_are_reported_at_their_two_positions(
    repository: Path,
) -> None:
    """A Locator is a position, not an identity, so identical declarations are neither merged
    nor told apart by something invented for the purpose."""
    declaration = '{"matcher": "Bash", "hooks": [{"type": "command", "command": "audit.sh"}]}'
    twice = f'{{"hooks": {{"PreToolUse": [{declaration}, {declaration}]}}}}'

    run = audit(repository, {".claude/settings.json": twice})

    assert run.exit_code == 0
    assert [entry["locator"] for entry in artifacts(run)] == [
        ".claude/settings.json#/hooks/PreToolUse/0",
        ".claude/settings.json#/hooks/PreToolUse/1",
    ]


def test_a_settings_file_with_no_hooks_block_declares_none(repository: Path) -> None:
    run = audit(repository, {".claude/settings.json": '{"permissions": {"allow": []}}'})

    assert run.exit_code == 0
    assert artifacts(run) == []
    assert run.document["data"]["containers"] == [
        {
            "locator": ".claude/settings.json",
            "format": "json",
            "source": "shared-project-settings",
            "scope": "repository",
            "settingsLayer": "shared-project",
            "holds": [],
        }
    ]


def test_a_container_whose_json_does_not_parse_is_a_violation(repository: Path) -> None:
    run = audit(repository, {".claude/settings.json": '{"hooks": {"Stop": [{"matcher": ""}'})

    assert run.exit_code == 1
    assert run.diagnostic_codes == ["HS-HOOK-CONTAINER-UNPARSEABLE"]
    finding = run.document["diagnostics"][0]
    assert finding["subject"] == {"kind": "container", "locator": ".claude/settings.json"}
    assert finding["remediation"] == "Fix the JSON syntax"
    assert artifacts(run) == []


def test_a_container_that_cannot_be_read_as_text_is_its_own_finding(repository: Path) -> None:
    write_tree(repository, {"CLAUDE.md": "# entry\n"})
    (repository / ".claude").mkdir(exist_ok=True)
    (repository / ".claude" / "settings.json").write_bytes(b'{"model": "\xff\xfe"}')

    run = run_cli("surface-audit", "--format", "json", cwd=repository)

    assert run.exit_code == 1
    assert run.diagnostic_codes == ["HS-HOOK-CONTAINER-FILE-UNREADABLE"]
    assert run.document["diagnostics"][0]["remediation"] == (
        "Make the container readable UTF-8 text, then rerun"
    )


REFUSED_DECLARATIONS: Mapping[str, str] = {
    "a number outside the double range": '{"timeout": 1e999}',
    "an integer outside the double range": '{"timeout": 1' + "0" * 400 + "}",
    "a lone surrogate": '{"command": "' + chr(92) + 'ud800"}',
    "a repeated property name": '{"matcher": "a", "matcher": "b"}',
}


@pytest.mark.parametrize(("name", "declaration"), sorted(REFUSED_DECLARATIONS.items()))
def test_a_declaration_rfc_8785_refuses_ends_as_a_violation_not_a_crash(
    repository: Path, name: str, declaration: str
) -> None:
    """RFC 8785 Section 3.1 admits no duplicate property names, and no number outside the
    IEEE 754 double range. A declaration failing that has no Declaration Digest, so it closes
    as a container finding and exit 1 rather than escaping as an internal error and exit 3."""
    settings = '{"hooks": {"Stop": [' + declaration + "]}}"

    run = audit(repository, {".claude/settings.json": settings})

    assert run.exit_code == 1, name
    assert run.diagnostic_codes == ["HS-HOOK-CONTAINER-INVALID"], name
    assert run.stderr == "", name
    assert artifacts(run) == []
    assert run.document["data"]["containers"][0]["holds"] == []


def test_machine_local_settings_are_left_out_of_the_audit(repository: Path) -> None:
    run = audit(
        repository,
        {
            ".claude/settings.local.json": (
                '{"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x.sh"}]}]}}'
            )
        },
    )

    assert run.exit_code == 0
    assert artifacts(run) == []
    assert run.document["data"]["containers"] == []
