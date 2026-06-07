# Kiro Agent — Chimera Memory Dogfood Prompt

Use this prompt to onboard a Kiro agent session with correct Chimera Memory discipline.

## Quick reference

```bash
chimera-memory agent-guide --agent kiro
chimera-memory template dogfood --scope-path packages/chimera-memory
```

---

## Prompt (paste at session start)

You are using Chimera Memory to record reliability evidence for this task.

**Run these commands in order. Do not skip steps.**

### Step 1 — Preflight (always first)

```bash
chimera-memory preflight --scope-path <your-scope-path>
```

Review the advisory. It is non-blocking. Proceed regardless.

### Step 2 — Start session

```bash
chimera-memory session start \
  --branch <current-git-branch> \
  --task-label "<short task description>" \
  --agent kiro \
  --model claude-sonnet-4-5  # use your actual model
  --harness-id kiro-cli
```

### Step 3 — Wrap every verification command

```bash
chimera-memory wrap \
  --failure-origin <origin> \
  --scope-path <scope> \
  --verification-scope package \
  [--repair-loop-id <loop-slug> --repair-phase <phase>] \
  -- <command>
```

**`--scope-path` is required** — omitting it prevents preflight intelligence from anchoring the claim.

**`--failure-origin` is required** — use exactly one of:

| Value | When |
|-------|------|
| `organic_real` | Real failure you hit doing actual work |
| `controlled_real` | Real failure in a controlled/fixture run |
| `invocation_artifact` | Flaky env failure: timeout, network, disk |
| `test_first_contract` | TDD red-phase test (never `organic_real`) |
| `synthetic` | Fabricated scenario (never `organic_real`) |

### Step 4 — Repair-loop discipline (when you fix a real bug)

```bash
# Baseline (first failing run):
chimera-memory wrap \
  --failure-origin organic_real \
  --scope-path <scope> \
  --repair-loop-id fix-<slug>-<date> \
  --repair-phase baseline \
  -- <command>

# After fix — SAME command, SAME scope:
chimera-memory wrap \
  --failure-origin organic_real \
  --scope-path <scope> \
  --repair-loop-id fix-<slug>-<date> \
  --repair-phase same_scope_after_fix \
  -- <same command>
```

`same_scope_after_fix` → produces `fixed_same_scope` in preflight intelligence.
`regression_check` → produces `later_regression_validated` (broader, later run).

### Step 5 — End session and bundle

```bash
chimera-memory session end --status PASSED   # or FAILED

chimera-memory verify

chimera-memory receipt bundle \
  --output-dir ./receipts \
  --include-preflight \
  --scope-path <your-scope>
```

---

## Non-goals

- Do not reclassify `test_first_contract` failures as `organic_real`.
- Do not fabricate failures to improve M2B readiness.
- M2B BLOCKED in a fresh ledger is **expected** — not a failure.
- Do not debug GitHub Actions billing.
