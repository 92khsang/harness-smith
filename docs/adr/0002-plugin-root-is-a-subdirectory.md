---
status: accepted
date: 2026-09-02
---

# The plugin root is a subdirectory, not the repository root

Plugin components must sit directly under the plugin root, and this repository is also a consumer of the plugin it ships. Putting the plugin root at the repository root would place two harness surfaces at the same depth, with `.claude-plugin/` and `.claude/` side by side meaning opposite things. The plugin root is `plugin/` instead, and the marketplace manifest at `.claude-plugin/marketplace.json` points at it with a relative source.

## Consequences

- Scope classification is structural rather than a hardcoded path list: everything under the plugin root is `scope: plugin`, everything else in the repository is `scope: repository`. A tool whose entire purpose is unambiguous artifact classification cannot afford to classify itself by exception list.
- Local development uses `--plugin-dir ./plugin`; packaging and validation use `claude plugin validate ./plugin --strict`.
- Relative marketplace sources do not resolve when a user adds the marketplace by direct URL to `marketplace.json`. Distribution is git-source or local-directory only.