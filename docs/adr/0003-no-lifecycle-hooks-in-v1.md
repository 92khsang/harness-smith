---
status: accepted
date: 2026-09-02
---

# No lifecycle hooks in v1; the CLI and CI carry enforcement

The v1 plugin registers no Claude Code lifecycle hooks of any kind, enforcement or infrastructure. Authority is layered instead: the Rule and Standard are the normative authority, the validator is the deterministic verdict authority, the CLI is the baseline execution surface, and CI is an optional execution surface.

## Why not hooks

Hooks can genuinely block — `PreToolUse` and `ConfigChange` both refuse an action on exit code 2 — so blocking capability is not the objection. The objections are that hooks cannot see changes made outside Claude Code, that some events fire after the change they would need to prevent, that hooks do not work in another agent runtime, and that they carry none of the auditability of a merge gate. `ConfigChange` also cannot see `.claude/rules/**` or `CLAUDE.md` at all, which is half of the Governed Harness.

Timeout behaviour narrows it further for the hook kinds a plugin can actually ship. A `command`, `http`, or `mcp_tool` hook that reaches its timeout is cancelled and its output discarded, and on `PreToolUse` it does not block the call: the documentation says outright not to count on a stalled hook to act as a gate. An Agent SDK callback hook blocks instead, and so does any timed-out hook on `PreModelSwitch` — so this is a property of the kinds we could ship, not of hooks in general.

## Consequences

- A future infrastructure hook is not forbidden in principle, but requires demonstrated need and its own ADR. Any hook may only invoke the same portable validator, never implement a check of its own, so hook and CLI cannot diverge.
- Governance operations stay explicit-invocation by default. Write and delete operations set `disable-model-invocation: true`, and the CLI enforces its own dry-run and `--apply` gates, because skill routing control is not a security boundary.