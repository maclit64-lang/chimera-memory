# chimera-memory Live CI Self-Dogfood (v0.4)

This document explains the live `.github/workflows/chimera-memory-ci.yml` workflow —
the actual CI integration, as opposed to the reference example in `docs/examples/`.

---

## What the live workflow does

1. Checks out the repo with full history (`fetch-depth: 0`) for `preflight --from-git`
2. Builds chimera-memory from the checkout and installs it (not from PyPI)
3. Runs `chimera-memory preflight --from-git` (advisory, `continue-on-error: true`)
4. Starts a chimera-memory session
5. Wraps `pytest`, `mypy`, and `ruff` — exit codes propagate; failing checks fail CI
6. Ends the session (`if: always()` — so receipt exists even if checks fail)
7. Generates `receipt bundle --include-preflight --from-git`
8. Generates `evidence bundle` + dry-run import report
9. Appends `github-summary.md` to `$GITHUB_STEP_SUMMARY`
10. Uploads `ci-bundle/` as a GitHub Actions artifact

## How it differs from the docs/examples workflow

| Aspect | `docs/examples/` | Live workflow |
|---|---|---|
| Install source | `pip install chimera-memory` (PyPI) | Built from checkout |
| Trigger | All push/PR | `workflow_dispatch` only (see below) |
| Purpose | Copy-paste for external users | Self-dogfoods this repo |
| Session label | Generic | Includes `github.run_id` |

## Why workflow_dispatch only

This repo has APFS dataless pack objects (observed in `startup_failure` runs in repo history). Push and pull_request triggers attempt to process these and fail at startup before any step runs. `workflow_dispatch` avoids that noise.

To enable push/PR triggers: clone this repo fresh to a non-APFS environment (Linux), push from there, and uncomment the `pull_request` block in the workflow.

## Exit-code preservation

`chimera-memory wrap` exits with the same code as the wrapped command. A `CONTRADICTED` claim does not suppress the exit code. If `pytest` exits 1, the CI step fails — even if the claim was recorded.

Receipt generation uses `if: always()` so you have evidence regardless of whether checks passed or failed.

## What artifacts are uploaded

The `ci-bundle/` directory contains:

| File | Description |
|---|---|
| `receipt.md` / `receipt.json` | Session receipt |
| `github-summary.md` | Step summary content |
| `preflight.md` / `preflight.json` | Preflight advisory |
| `status.json` | DQ status |
| `reliability.json` | Organic-only reliability |
| `failures.json` | Effective failures |
| `verify.json` | Integrity check |
| `evidence/` | Portable claim events bundle |
| `evidence-dry-run.json` | Dry-run import report |

The raw `.chimera-memory/` ledger is **not** uploaded. Only the generated bundle.

## `preflight --from-git` and `source: none`

On a clean tree (no modified files), `preflight --from-git` returns `source: none`. This is expected and not an error. The preflight step uses `continue-on-error: true`. To use an explicit scope, add `--scope-path packages/chimera-memory` to the preflight command.

## Supporting dogfood

This workflow runs on the actual chimera-memory source. Each run accumulates evidence in the ephemeral runner's ledger. The evidence bundle is uploaded as an artifact.

Evidence from CI runners does not merge into local developer ledgers automatically — evidence import is dry-run only in v0.3.x/v0.4.x.

## What is not built

- M2B scoring
- Model routing
- Hosted/cloud sync
- Evidence write-import (dry-run only)
- GitHub App or PR bot
- Dashboard

## M2B readiness in CI

Each CI run starts with an empty ledger (ephemeral runner). M2B readiness will always be `blocked` on a fresh ledger. Do not gate CI jobs on M2B readiness. It is meaningful only in persistent local developer ledgers.
