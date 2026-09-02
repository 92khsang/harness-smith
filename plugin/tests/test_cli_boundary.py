"""Acceptance tests at the one public product seam: the command line and its JSON document."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.support import make_repository, run_cli, snapshot_tree, sole_json_document


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    return make_repository(tmp_path / "repository")


def test_surface_audit_on_an_empty_repository_emits_three_empty_inventories(
    repository: Path,
) -> None:
    run = run_cli("surface-audit", "--format", "json", cwd=repository)

    assert run.exit_code == 0
    assert run.document == {
        "schemaVersion": 1,
        "operation": "surface-audit",
        "mode": "read",
        "status": "ok",
        "diagnostics": [],
        "changes": [],
        "data": {"artifacts": [], "containers": [], "observations": []},
    }


def test_json_format_puts_exactly_one_document_on_stdout(repository: Path) -> None:
    run = run_cli("surface-audit", "--format", "json", cwd=repository)

    assert sole_json_document(run.stdout)["operation"] == "surface-audit"


def test_text_is_the_default_format_and_is_not_json(repository: Path) -> None:
    run = run_cli("surface-audit", cwd=repository)

    assert run.exit_code == 0
    with pytest.raises(json.JSONDecodeError):
        json.loads(run.stdout)
    assert "surface-audit" in run.stdout


def test_an_unknown_operation_fails_before_dispatch(repository: Path) -> None:
    run = run_cli("no-such-operation", "--format", "json", cwd=repository)

    assert run.exit_code == 2
    assert run.document["operation"] is None
    assert run.document["data"] is None
    assert run.document["mode"] == "read"
    assert run.document["status"] == "usage-error"
    assert run.document["changes"] == []
    assert run.diagnostic_codes == ["HS-CLI-USAGE"]
    assert run.document["diagnostics"][0]["subject"] == {"kind": "environment", "locator": None}


def test_an_unparseable_argument_fails_before_dispatch(repository: Path) -> None:
    run = run_cli("surface-audit", "--no-such-option", "--format", "json", cwd=repository)

    assert run.exit_code == 2
    assert run.document["operation"] is None
    assert run.diagnostic_codes == ["HS-CLI-USAGE"]


def test_an_unknown_operation_still_reports_json_when_the_format_uses_equals(
    repository: Path,
) -> None:
    run = run_cli("no-such-operation", "--format=json", cwd=repository)

    assert run.exit_code == 2
    assert run.diagnostic_codes == ["HS-CLI-USAGE"]


def test_a_usage_error_prints_text_when_no_json_format_is_requested(repository: Path) -> None:
    run = run_cli("no-such-operation", cwd=repository)

    assert run.exit_code == 2
    assert "HS-CLI-USAGE" in run.stdout
    with pytest.raises(json.JSONDecodeError):
        json.loads(run.stdout)


def test_no_identifiable_repository_root_is_a_precondition_error(tmp_path: Path) -> None:
    outside = tmp_path / "not-a-repository"
    outside.mkdir()

    run = run_cli("surface-audit", "--format", "json", cwd=outside)

    assert run.exit_code == 2
    assert run.document["operation"] == "surface-audit"
    assert run.document["data"] is None
    assert run.document["status"] == "usage-error"
    assert run.diagnostic_codes == ["HS-REPOSITORY-ROOT-NOT-FOUND"]


def test_the_repository_root_is_found_from_a_nested_working_directory(repository: Path) -> None:
    nested = repository / "a" / "b"
    nested.mkdir(parents=True)

    run = run_cli("surface-audit", "--format", "json", cwd=nested)

    assert run.exit_code == 0


def test_an_explicit_root_is_accepted_from_outside_the_repository(
    repository: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()

    run = run_cli("surface-audit", "--root", str(repository), "--format", "json", cwd=outside)

    assert run.exit_code == 0
    assert run.document["status"] == "ok"


def test_an_explicit_root_that_is_not_a_repository_is_refused(tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()

    run = run_cli("surface-audit", "--root", str(outside), "--format", "json", cwd=outside)

    assert run.exit_code == 2
    assert run.diagnostic_codes == ["HS-REPOSITORY-ROOT-NOT-FOUND"]


def test_a_refused_explicit_root_says_so_rather_than_blaming_the_working_directory(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()

    refused = run_cli("surface-audit", "--root", str(outside), "--format", "json", cwd=outside)
    undiscovered = run_cli("surface-audit", "--format", "json", cwd=outside)

    assert "--root" in refused.document["diagnostics"][0]["message"]
    assert "working directory" in undiscovered.document["diagnostics"][0]["message"]


def test_a_diagnostic_message_carries_no_absolute_path(tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()

    run = run_cli("surface-audit", "--root", str(outside), "--format", "json", cwd=outside)

    assert str(outside) not in run.stdout


def test_help_is_refused_as_a_format_combination_rather_than_written_to_stdout(
    repository: Path,
) -> None:
    run = run_cli("--format", "json", "--help", cwd=repository)

    assert run.exit_code == 2
    assert run.document["operation"] is None
    assert run.diagnostic_codes == ["HS-CLI-USAGE"]


def test_help_is_ordinary_prose_in_the_text_format(repository: Path) -> None:
    run = run_cli("--help", cwd=repository)

    assert run.exit_code == 0
    assert "surface-audit" in run.stdout


def test_the_last_format_wins_as_the_parser_would_have_decided(repository: Path) -> None:
    run = run_cli("surface-audit", "--format", "json", "--format", "text", cwd=repository)

    assert run.exit_code == 0
    with pytest.raises(json.JSONDecodeError):
        json.loads(run.stdout)


def test_two_runs_over_the_same_repository_are_byte_identical(repository: Path) -> None:
    first = run_cli("surface-audit", "--format", "json", cwd=repository)
    second = run_cli("surface-audit", "--format", "json", cwd=repository)

    assert first.stdout == second.stdout
    assert first.exit_code == second.exit_code


def test_a_read_operation_leaves_the_repository_untouched(repository: Path) -> None:
    before = snapshot_tree(repository)

    run_cli("surface-audit", "--format", "json", cwd=repository)

    assert snapshot_tree(repository) == before


def test_a_repository_holding_its_own_harness_smith_package_does_not_shadow_the_tool(
    repository: Path,
) -> None:
    """The tool runs from inside the repository it audits, so that directory must never be
    able to supply the package the tool is."""
    package = repository / "harness_smith"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "__main__.py").write_text('print("SHADOWED")\n', encoding="utf-8")

    run = run_cli("surface-audit", "--format", "json", cwd=repository)

    assert run.exit_code == 0
    assert "SHADOWED" not in run.stdout
    assert run.document["operation"] == "surface-audit"


def test_an_abbreviated_option_is_refused_rather_than_silently_accepted(
    repository: Path,
) -> None:
    """argparse would accept --forma=json while the pre-scan that picks the format of a
    pre-dispatch failure would not, so one invocation could answer in two formats."""
    run = run_cli("--forma=json", "surface-audit", cwd=repository)

    assert run.exit_code == 2
    assert "HS-CLI-USAGE" in run.stdout
