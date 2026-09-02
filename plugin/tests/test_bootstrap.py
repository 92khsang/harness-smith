"""The first-operation bootstrap: prepare once per plugin content, then get out of the way."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from harness_smith.diagnostics import DIAGNOSTIC_REGISTRY
from tests.support import BOOTSTRAP_PATH, validate_document

# A stub ``uv`` that builds the environment the launcher asked for and records the plugin root
# it was pointed at, so a test can tell which version's code an environment holds.
STUB_UV = """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$UV_CALLS"
printf 'preparing the environment\\n'
project=""
previous=""
for argument in "$@"; do
  if [[ $previous == "--project" ]]; then project=$argument; fi
  previous=$argument
done
marker=$(sed -n 's/^VERSION = "\\(.*\\)"$/\\1/p' "$project/src/harness_smith/__init__.py")
mkdir -p "$UV_PROJECT_ENVIRONMENT/bin"
printf 'version_info = 3.13\\n' > "$UV_PROJECT_ENVIRONMENT/pyvenv.cfg"
cat > "$UV_PROJECT_ENVIRONMENT/bin/python" <<INNER
#!/usr/bin/env bash
printf 'stub-python[$marker] %s\\n' "\\$*"
INNER
chmod +x "$UV_PROJECT_ENVIRONMENT/bin/python"
"""

PYPROJECT = """[project]
name = "harness-smith"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []
"""

LOCK = 'version = 1\nrequires-python = ">=3.12"\n'

CORE_TOOLS_PATH = "/usr/bin:/bin"


class PluginData:
    """One plugin data directory, shared across plugin versions the way CLAUDE_PLUGIN_DATA is.

    Each ``install`` lands a plugin root at its own path, which is what a plugin update does:
    ``CLAUDE_PLUGIN_ROOT`` moves, ``CLAUDE_PLUGIN_DATA`` does not.
    """

    def __init__(self, tmp_path: Path, *, with_uv: bool = True) -> None:
        self.root = tmp_path
        self.data_dir = tmp_path / "plugin-data"
        self.calls = tmp_path / "uv-calls"
        self.calls.touch()
        stub_dir = tmp_path / "stub-bin"
        stub_dir.mkdir()
        if with_uv:
            stub = stub_dir / "uv"
            stub.write_text(STUB_UV, encoding="utf-8")
            stub.chmod(0o755)
        self.path = f"{stub_dir}:{CORE_TOOLS_PATH}"

    def install(self, marker: str, *, lock: str = LOCK, source: str | None = None) -> Path:
        root = self.root / "cache" / marker
        (root / "bin").mkdir(parents=True)
        (root / "bin" / "harness-smith").symlink_to(BOOTSTRAP_PATH)
        (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
        (root / "uv.lock").write_text(lock, encoding="utf-8")
        package = root / "src" / "harness_smith"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text(f'VERSION = "{marker}"\n', encoding="utf-8")
        (package / "cli.py").write_text(source or "def main() -> int:\n    return 0\n", "utf-8")
        (root / "resources").mkdir()
        (root / "resources" / "note.txt").write_text("resource\n", encoding="utf-8")
        return root / "bin" / "harness-smith"

    def run(self, launcher: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(launcher), *arguments],
            capture_output=True,
            text=True,
            check=False,
            env={
                "PATH": self.path,
                "HOME": os.environ["HOME"],
                "HARNESS_SMITH_DATA_DIR": str(self.data_dir),
                "UV_CALLS": str(self.calls),
            },
        )

    @property
    def uv_invocations(self) -> list[str]:
        return self.calls.read_text(encoding="utf-8").splitlines()

    @property
    def ready_environments(self) -> list[str]:
        environments = self.data_dir / "venvs"
        if not environments.is_dir():
            return []
        return sorted(path.stem for path in environments.glob("*.ready"))


@pytest.fixture
def plugin_data(tmp_path: Path) -> PluginData:
    return PluginData(tmp_path)


def test_the_first_operation_prepares_the_environment_and_hands_over(
    plugin_data: PluginData,
) -> None:
    launcher = plugin_data.install("A")

    run = plugin_data.run(launcher, "surface-audit", "--format", "json")

    assert run.returncode == 0, run.stderr
    assert len(plugin_data.uv_invocations) == 1
    assert run.stdout == "stub-python[A] -m harness_smith surface-audit --format json\n"
    assert plugin_data.ready_environments


def test_a_later_operation_is_a_no_op(plugin_data: PluginData) -> None:
    launcher = plugin_data.install("A")

    plugin_data.run(launcher, "surface-audit")
    second = plugin_data.run(launcher, "surface-audit")

    assert second.returncode == 0
    assert len(plugin_data.uv_invocations) == 1


def test_the_environment_holds_its_own_copy_of_the_source(plugin_data: PluginData) -> None:
    """--no-editable, so the environment does not point back at a plugin root that an update
    is about to replace."""
    launcher = plugin_data.install("A")

    plugin_data.run(launcher, "surface-audit")

    assert "--no-editable" in plugin_data.uv_invocations[0]


def test_an_update_that_changes_only_source_runs_the_new_code(plugin_data: PluginData) -> None:
    """The dependency metadata is byte-identical across the two versions; only the code moved."""
    first = plugin_data.install("A")
    second = plugin_data.install("B")
    assert (first.parent.parent / "uv.lock").read_bytes() == (
        second.parent.parent / "uv.lock"
    ).read_bytes()

    plugin_data.run(first, "surface-audit")
    updated = plugin_data.run(second, "surface-audit")

    assert updated.stdout.startswith("stub-python[B]")
    assert len(plugin_data.uv_invocations) == 2


def test_the_previous_version_keeps_running_its_own_code_after_an_update(
    plugin_data: PluginData,
) -> None:
    first = plugin_data.install("A")
    second = plugin_data.install("B")
    plugin_data.run(first, "surface-audit")
    plugin_data.run(second, "surface-audit")

    still_the_old_one = plugin_data.run(first, "surface-audit")

    assert still_the_old_one.stdout.startswith("stub-python[A]")
    assert len(plugin_data.uv_invocations) == 2


def test_each_version_gets_its_own_environment(plugin_data: PluginData) -> None:
    plugin_data.run(plugin_data.install("A"), "surface-audit")
    plugin_data.run(plugin_data.install("B"), "surface-audit")

    assert len(plugin_data.ready_environments) == 2


def test_the_same_content_at_a_different_plugin_root_reuses_its_environment(
    plugin_data: PluginData,
) -> None:
    """An update that changes nothing the environment holds is not a reason to rebuild it."""
    shared = "def main() -> int:\n    return 0\n"
    first = plugin_data.install("same", source=shared)
    relocated = plugin_data.root / "cache" / "relocated"
    relocated.parent.mkdir(exist_ok=True)
    subprocess.run(["cp", "-r", str(first.parent.parent), str(relocated)], check=True)

    plugin_data.run(first, "surface-audit")
    plugin_data.run(relocated / "bin" / "harness-smith", "surface-audit")

    assert len(plugin_data.uv_invocations) == 1
    assert len(plugin_data.ready_environments) == 1


def test_an_environment_without_its_readiness_marker_is_prepared_again(
    plugin_data: PluginData,
) -> None:
    launcher = plugin_data.install("A")
    plugin_data.run(launcher, "surface-audit")
    for marker in (plugin_data.data_dir / "venvs").glob("*.ready"):
        marker.unlink()

    plugin_data.run(launcher, "surface-audit")

    assert len(plugin_data.uv_invocations) == 2


def test_preparation_progress_never_reaches_stdout(plugin_data: PluginData) -> None:
    launcher = plugin_data.install("A")

    run = plugin_data.run(launcher, "surface-audit", "--format", "json")

    assert run.stdout == "stub-python[A] -m harness_smith surface-audit --format json\n"
    assert "preparing the environment" in run.stderr


def test_a_missing_uv_is_an_environment_failure_reported_as_a_document(tmp_path: Path) -> None:
    plugin_data = PluginData(tmp_path, with_uv=False)
    launcher = plugin_data.install("A")

    run = plugin_data.run(launcher, "surface-audit", "--format", "json")

    assert run.returncode == 3
    document = json.loads(run.stdout)
    validate_document(document)
    assert document["operation"] is None
    assert document["status"] == "environment-error"
    assert document["data"] is None
    assert [entry["code"] for entry in document["diagnostics"]] == ["HS-BOOTSTRAP-FAILED"]
    assert "uv" in run.stderr


def test_the_bootstrap_document_repeats_the_registry_remediation_verbatim(tmp_path: Path) -> None:
    """The launcher writes its document before Python exists, so the one string it duplicates
    from the registry is held to it here."""
    plugin_data = PluginData(tmp_path, with_uv=False)
    launcher = plugin_data.install("A")

    run = plugin_data.run(launcher, "surface-audit", "--format", "json")

    diagnostic = json.loads(run.stdout)["diagnostics"][0]
    assert diagnostic["remediation"] == DIAGNOSTIC_REGISTRY["HS-BOOTSTRAP-FAILED"].remediation
    assert diagnostic["severity"] == DIAGNOSTIC_REGISTRY["HS-BOOTSTRAP-FAILED"].severity


@pytest.mark.parametrize(
    "arguments",
    [
        ("surface-audit",),
        ("surface-audit", "--format", "text"),
        ("surface-audit", "--format", "json", "--format", "text"),
        ("surface-audit", "--format=json", "--format", "text"),
        ("surface-audit", "--format=json", "--format=text"),
    ],
)
def test_a_failure_stays_off_stdout_when_the_last_format_is_not_json(
    tmp_path: Path, arguments: tuple[str, ...]
) -> None:
    plugin_data = PluginData(tmp_path, with_uv=False)
    launcher = plugin_data.install("A")

    run = plugin_data.run(launcher, *arguments)

    assert run.returncode == 3
    assert run.stdout == ""
    assert "harness-smith:" in run.stderr


@pytest.mark.parametrize(
    "arguments",
    [
        ("surface-audit", "--format", "json"),
        ("surface-audit", "--format=json"),
        ("surface-audit", "--format", "text", "--format", "json"),
        ("surface-audit", "--format", "text", "--format=json"),
        ("surface-audit", "--format=text", "--format=json"),
    ],
)
def test_a_failure_is_a_document_when_the_last_format_is_json(
    tmp_path: Path, arguments: tuple[str, ...]
) -> None:
    plugin_data = PluginData(tmp_path, with_uv=False)
    launcher = plugin_data.install("A")

    run = plugin_data.run(launcher, *arguments)

    assert run.returncode == 3
    document = json.loads(run.stdout)
    validate_document(document)
    assert document["status"] == "environment-error"
