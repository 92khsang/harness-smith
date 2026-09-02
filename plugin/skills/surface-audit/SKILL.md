---
name: surface-audit
description: Inventory the agent harness of this repository - every harness artifact, the files that contain hook declarations, and the runtime components that have no artifact type. Use when asked what harness artifacts exist, which of them the runtime loads, who is allowed to change one, or for an audit of the repository's harness surface.
---

# surface-audit

Report what the repository's agent harness actually contains. Read-only: it writes nothing and
proposes nothing.

## Run it

```bash
CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/bin/harness-smith" \
  surface-audit --format json
```

Run it from inside the repository under audit, or add `--root <path>`. The first run of any
operation prepares the plugin's Python environment and takes a few seconds; later runs do not.

Drop `--format json` for a short human-readable summary instead.

## Read the result

With `--format json`, stdout carries exactly one `OperationResult` document and nothing else;
progress and errors go to stderr. `data` holds the three parts of the Discovery Report:

- `artifacts` - the discovered artifacts, each with its type, scope, provenance, management
  authority, activation, and the governance sets it belongs to.
- `containers` - files that hold artifacts addressed by pointer rather than by path, and what
  each one holds.
- `observations` - runtime components that have no artifact type, with the adapter's capability
  policy for each.

Exit codes: `0` nothing to report, `1` a policy violation, `2` a usage or precondition error,
`3` an environment failure. Every finding in `diagnostics` carries an `HS-*` code and its
remediation; report the remediation rather than inventing one.
