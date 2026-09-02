---
status: accepted
date: 2026-09-02
---

# The standard is copied into consumer repositories, with a drift state machine

`init` copies the standard from `plugin/resources/standards/` to `docs/harness/HARNESS_STANDARD.md` in the consumer repository, rather than having the entry point reference the plugin's own copy.

## Why

An agent working in the repository must be able to read the standard whether or not the plugin is installed, which is what "the repository is the source of truth" requires. Claude Code does not copy files outside the plugin root into its cache, and `${CLAUDE_PLUGIN_ROOT}` changes on every plugin update, so a cache path is neither stable nor visible to someone reading the repository on GitHub.

## Consequences

- The copy is described by three independent axes, not one compound state. Provenance starts as `generated`, update policy as `pinned`, Management Authority as `harness-smith`. Each axis is stored where its kind of metadata belongs, and the split is by who decides the value rather than by which artifact it describes:

  | File | Holds | Why |
  | :--- | :--- | :--- |
  | `harness.manifest.yaml` | Management Authority, `updatePolicy`, declared Consumer and Writer relations | Human policy choices |
  | `harness.lock.json` | provenance, source id, source version, content digest, drift baseline | Computed, tool-owned |
  | Rule frontmatter | `enforced-by`, `verified-by`, and other rule-local relations | Belongs with its subject |

  The manifest's `authority` mapping records Management Authority through each entry's `authority` or `managed-by` field. `pinned` versus `local` is a choice someone makes, not a result anything computes, so `updatePolicy` sits beside that declaration in the manifest rather than in the lock.

- A local edit makes the digest disagree with the recorded baseline, which is unacknowledged drift. Approving it is one composite transition across both files: the manifest entry's `updatePolicy` becomes `local` and its `managed-by` is replaced by `authority: local`, while the lock's provenance becomes `adopted` and its approved digest and baseline are refreshed, keeping the standard version the edit was based on. Pinning therefore does not forbid a local override; it separates accidental drift from deliberate change.
- That transition spans two files, so it is a concrete instance of the bounded write atomicity in ADR-0008: a crash partway through can leave the manifest updated and the lock not. The half-applied state is detectable rather than silent: a manifest in the post-adoption state with a lock still describing the pre-adoption state, or the inverse combination, raises `HS-AUTHORITY-LOCK-MANIFEST-MISMATCH`.
- Upgrade behaviour follows the update policy: `pinned` is replaced after an explicit diff and approval, `local` is never overwritten automatically and becomes a manual merge.
- The compatibility rules apply to `standardVersion`, the version of the normative contract, and not to the plugin's own release version. A major mismatch is an error, an older minor in the repository is an upgrade warning, and a repository minor ahead of the validator is a validator-too-old error. There is no automatic migration in v1.
- The same shape covers any artifact `init` materialises, so the drift diagnostic `HS-ARTIFACT-UNACKNOWLEDGED-DRIFT` is shared rather than per-artifact-type.