# chimera-memory v0.26.2 — Alpha Onboarding Hardening

## Classification

Narrow patch. No evidence semantics changed. No settlement behavior changed. No new features.

## Summary

v0.26.2 is a focused alpha-onboarding hardening release. It addresses five
friction points found during the first external alpha preparation:

- **F4** — Python version onboarding trap: macOS system `python3` may be 3.9. Install instructions now explicitly use `python3.12` and `uv venv --python 3.12`.
- **F5** — X-Ray mode confusion: README and alpha guide now clearly distinguish committed (PR review) mode from uncommitted (working-tree) mode.
- **F6** — scope_path first-run confusion: docs now recommend `scope_path = "."` for first-time users with a clear explanation of when to narrow it.
- **F7** — SCOPE_DRIFT interpretation: docs now state explicitly that `SCOPE_DRIFT` means checks passed, not that tests failed.
- **F8** — stale hook install next-step text: `hooks install` output now says to create `.chimera/hooks.toml` instead of directing users to `CHIMERA_INTENT` (which predates v0.26 auto-lock).

## Changes

- `packages/chimera-memory/src/chimera_memory/cli.py`: updated `hooks install` next-step message
- `packages/chimera-memory/README.md`: Python 3.12 install block, hooks section rewritten to `hooks.toml` pattern, SCOPE_DRIFT explanation, X-Ray committed/uncommitted guidance
- `docs/alpha-trial.md`: new external alpha trial guide
- `packages/chimera-memory/tests/test_claude_hooks.py`: 2 new tests guarding install output
- `packages/chimera-memory/tests/test_public_docs.py`: 11 new tests guarding README and alpha-trial docs

## What did not change

- Settlement logic (VALIDATED / SCOPE_DRIFT / CONTRADICTED / UNSETTLED)
- Claim lock / settle / report semantics
- Hook scripts
- MCP server
- Storage format
- No registry, scoring, routing, dashboard, or filtering added
