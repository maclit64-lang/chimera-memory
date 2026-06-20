# Chimera Memory — OSS Launch Execution Plan

Canonical, current operating plan for the Chimera Memory open-source launch.
This supersedes earlier scratch planning notes; keep this file as the single
source of truth.

## Product

- **Promise:** Your AI agent says it's done. Chimera Memory makes it prove it.
- **Category:** Proof-Carrying PRs for AI-written code.
- **Main artifact:** `PR_EVIDENCE.md` (the Merge X-Ray receipt).
- **Honesty rule (non-negotiable):** Chimera Memory proves *evidence quality*,
  not code correctness. It never claims code is correct, safe, production-ready,
  or that an agent intentionally lied. It reports evidence as weak, missing,
  contradicted, unsettled, scope-drifted, or evidence-dark, and always states
  what it does not prove.

## Launch base

- **Branch:** `oss/memory-launch`, cut from `chimera-memory-upstream/main`.
- **Base commit:** `04a9b4fa5`.
- **Version:** `0.26.4`.
- The standalone upstream line is canonical. The `court/crt-foundation` v0.6.1
  tree is **reference-only** (e.g. its granular evidence-smell taxonomy is a
  possible post-launch port candidate; not ported at launch).

### Guardrails

- Do not mutate the dirty `court/crt-foundation` tree.
- Do not merge the two unrelated histories.
- Do not port the court smell taxonomy at launch.
- Do not ship a GitHub App before the OSS GitHub Action.
- Do not introduce any correctness/safety/approval overclaim.

## Baseline status (L-000 — accepted)

- `oss/memory-launch` established from upstream `main`; tree clean.
- Full test suite: **1037 passed, 0 failed**.
- `chimera-memory demo`: pass.
- `uv build` (wheels + sdists, both packages): pass.
- Clean-install smoke from built wheels into a fresh venv: pass.
- Court tree: untouched.

## Ticket sequence

- **L-000 — Baseline (DONE).** Establish branch; prove tests/demo/build/install.
- **L-001 — Launch polish (DONE).** Shipped on `oss/memory-launch`:
  1. `python -m chimera_memory` entrypoint (`__main__.py`).
  2. At-a-glance verdict banner on `PR_EVIDENCE.md` (derived from the existing
     verdict model; no new scoring).
  3. Duplicate working-tree-warning audit + dedupe.
  4. README hero focus on `PR_EVIDENCE.md`.
  5. This execution-plan doc.
- **L-002 — Reusable GitHub Action / Receipt-on-PR (in progress).** Distribution
  layer: a composite repo-root `action.yml` installs Chimera Memory, generates
  `PR_EVIDENCE.md` for the PR diff, and surfaces it three ways — a sticky PR
  comment, a job step summary, and an uploaded artifact. Fork-safe: a restricted
  comment token degrades to summary + artifact and never fails the job. Adds a
  `--format pr-comment` X-Ray output (no new evidence semantics — built from the
  existing `verdict_label`/`counts`) and an example workflow at
  `docs/examples/github-actions/pr-evidence.yml`. Advisory only; the `fail-on`
  input defaults to `never` (CI gating is deferred, not part of L-002).
- **L-003 / L-004 — Later polish.** Verdict-vocabulary refinement, scope-drift
  severity classification, and other sharp-edge items as scoped.

## Out of scope (do not build yet)

Chimera Engine/Harness, Cortex, Consequence Engine, Foundry, Rehearsal, model
training/routing/scorecards, cloud sync, hosted dashboards, enterprise
analytics, heavy/cross-repo relapse, Repo Scar Map, GitHub App (before the OSS
Action), and any "proves code is correct" framing.

## Definition of launch-ready (Apple-grade)

Clean branch and tree; full tests green; first-run (`demo`/`quickstart`) works;
wheel builds and clean-installs; `PR_EVIDENCE.md` opens with an at-a-glance
verdict and a clear "what this does not prove" section; no stale docs, no orphan
files, no overclaims.
