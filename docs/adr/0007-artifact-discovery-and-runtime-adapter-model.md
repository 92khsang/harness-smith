---
status: proposed
date: 2026-09-02
---

# Artifacts, discovery, and the runtime adapter are three separate things

The model has three layers that were repeatedly conflated during design, so they are separated by construction.

**Artifact types** are runtime-independent: Entry Point, Rule, Skill, Agent, Hook, Enforcement, Documentation, Decision Record. Generated-versus-authored and vendor-specific-versus-canonical are attributes on any type, not types of their own, and runtime state is outside the taxonomy entirely.

**Discovery** works in three layers.

- *Runtime-native structural discovery*: locations the runtime itself defines and loads from, such as the entry point, `.claude/rules/**`, `.claude/skills/`, `.claude/agents/`, and the plugin's own component directories.
- *Harness-standard conventional discovery*: locations this standard prescribes, which the runtime knows nothing about — `docs/adr/**`, the reserved `docs/harness/**`, the canonical Enforcement locations, and the manifest and lock themselves.
- *Relation-based discovery*: found because something points at it — registered in the manifest or lock, referenced from the entry point, cited as evidence by another artifact's relation, or named in an explicit audit scope.

Documentation and Enforcement have no runtime-native location, which is why they are never swept in by location alone. That is a separate fact from the standard being free to prescribe conventional locations for them, which it does. A repository's ordinary `docs/**` therefore stays outside the harness while `docs/harness/**` does not.

One scan emits a Discovery Report with three parts: Artifact Inventory, Container Inventory, and Runtime Component Observations, so that runtime surfaces with no artifact type stay visible without breaking the inventory's type invariant.

**The runtime adapter** owns everything Claude-Code-specific: which paths are structural, how `plugin.json` component overrides resolve, and the Capability Policy for each Surface. v1 ships exactly one adapter.

## Consequences

- `managed`, `observed-only`, and `unsupported` are adapter capability policy, not artifact metadata, so they are looked up rather than stored.
- Plugin discovery must parse `plugin.json` and resolve component overrides before scanning; default paths alone would miss components. The documented merge semantics differ per field, and hooks, MCP, and LSP have their own combination rules, so the adapter follows the runtime rather than reimplementing or validating the manifest — `claude plugin validate` owns that.
- AGENTS.md is not structurally discovered, because Claude Code does not load it. It appears only as an import target of the entry point. Making it a first-class entry point would mean adding a second adapter, which v1 does not do.
- Adding a second runtime means adding an adapter, not changing the artifact model. Whether the shared behaviour is then promoted to a vendor-neutral canonical source is deliberately left open.