"""The first-operation bootstrap: prepare once per plugin content, then get out of the way."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from harness_smith.cli import preferred_format
from harness_smith.diagnostics import DIAGNOSTIC_REGISTRY
from tests.support import BOOTSTRAP_PATH, LOADER_PATH, PLUGIN_ROOT, validate_document

# A stub ``uv`` that builds the environment the launcher asked for and records the plugin root
# it was pointed at, so a test can tell which version's code an environment holds.
STUB_UV = """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$UV_CALLS"
printf 'preparing the environment\\n'
# uv holds a process lock on the target environment; a stub that did not would rewrite an
# interpreter another launcher is executing.
lock="$UV_PROJECT_ENVIRONMENT.lock"
until mkdir "$lock" 2>/dev/null; do sleep 0.02; done
trap 'rmdir "$lock"' EXIT
project=""
previous=""
for argument in "$@"; do
  if [[ $previous == "--project" ]]; then project=$argument; fi
  previous=$argument
done
marker=$(sed -n 's/^VERSION = "\\(.*\\)"$/\\1/p' "$project/src/harness_smith/__init__.py")
mkdir -p "$UV_PROJECT_ENVIRONMENT/bin"
printf 'version_info = 3.13\\n' > "$UV_PROJECT_ENVIRONMENT/pyvenv.cfg"
: > "$UV_PROJECT_ENVIRONMENT/installed"
# Stands in for the loader contract: an environment that cannot import the tool exits 97
# before anything reaches stdout.
cat > "$UV_PROJECT_ENVIRONMENT/bin/python" <<INNER
#!/usr/bin/env bash
if [[ ! -f "$UV_PROJECT_ENVIRONMENT/installed" ]]; then
  printf 'cannot load the tool\\n' >&2
  exit 97
fi
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
        (root / "bin" / "loader.py").symlink_to(LOADER_PATH)
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
    assert run.stdout.startswith("stub-python[A] -I -X utf8 ")
    assert run.stdout.rstrip().endswith("bin/loader.py surface-audit --format json")
    assert plugin_data.ready_environments


def test_a_later_operation_is_a_no_op(plugin_data: PluginData) -> None:
    launcher = plugin_data.install("A")

    plugin_data.run(launcher, "surface-audit")
    second = plugin_data.run(launcher, "surface-audit")

    assert second.returncode == 0
    assert len(plugin_data.uv_invocations) == 1


def test_the_working_directory_is_kept_off_the_interpreter_path(
    plugin_data: PluginData,
) -> None:
    """The tool runs from inside the repository it audits, so that directory must not be able
    to supply a harness_smith package of its own."""
    launcher = plugin_data.install("A")

    run = plugin_data.run(launcher, "surface-audit")

    assert run.stdout.startswith("stub-python[A] -I -X utf8 ")


def test_the_environment_holds_its_own_copy_of_the_source(plugin_data: PluginData) -> None:
    """--no-editable, so the environment does not point back at a plugin root that an update
    is about to replace."""
    launcher = plugin_data.install("A")

    plugin_data.run(launcher, "surface-audit")

    assert "--no-editable" in plugin_data.uv_invocations[0]
    assert "--locked" in plugin_data.uv_invocations[0]


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

    assert run.stdout.startswith("stub-python[A] -I -X utf8 ")
    assert run.stdout.rstrip().endswith("bin/loader.py surface-audit --format json")
    assert "preparing the environment" in run.stderr


def test_a_plugin_root_with_nothing_to_fingerprint_is_reported_as_a_document(
    tmp_path: Path,
) -> None:
    """The fingerprint is computed before the environment is chosen, and its failures used to
    be raised inside a command substitution that captured the document instead of emitting
    it."""
    plugin_data = PluginData(tmp_path)
    launcher = plugin_data.install("A")
    for path in ("pyproject.toml", "uv.lock"):
        (launcher.parent.parent / path).unlink()
    for directory in ("src", "resources"):
        subprocess.run(["rm", "-rf", str(launcher.parent.parent / directory)], check=True)

    run = plugin_data.run(launcher, "surface-audit", "--format", "json")

    assert run.returncode == 3
    document = json.loads(run.stdout)
    validate_document(document)
    assert [entry["code"] for entry in document["diagnostics"]] == ["HS-BOOTSTRAP-FAILED"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads unreadable files")
def test_an_unreadable_source_file_is_reported_as_a_document(tmp_path: Path) -> None:
    """A failure inside the digest pipeline used to escape as the raw status of whichever
    stage failed, outside the declared exit vocabulary and with no document at all."""
    plugin_data = PluginData(tmp_path)
    launcher = plugin_data.install("A")
    (launcher.parent.parent / "src" / "harness_smith" / "cli.py").chmod(0o000)

    run = plugin_data.run(launcher, "surface-audit", "--format", "json")

    assert run.returncode == 3
    validate_document(json.loads(run.stdout))


def test_no_identifiable_data_directory_is_reported_as_a_document(tmp_path: Path) -> None:
    plugin_data = PluginData(tmp_path)
    launcher = plugin_data.install("A")

    run = subprocess.run(
        [str(launcher), "surface-audit", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": plugin_data.path},
    )

    assert run.returncode == 3
    validate_document(json.loads(run.stdout))


def test_a_failure_message_carries_no_path_into_the_document(tmp_path: Path) -> None:
    """Paths belong on stderr. In the document they would be both non-reproducible and, when
    they carry a control character, unparseable."""
    plugin_data = PluginData(tmp_path)
    launcher = plugin_data.install("A")
    unusable = tmp_path / "not	writable" / "data"

    run = subprocess.run(
        [str(launcher), "surface-audit", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": plugin_data.path, "HARNESS_SMITH_DATA_DIR": str(unusable)},
    )

    assert run.returncode == 3
    document = json.loads(run.stdout)
    validate_document(document)
    assert "\t" not in document["diagnostics"][0]["message"]
    assert str(unusable) not in run.stdout


def test_an_interrupted_preparation_leaves_no_readiness_claim(tmp_path: Path) -> None:
    """A marker that outlived a half-finished sync would assert an environment that cannot
    import the package, and nothing would ever prepare it again."""
    plugin_data = PluginData(tmp_path)
    launcher = plugin_data.install("A")
    plugin_data.run(launcher, "surface-audit")
    stub = Path(plugin_data.path.split(":")[0]) / "uv"
    stub.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    stub.chmod(0o755)
    for environment in (plugin_data.data_dir / "venvs").iterdir():
        if environment.is_dir():
            (environment / "bin" / "python").unlink()

    failed = plugin_data.run(launcher, "surface-audit", "--format", "json")

    assert failed.returncode == 3
    assert plugin_data.ready_environments == []


def test_concurrent_launchers_at_one_fingerprint_all_succeed(tmp_path: Path) -> None:
    """Every launcher that loses the race to write the marker is still looking at a prepared
    environment, and must not report a failure for work that succeeded."""
    plugin_data = PluginData(tmp_path)
    launcher = plugin_data.install("A")
    with ThreadPoolExecutor(max_workers=6) as pool:
        runs = list(pool.map(lambda _: plugin_data.run(launcher, "surface-audit"), range(6)))

    assert [run.returncode for run in runs] == [0] * 6
    assert [run.stderr for run in runs if run.returncode] == []
    assert list((plugin_data.data_dir / "venvs").glob("*.partial")) == []


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


# The launcher decides the format of a bootstrap failure before Python exists, so its scan and
# the parser's must agree on every argv, not only on the well-formed ones.
SCANNER_ARGUMENTS = [
    ("surface-audit",),
    ("surface-audit", "--format", "json"),
    ("surface-audit", "--format=json"),
    ("surface-audit", "--format", "json", "--format", "text"),
    ("surface-audit", "--format", "text", "--format", "json"),
    ("surface-audit", "--format=json", "--format=text"),
    ("surface-audit", "--format=text", "--format=json"),
    ("surface-audit", "--format", "--format=json"),
    ("surface-audit", "--format=text", "--format", "--format=json"),
    ("surface-audit", "--format", "json", "--format"),
    ("surface-audit", "--format", "nonsense"),
    ("surface-audit", "--format"),
]


@pytest.mark.parametrize("arguments", SCANNER_ARGUMENTS, ids=lambda a: " ".join(a[1:]) or "bare")
def test_the_launcher_resolves_the_format_exactly_as_the_parser_would(
    tmp_path: Path, arguments: tuple[str, ...]
) -> None:
    plugin_data = PluginData(tmp_path, with_uv=False)
    launcher = plugin_data.install("A")

    run = plugin_data.run(launcher, *arguments)

    assert run.returncode == 3
    emitted_a_document = bool(run.stdout.strip())
    assert emitted_a_document == (preferred_format(list(arguments)) == "json")
    if emitted_a_document:
        validate_document(json.loads(run.stdout))


def damage(plugin_data: PluginData) -> None:
    """Remove what makes the environment able to load the tool, leaving its readiness claim."""
    for environment in (plugin_data.data_dir / "venvs").iterdir():
        if environment.is_dir():
            (environment / "installed").unlink()


def test_a_damaged_environment_is_prepared_again_and_succeeds(plugin_data: PluginData) -> None:
    """The marker records that a sync finished, not that the environment still works."""
    launcher = plugin_data.install("A")
    plugin_data.run(launcher, "surface-audit")
    damage(plugin_data)

    run = plugin_data.run(launcher, "surface-audit", "--format", "json")

    assert run.returncode == 0
    assert run.stdout.startswith("stub-python[A] -I -X utf8 ")
    assert len(plugin_data.uv_invocations) == 2
    assert "--reinstall" in plugin_data.uv_invocations[1]


def test_a_damaged_environment_that_cannot_be_repaired_is_one_document(tmp_path: Path) -> None:
    plugin_data = PluginData(tmp_path)
    launcher = plugin_data.install("A")
    plugin_data.run(launcher, "surface-audit")
    damage(plugin_data)
    (Path(plugin_data.path.split(":")[0]) / "uv").unlink()

    run = plugin_data.run(launcher, "surface-audit", "--format", "json")

    assert run.returncode == 3
    document = json.loads(run.stdout)
    validate_document(document)
    assert [entry["code"] for entry in document["diagnostics"]] == ["HS-BOOTSTRAP-FAILED"]
    assert "Traceback" not in run.stderr


def test_a_damaged_environment_never_ends_in_a_bare_import_error(tmp_path: Path) -> None:
    """Before the loader existed this path exited 1 -- the code reserved for a policy
    violation -- with an empty stdout and ModuleNotFoundError on stderr."""
    plugin_data = PluginData(tmp_path)
    launcher = plugin_data.install("A")
    plugin_data.run(launcher, "surface-audit")
    damage(plugin_data)
    (Path(plugin_data.path.split(":")[0]) / "uv").unlink()

    run = plugin_data.run(launcher, "surface-audit", "--format", "json")

    assert run.returncode != 1
    assert run.stdout.strip() != ""
    assert "ModuleNotFoundError" not in run.stdout


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs the real uv to check the lock")
def test_a_lock_that_no_longer_describes_the_project_is_refused(tmp_path: Path) -> None:
    """--frozen installed the stale lock and marked the environment ready while a declared
    dependency was missing from it."""
    root = tmp_path / "plugin"
    shutil.copytree(
        PLUGIN_ROOT, root, ignore=shutil.ignore_patterns(".venv", "__pycache__", ".*_cache")
    )
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        re.sub(
            r"^dependencies = .*$",
            'dependencies = ["tomli-w>=1.0"]',
            pyproject.read_text(encoding="utf-8"),
            count=1,
            flags=re.MULTILINE,
        ),
        encoding="utf-8",
    )
    data_dir = tmp_path / "plugin-data"

    run = subprocess.run(
        [str(root / "bin" / "harness-smith"), "surface-audit", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "HARNESS_SMITH_DATA_DIR": str(data_dir)},
    )

    assert run.returncode == 3
    document = json.loads(run.stdout)
    validate_document(document)
    assert [entry["code"] for entry in document["diagnostics"]] == ["HS-BOOTSTRAP-FAILED"]
    assert list((data_dir / "venvs").glob("*.ready")) == []
