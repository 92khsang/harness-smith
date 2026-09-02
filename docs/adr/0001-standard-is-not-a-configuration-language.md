---
status: accepted
date: 2026-09-02
---

# The normative standard is not a configuration language

harness-smith ships one opinionated standard rather than a mechanism for each repository to declare its own. `HARNESS_STANDARD.md` is normative prose and is never read at runtime by the validator: changing a mechanically enforced rule means changing the normative rule, its template or policy data, the validator, and the validation test together.

## Considered options

- **Policy-as-data**: the validator derives its checks from the standard file. Rejected — an arbitrary Markdown edit would silently change enforcement semantics, and the standard is the artifact most likely to be edited casually.
- **Per-repository declared standard**: the plugin ships a schema and each repository declares its own taxonomy. Rejected for v1 — the schema language can only be designed well once the taxonomy is stable, and there is no evidence yet of a second opinion needing to be expressed.

## Consequences

- The four artifacts are kept in step by discipline, not by construction. The `enforced-by` and `verified-by` relations make the structural half checkable — that a rule claiming mechanical enforcement names an enforcer, and that the enforcer has a test — and the test checks that the implementation behaves as written. Whether the implementation means the same thing as the prose is a review judgement, and nothing here verifies it.
- Moving to a configurable standard later stays open; building it first would not have been reversible.