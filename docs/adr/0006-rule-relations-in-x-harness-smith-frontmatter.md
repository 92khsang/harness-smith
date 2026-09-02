---
status: proposed
date: 2026-09-02
---

# Rule governance relations live in `x-harness-smith` frontmatter

A Rule's `id`, `enforced-by`, and `verified-by` live in an `x-harness-smith` mapping in the rule's own YAML frontmatter, even though `paths` is the only frontmatter key Claude Code documents for `.claude/rules/**`.

## Evidence

Measured in an isolated repository on Claude Code 2.1.258: a rule carrying a nested `x-harness-smith` mapping loads at session start; the same with `paths` activates when a matching file is read through the Read tool; the mapping's values never appear in context, only the body does; and the frontmatter is byte-identical after Claude Code edits the file. The dependency is therefore weaker than it looks — harness-smith reads the keys from disk with its own parser, so it relies on Claude Code not corrupting the file rather than on Claude Code exposing the keys.

## Considered options

- **A registry file keyed by rule path**: rejected because a registry entry would dangle whenever a rule is renamed, moved, or deleted, and because it splits one fact across two files. Co-location removes that particular dangling class; it does not remove dangling in general, since an `enforced-by` or `verified-by` target can still be deleted or moved out from under a rule. The validator checks those targets in both directions.
- **Flat custom keys**: rejected in favour of the `x-harness-smith` namespace, which costs nothing and avoids collision with future official keys.

## Consequences

- A person reading the rule file sees the relation; the model reading the rule in context does not, because the runtime strips frontmatter before injection. Anything the agent needs to act on must be in the body.
- harness-smith does not detect whether a rule's custom frontmatter was previously present and removed; there is no persisted expectation to compare against. Platform-wide regression is the scheduled compatibility probe's job, and this limit is stated in the compatibility contract.
- If custom frontmatter ever becomes impossible, relations move to a `relations` section in `harness.manifest.yaml`, which already keys by path. The name is reserved in the schema documentation; the section is not created until it is needed.