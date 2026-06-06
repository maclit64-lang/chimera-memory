# Chimera Memory First-Run Quickstart

A practical guide for getting started with `chimera-memory` from a local install.

---

## Install

```bash
# From local checkout (until public PyPI is available)
uv build packages/chimera-memory-types --out-dir /tmp/cm-dist
uv build packages/chimera-memory --out-dir /tmp/cm-dist
pip install /tmp/cm-dist/*.whl
```

---

## Step 1: Initialize a ledger

```bash
chimera-memory init
```

Creates `.chimera-memory/` in the current directory. All data stays local.

---

## Step 2: Wrap a verification command

The most basic use — wrap a command and record whether it passed:

```bash
chimera-memory wrap -- pytest packages/chimera-memory/tests
```

For labeled evidence (recommended):

```bash
chimera-memory wrap \
  --failure-origin organic_real \
  --verification-scope package \
  --scope-path packages/chimera-memory \
  -- pytest packages/chimera-memory/tests
```

---

## Step 3: Use sessions for attribution

Sessions link multiple wrapped commands to one named work session:

```bash
chimera-memory session start \
  --branch feat/my-feature \
  --task-label "Add new feature" \
  --agent kiro \
  --model claude-sonnet-4.6 \
  --harness-id kiro-cli

chimera-memory wrap --failure-origin organic_real --verification-scope package \
  -- pytest packages/chimera-memory/tests

chimera-memory session end --status PASSED
```

---

## Step 4: View a receipt

```bash
chimera-memory receipt latest
chimera-memory receipt latest --format markdown
chimera-memory receipt latest --format json
```

---

## Step 5: Preflight advisory

Before starting work, check historical failures and recommended checks:

```bash
chimera-memory preflight --from-git
chimera-memory preflight --scope-path packages/chimera-memory
```

This is advisory only — no routing or gating decisions.

---

## Step 6: CI receipt bundle

In CI, produce machine-readable receipt artifacts:

```bash
chimera-memory receipt bundle --output-dir ci-bundle
# Then: cat ci-bundle/github-summary.md >> $GITHUB_STEP_SUMMARY
```

---

## Step 7: Evidence bundle (cross-agent)

Share evidence between agents using dry-run only:

```bash
# Export
chimera-memory evidence bundle --output-dir /tmp/my-evidence

# Inspect before any import
chimera-memory evidence import /tmp/my-evidence --dry-run --json
```

Write-capable import is not built in v0.6.

---

## Step 8: M2B readiness gate

Check whether enough labeled organic evidence exists for future M2B analysis:

```bash
chimera-memory m2b-readiness
chimera-memory m2b-readiness --dq-only
```

Typical output on a fresh ledger:

```
Readiness: BLOCKED
Blockers:
  - metadata coverage too low (use --failure-origin and --verification-scope on wrap)
  - organic_real claims too few
```

---

## What is NOT built in v0.6

- M2B drift scoring or model ranking
- Routing or autonomy decisions
- Hosted/cloud sync
- Team dashboard
- ORIAS
- Write-capable evidence import
- GraphSource/substrate writes

---

## Common commands

```bash
chimera-memory --help
chimera-memory status
chimera-memory reliability --organic-only
chimera-memory failures --failure-origin organic_real
chimera-memory repair-loops
chimera-memory errata list
chimera-memory verify
```
