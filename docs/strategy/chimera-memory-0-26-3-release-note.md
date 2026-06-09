# chimera-memory v0.26.3 — External Alpha Onboarding Patch

## Classification

Narrow patch. No evidence semantics changed. No settlement behavior changed. No new features.

## Summary

v0.26.3 is a narrow external-alpha onboarding patch. It improves missing-git
guidance, starter hooks.toml setup, alpha docs links, session lifecycle docs,
and baseline-check guidance.

These changes were justified by a true external alpha trial (studyapp, Next.js /
TypeScript / pnpm) where a high-level external engineer hit five distinct
first-use friction points.

## Changes

### CLI

- `chimera-memory init`: detects missing `.git` and exits with a clear message:
  "Chimera Memory expects a git repository. Run `git init` first."
- `chimera-memory hooks init`: new command — creates a starter `.chimera/hooks.toml`
  with commented examples for Python (uv, .venv) and Node/TypeScript (pnpm, npm).
  Refuses to overwrite existing config without `--force`.

### Docs

- `docs/alpha-trial.md`: rewritten with:
  - F10: canonical repo URL (`maclit64-lang/chimera-memory`) added to prevent 404
  - F11: git repository prerequisite and `git init` guidance
  - F12: `chimera-memory hooks init` command referenced
  - F13: session lifecycle explanation (sessions group claims/receipts)
  - F14/baseline: run falsifier before the task; pre-existing failures are baseline
    noise, not organic_real evidence
  - F15: build/typecheck should be in `falsifiers` when it is the main proof

### Tests

- 14 new tests in `test_first_run_ux.py` covering F11 (init outside .git) and
  F12 (hooks init template creation, no-overwrite, force, content guards)
- 11 new tests in `test_public_docs.py` covering all alpha-trial docs guards
- 7 pre-existing tests updated to add `.git` directory where needed

## What did not change

- No evidence semantics changed
- No settlement logic changed
- No scoring/routing/ranking added
- No registry/dashboard/cloud features added
- No automatic session start
- No must_not_break-as-CONTRADICTED behavior
- No v0.27 work
