---
status: proposed
date: 2026-09-02
---

# The standard is copied into consumer repositories, with a drift state machine

`init` copies the standard from `plugin/resources/standards/` to `docs/harness/HARNESS_STANDARD.md` in the consumer repository, rather than having the entry point reference the plugin's own copy.

## Why

An agent working in the repository must be able to read the standard whether or not the plugin is installed, which is what "the repository is the source of truth" requires. Claude Code does not copy files outside the plugin root into its cache, and `${CLAUDE_PLUGIN_ROOT}` changes on every plugin update, so a cache path is neither stable nor visible to someone reading the repository on GitHub.

## Consequences

- The copy is described by three independent axes, not one compound state. Provenance starts as `generated`; update policy starts as `pinned`; Management Authority starts as `harness-smith`. Each axis is recorded where its kind of metadata belongs: `harness.lock.json` holds provenance, source id, source version, content digest, and the drift baseline, because those are computed; `harness.manifest.yaml` holds the authority declaration, because that is a human policy statement.
- A local edit makes the digest disagree with the recorded baseline, which is unacknowledged drift. Reviewing and approving it moves Provenance to `adopted`, update policy to `local`, and Management Authority to `local`, keeping the standard version and digest it was based on. Pinning therefore does not forbid a local override; it separates accidental drift from deliberate change.
- Upgrade behaviour follows the update policy: `pinned` is replaced after an explicit diff and approval, `local` is never overwritten automatically and becomes a manual merge.
- The compatibility rules apply to `standardVersion`, the version of the normative contract, and not to the plugin's own release version. A major mismatch is an error, an older minor in the repository is an upgrade warning, and a repository minor ahead of the validator is a validator-too-old error. There is no automatic migration in v1.
- The same shape covers any artifact `init` materialises, so the drift diagnostic `HS-ARTIFACT-UNACKNOWLEDGED-DRIFT` is shared rather than per-artifact-type.