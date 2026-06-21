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
- **Version:** base `0.26.4`; the launch release candidate bumps both packages
  to `0.26.5` in lockstep (see "Ticket sequence" → release closeout prep).
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
- **L-002 — Reusable GitHub Action / Receipt-on-PR (DONE).** Distribution
  layer: a composite repo-root `action.yml` installs Chimera Memory, generates
  `PR_EVIDENCE.md` for the PR diff, and surfaces it three ways — a sticky PR
  comment, a job step summary, and an uploaded artifact. Fork-safe: a restricted
  comment token degrades to summary + artifact and never fails the job. Adds a
  `--format pr-comment` X-Ray output (no new evidence semantics — built from the
  existing `verdict_label`/`counts`) and an example workflow at
  `docs/examples/github-actions/pr-evidence.yml`. Advisory only; the `fail-on`
  input defaults to `never` (CI gating is deferred, not part of L-002).
- **L-002R — Release-readiness closeout (DONE, docs only).** Verified that the
  PyPI packages (`chimera-memory`/`chimera-memory-types` 0.26.4) are public but
  the reusable Action was **not** consumable at the existing `v0.26.4` tag
  (which predates `action.yml`). Annotated the two Action references for honesty and
  produced the release/consumability checklist + manual PR smoke protocol in
  [`docs/release-action-readiness.md`](release-action-readiness.md). No tag,
  push, publish, or version change performed.
- **Release closeout prep — `v0.26.5` RC (DONE, no publish).** Lockstep bump of
  `chimera-memory` + `chimera-memory-types` 0.26.4 → 0.26.5 (dep bound
  `>=0.26.5,<1.0`, lockfile updated); release note at
  [`docs/releases/v0.26.5.md`](releases/v0.26.5.md); Action/docs examples now
  reference `@v0.26.5`. `v0.26.4` left untouched (it maps to the shipped PyPI
  build). Push/tag/publish commands are prepared but **NOT run** — awaiting
  founder authorization (Path A).
- **L-003 — Evidence Quality Enrichment (DONE).** Advisory evidence-quality
  warnings derived only from settled-claim command evidence (command text,
  role, outcome, stdout excerpt) — no new scoring, no schema rewrite:
  `LINT_ONLY_EVIDENCE`, `ZERO_TESTS_COLLECTED`, `GREEN_ONLY_EVIDENCE`. Rendered
  as a `## Evidence Quality Warnings` section in `PR_EVIDENCE.md` (only when
  present) and a compact count line in the PR comment. Advisory only — they flag
  weak/missing evidence, never correctness. Built on a separate worktree; the
  release RC `c8e6526bf` is unchanged.
- **L-004 — Test Integrity Detector (DONE).** Advisory test-integrity warnings
  derived from the diff (added lines + deleted files), independent of claim
  locks: `TEST_SKIP_ADDED`, `TEST_XFAIL_ADDED`, `ONLY_FOCUS_ADDED`,
  `TEST_FILE_DELETED`. Rendered as a `## Test Integrity Warnings` section in
  `PR_EVIDENCE.md` (only when present) and a compact count in the PR comment.
  Added small read-only git diff helpers (added lines + deleted files); no
  schema rewrite. Advisory only — they flag possible test weakening, never
  correctness. Built on a separate worktree; release RC `c8e6526bf` unchanged.
- **L-005 — Opt-in CI evidence gate (DONE).** A pure `evaluate_evidence_gate`
  policy over existing X-Ray fields (verdict label + warning/claim counts; no new
  heuristics), exposed via `xray generate --fail-on <policy>` (default `never`,
  exit 2 on policy failure, gate messages to stderr) and the Action's `fail-on`
  input. Policies: never, review-required, warnings, evidence-quality-warnings,
  test-integrity-warnings, contradicted, unsettled, scope-drift, evidence-dark.
  The Action's gate step runs last so the receipt/summary/artifact/comment are
  produced first. Advisory by default — enforces evidence policy, never code
  correctness. Separate worktree; release RC `c8e6526bf` unchanged.
- **L-003B — Later product ticket** (stale-evidence / changed-files-not-exercised
  warnings). Not started.

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
