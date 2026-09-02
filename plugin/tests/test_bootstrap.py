"""The first-operation bootstrap: prepare once, then get out of the way."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.support import BOOTSTRAP_PATH, validate_document

STUB_UV = """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$UV_CALLS"
printf 'preparing the environment\\n'
mkdir -p "$UV_PROJECT_ENVIRONMENT/bin"
printf 'version_info = 3.13\\n' > "$UV_PROJECT_ENVIRONMENT/pyvenv.cfg"
cat > "$UV_PROJECT_ENVIRONMENT/bin/python" <<'INNER'
#!/usr/bin/env bash
printf 'stub-python %s\\n' "$*"
INNER
chmod +x "$UV_PROJECT_ENVIRONMENT/bin/python"
"""

CORE_TOOLS_PATH = "/usr/bin:/bin"


class Bootstrap:
    """Drives bin/harness-smith against a stub ``uv`` and an isolated data directory."""

    def __init__(self, tmp_path: Path, *, with_uv: bool = True) -> None:
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

    def run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(BOOTSTRAP_PATH), *arguments],
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


def test_the_first_operation_prepares_the_environment_and_hands_over(tmp_path: Path) -> None:
    bootstrap = Bootstrap(tmp_path)

    run = bootstrap.run("surface-audit", "--format", "json")

    assert run.returncode == 0, run.stderr
    assert len(bootstrap.uv_invocations) == 1
    assert "--frozen" in bootstrap.uv_invocations[0]
    assert "--no-dev" in bootstrap.uv_invocations[0]
    assert run.stdout == "stub-python -m harness_smith surface-audit --format json\n"
    assert (bootstrap.data_dir / "environment.fingerprint").is_file()


def test_a_later_operation_is_a_no_op(tmp_path: Path) -> None:
    bootstrap = Bootstrap(tmp_path)

    bootstrap.run("surface-audit")
    second = bootstrap.run("surface-audit")

    assert second.returncode == 0
    assert len(bootstrap.uv_invocations) == 1


def test_a_stale_fingerprint_prepares_the_environment_again(tmp_path: Path) -> None:
    bootstrap = Bootstrap(tmp_path)
    bootstrap.run("surface-audit")

    (bootstrap.data_dir / "environment.fingerprint").write_text("stale", encoding="utf-8")
    bootstrap.run("surface-audit")

    assert len(bootstrap.uv_invocations) == 2


def test_preparation_progress_never_reaches_stdout(tmp_path: Path) -> None:
    bootstrap = Bootstrap(tmp_path)

    run = bootstrap.run("surface-audit", "--format", "json")

    assert run.stdout == "stub-python -m harness_smith surface-audit --format json\n"
    assert "preparing the environment" in run.stderr


def test_a_missing_uv_is_an_environment_failure_reported_as_a_document(tmp_path: Path) -> None:
    bootstrap = Bootstrap(tmp_path, with_uv=False)

    run = bootstrap.run("surface-audit", "--format", "json")

    assert run.returncode == 3
    document = json.loads(run.stdout)
    validate_document(document)
    assert document["operation"] is None
    assert document["status"] == "environment-error"
    assert document["data"] is None
    assert [entry["code"] for entry in document["diagnostics"]] == ["HS-BOOTSTRAP-FAILED"]
    assert "uv" in run.stderr


@pytest.mark.parametrize("arguments", [("surface-audit",), ("surface-audit", "--format", "text")])
def test_a_missing_uv_stays_off_stdout_when_json_was_not_asked_for(
    tmp_path: Path, arguments: tuple[str, ...]
) -> None:
    bootstrap = Bootstrap(tmp_path, with_uv=False)

    run = bootstrap.run(*arguments)

    assert run.returncode == 3
    assert run.stdout == ""
    assert "harness-smith:" in run.stderr


def test_the_equals_form_of_the_json_format_is_recognised(tmp_path: Path) -> None:
    bootstrap = Bootstrap(tmp_path, with_uv=False)

    run = bootstrap.run("surface-audit", "--format=json")

    assert run.returncode == 3
    assert json.loads(run.stdout)["status"] == "environment-error"
