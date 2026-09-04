"""The product boundary a consumer actually invokes: `bin/harness-smith`, with the real uv.

Every other suite reaches the tool through the development environment, where the project is
installed editable and current source is therefore unavoidable. That is the wrong shape for
anything about how the launcher builds and installs an environment, because an editable
install cannot go stale. These tests copy the real plugin tree, give it its own uv cache and
plugin data directory, and observe what the launcher hands back.

They are the only tests that need the real uv, and they are skipped without it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.support import PLUGIN_ROOT, make_repository, validate_document, write_tree

# A literal that reaches stdout, so a source-only change is observable at the boundary rather
# than by reading the installed files. The test asserts it is present before rewriting it, so
# a rename of the description fails loudly instead of silently testing nothing.
DESCRIPTION = "Author and govern the repository-owned agent harness."
REWRITTEN_DESCRIPTION = "Author and govern the repository-owned agent harness, second build."

needs_real_uv = pytest.mark.skipif(
    shutil.which("uv") is None, reason="needs the real uv to build and install the project"
)


@dataclass(frozen=True)
class RealPlugin:
    """A copy of the real plugin tree with a cache and data directory of its own."""

    root: Path
    data_dir: Path
    cache_dir: Path

    def run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.root / "bin" / "harness-smith"), *arguments],
            capture_output=True,
            text=True,
            check=False,
            env={
                **os.environ,
                "HARNESS_SMITH_DATA_DIR": str(self.data_dir),
                "UV_CACHE_DIR": str(self.cache_dir),
            },
        )

    def rewrite_source(self, old: str, new: str) -> None:
        """Change source only. The package name, version, pyproject.toml and uv.lock all stay
        as they are, which is the case a version-keyed wheel cache gets wrong."""
        path = self.root / "src" / "harness_smith" / "cli.py"
        text = path.read_text(encoding="utf-8")
        assert old in text, f"the literal this test rewrites is gone: {old!r}"
        path.write_text(text.replace(old, new), encoding="utf-8")

    @property
    def ready_environments(self) -> list[str]:
        environments = self.data_dir / "venvs"
        if not environments.is_dir():
            return []
        return sorted(path.stem for path in environments.glob("*.ready"))


@pytest.fixture
def plugin(tmp_path: Path) -> RealPlugin:
    root = tmp_path / "plugin"
    shutil.copytree(
        PLUGIN_ROOT, root, ignore=shutil.ignore_patterns(".venv", "__pycache__", ".*_cache")
    )
    return RealPlugin(root, tmp_path / "plugin-data", tmp_path / "uv-cache")


@needs_real_uv
def test_the_launcher_answers_for_the_repository_it_is_pointed_at(
    plugin: RealPlugin, tmp_path: Path
) -> None:
    """One acceptance test at the real boundary: the launcher binary, the environment it
    prepares for itself, and the document that comes back."""
    repository = write_tree(make_repository(tmp_path / "repository"), {"CLAUDE.md": "# entry\n"})

    run = plugin.run("surface-audit", "--format", "json", "--root", str(repository))

    assert run.returncode == 0, run.stderr
    document = json.loads(run.stdout)
    validate_document(document)
    assert document["data"]["artifacts"] == [
        {
            "locator": "CLAUDE.md",
            "type": "entry-point",
            "scope": "repository",
            "representation": "file",
            "provenance": "authored",
            "managementAuthority": "unknown",
            "activation": "unknown",
            "activationCause": "runtime-state-not-read",
            "harnessRelevant": True,
            "sets": ["inventoried"],
        }
    ]


@needs_real_uv
def test_the_launcher_refuses_a_repository_whose_governance_file_will_not_read(
    plugin: RealPlugin, tmp_path: Path
) -> None:
    """The configuration error at the real boundary: exit 2, no report, and a document
    automation can still read."""
    repository = write_tree(
        make_repository(tmp_path / "repository"),
        {"CLAUDE.md": "# entry\n", "harness.manifest.yaml": "schemaVersion: 1\nrelations: {}\n"},
    )

    run = plugin.run("surface-audit", "--format", "json", "--root", str(repository))

    assert run.returncode == 2, run.stderr
    document = json.loads(run.stdout)
    validate_document(document)
    assert document["status"] == "usage-error"
    assert document["data"] is None
    assert [finding["code"] for finding in document["diagnostics"]] == ["HS-MANIFEST-INVALID"]


@needs_real_uv
def test_the_launcher_refuses_a_repository_whose_lock_will_not_read(
    plugin: RealPlugin, tmp_path: Path
) -> None:
    repository = write_tree(
        make_repository(tmp_path / "repository"),
        {"CLAUDE.md": "# entry\n", "harness.lock.json": "{not json\n"},
    )

    run = plugin.run("surface-audit", "--format", "json", "--root", str(repository))

    assert run.returncode == 2, run.stderr
    document = json.loads(run.stdout)
    validate_document(document)
    assert document["status"] == "usage-error"
    assert document["data"] is None
    assert [finding["code"] for finding in document["diagnostics"]] == ["HS-LOCK-INVALID"]


@needs_real_uv
def test_a_source_only_update_runs_the_new_code_rather_than_a_cached_wheel(
    plugin: RealPlugin,
) -> None:
    """uv caches the wheel it builds for a local project under that project's name and
    version, and a plugin's version does not move for every source change. The fingerprint
    already chose a new environment; uv still filled it from the previous build."""
    first = plugin.run("--help")
    plugin.rewrite_source(DESCRIPTION, REWRITTEN_DESCRIPTION)
    second = plugin.run("--help")

    assert first.returncode == 0, first.stderr
    assert DESCRIPTION in first.stdout
    assert second.returncode == 0, second.stderr
    assert REWRITTEN_DESCRIPTION in second.stdout
    assert len(plugin.ready_environments) == 2


@needs_real_uv
def test_a_prepared_environment_keeps_answering_from_the_source_it_was_built_from(
    plugin: RealPlugin,
) -> None:
    """The warm path: a second run at one fingerprint prepares nothing and does not drift."""
    plugin.rewrite_source(DESCRIPTION, REWRITTEN_DESCRIPTION)

    first = plugin.run("--help")
    second = plugin.run("--help")

    assert REWRITTEN_DESCRIPTION in first.stdout
    assert REWRITTEN_DESCRIPTION in second.stdout
    assert len(plugin.ready_environments) == 1


@needs_real_uv
def test_a_lock_that_no_longer_describes_the_project_is_refused(plugin: RealPlugin) -> None:
    """--frozen installed the stale lock and marked the environment ready while a declared
    dependency was missing from it."""
    pyproject = plugin.root / "pyproject.toml"
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

    run = plugin.run("surface-audit", "--format", "json")

    assert run.returncode == 3
    document = json.loads(run.stdout)
    validate_document(document)
    assert [entry["code"] for entry in document["diagnostics"]] == ["HS-BOOTSTRAP-FAILED"]
    assert plugin.ready_environments == []
