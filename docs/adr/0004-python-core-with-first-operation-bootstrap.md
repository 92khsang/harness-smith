---
status: proposed
date: 2026-09-02
---

# Python core, prepared by first-operation bootstrap rather than a SessionStart hook

The core is Python (>= 3.12, developed on 3.14) managed with `uv`, using `ruamel.yaml`, `pytest`, `ruff`, and `mypy --strict`. Claude Code does not auto-install Python dependencies, and the documented way to prepare them is a `SessionStart` hook that syncs into `${CLAUDE_PLUGIN_DATA}`. This project deliberately departs from that pattern and prepares the environment lazily, on the first explicit operation.

## Why Python

Long-term maintainability by this repository's author is the deciding criterion for a personal-first project. `StrEnum`, `Literal`, `match`, `assert_never` and `mypy --strict` give the artifact taxonomy the same exhaustiveness a discriminated union would, and external YAML and JSON require runtime validation in any language.

## Why not the documented hook

A tool that audits other people's context and automation footprint should not install a session-start side effect in every repository where it is enabled. The check is cheap — a venv presence test and a fingerprint over `pyproject.toml`, `uv.lock`, and the Python minor version — so session-start cost stays zero.

## Consequences

- The first operation after an install or a dependency change is slower, and a preparation failure surfaces mid-task rather than at session start.
- `uv` and Python are declared runtime prerequisites rather than hidden. CI does not rely on the lazy path; it runs `uv sync --frozen` explicitly.
- The standalone validator must run without Claude Code installed at all, so the Claude Code version floor applies only to plugin-hosted operation and to `--compat`.