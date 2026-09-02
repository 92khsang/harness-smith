"""The operation contract, parameterised over every registered operation.

Written as prose this contract would go unchecked; parameterised over every operation
it is enforced. New operations join by adding a minimal invocation below, and the
completeness test fails until they do.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_smith.operations import DECLARED_OPERATIONS, REGISTRY
from harness_smith.vocabulary import EXIT_CODE_BY_STATUS
from tests.support import make_repository, run_cli, snapshot_tree, validate_document

MINIMAL_INVOCATION: dict[str, tuple[str, ...]] = {
    "surface-audit": ("surface-audit",),
}

OPERATION_NAMES = sorted(MINIMAL_INVOCATION)


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    return make_repository(tmp_path / "repository")


def test_every_registered_operation_is_covered_by_the_contract_harness() -> None:
    assert set(MINIMAL_INVOCATION) == set(REGISTRY)


def test_every_registered_operation_is_one_of_the_declared_operations() -> None:
    assert set(REGISTRY) <= set(DECLARED_OPERATIONS)


@pytest.mark.parametrize("name", OPERATION_NAMES)
def test_operation_emits_a_schema_valid_document(name: str, repository: Path) -> None:
    run = run_cli(*MINIMAL_INVOCATION[name], "--format", "json", cwd=repository)

    validate_document(run.document)
    assert run.document["operation"] == name


@pytest.mark.parametrize("name", OPERATION_NAMES)
def test_operation_returns_only_declared_exit_codes(name: str, repository: Path) -> None:
    run = run_cli(*MINIMAL_INVOCATION[name], "--format", "json", cwd=repository)

    assert run.exit_code in {0, 1, 2, 3}
    assert EXIT_CODE_BY_STATUS[run.document["status"]] == run.exit_code


@pytest.mark.parametrize("name", OPERATION_NAMES)
def test_operation_defaults_to_dry_run(name: str, repository: Path) -> None:
    run = run_cli(*MINIMAL_INVOCATION[name], "--format", "json", cwd=repository)

    expected_mode = "read" if REGISTRY[name].spec.kind == "read" else "plan"
    assert run.document["mode"] == expected_mode


@pytest.mark.parametrize("name", OPERATION_NAMES)
def test_operation_writes_nothing_without_the_apply_flag(name: str, repository: Path) -> None:
    before = snapshot_tree(repository)

    run_cli(*MINIMAL_INVOCATION[name], "--format", "json", cwd=repository)

    assert snapshot_tree(repository) == before


@pytest.mark.parametrize("name", OPERATION_NAMES)
def test_read_operation_emits_no_changes(name: str, repository: Path) -> None:
    if REGISTRY[name].spec.kind != "read":
        pytest.skip("only read operations promise an empty change set")

    run = run_cli(*MINIMAL_INVOCATION[name], "--format", "json", cwd=repository)

    assert run.document["changes"] == []


@pytest.mark.parametrize("name", OPERATION_NAMES)
def test_read_operation_is_deterministic(name: str, repository: Path) -> None:
    if REGISTRY[name].spec.kind != "read":
        pytest.skip("only read operations promise determinism across runs")

    first = run_cli(*MINIMAL_INVOCATION[name], "--format", "json", cwd=repository)
    second = run_cli(*MINIMAL_INVOCATION[name], "--format", "json", cwd=repository)

    assert first.stdout == second.stdout


@pytest.mark.parametrize("name", OPERATION_NAMES)
def test_operation_refuses_to_run_without_an_identifiable_repository_root(
    name: str, tmp_path: Path
) -> None:
    outside = tmp_path / "not-a-repository"
    outside.mkdir()

    run = run_cli(*MINIMAL_INVOCATION[name], "--format", "json", cwd=outside)

    assert run.exit_code == 2
    assert run.diagnostic_codes == ["HS-REPOSITORY-ROOT-NOT-FOUND"]
