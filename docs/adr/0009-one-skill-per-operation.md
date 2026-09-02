---
status: accepted
date: 2026-09-02
---

# One skill per operation, split by whether the operation writes

The twelve governance operations are exposed as twelve skills under `plugin/skills/`, each a thin front end over one subcommand of a shared Python CLI. Twelve skills are not twelve implementations: they share one inventory primitive, one parser, one validator, and one mutation engine.

## Why not one dispatcher skill

`disable-model-invocation` is a per-skill field. A single dispatching skill would force all twelve operations to be either model-invocable or user-only. Splitting them lets the boundary fall where it belongs: `init`, `config-gc`, `skill-create`, `artifact-manage`, and `entrypoint-manage` are user-only; the read-only operations stay model-invocable. This is the failure ECC has, where a deletion skill is open to model invocation with only prose as its guard.

A second reason is routing: a skill's description is how the model decides to invoke it, and twelve intents compressed into one description match nothing well.

## Consequences

- `rules-distill`, `skill-scout`, and `artifact-route` return candidates or recommendations only; applying them goes through the user-only write operations.
- `surface-audit` is a thin report over the shared inventory primitive, not the other way round, so the other operations do not pay report-formatting cost to reuse it.
- Every subcommand satisfies one implementation-independent `OperationContract` — an interface and result schema covering dry-run, `--apply`, exit codes, write scope, and idempotence — and the contract tests are parameterised over all twelve. Written as prose the contract would go unchecked; expressed as a contract with tests over every operation it is enforced. Whether that contract is realised as a base class, a Protocol, or composition is an implementation decision, deliberately left open here.
- New plugins are told to use `skills/` rather than `commands/`, so `commands/` is only consumed, never produced.