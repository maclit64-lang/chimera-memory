# Generic Agent — Chimera Memory Dogfood Prompt

Use this prompt to onboard any coding agent with correct Chimera Memory discipline.

## Quick reference

```bash
chimera-memory agent-guide --agent generic
chimera-memory template dogfood --scope-path <your-package>
```

---

## Prompt (paste at session start)

You are using Chimera Memory to record reliability evidence for this task.

**Required sequence. Do not skip steps.**

### 1. Preflight

```bash
chimera-memory preflight --scope-path <scope>
```

Advisory only. Always safe to run. Proceed regardless of output.

### 2. Start session

```bash
chimera-memory session start \
  --branch <branch> \
  --task-label "<task description>" \
  --agent <your-agent-label> \
  --model <your-model> \
  --harness-id <your-harness>
```

### 3. Wrap verification commands

```bash
chimera-memory wrap \
  --failure-origin <origin> \
  --scope-path <scope> \
  --verification-scope package \
  -- <command>
```

**Classification rules — choose exactly one `--failure-origin`:**

- `organic_real` — real failure encountered during actual work
- `controlled_real` — real failure in a deliberately controlled run
- `invocation_artifact` — environment/infra flake (not a code bug)
- `test_first_contract` — TDD test written before implementation; **not** `organic_real`
- `synthetic` — fabricated/scaffolded scenario; **not** `organic_real`

### 4. Fix a real bug? Use repair-loop flags

```bash
# First failing run:
chimera-memory wrap \
  --failure-origin organic_real \
  --scope-path <scope> \
  --repair-loop-id <stable-slug> \
  --repair-phase baseline \
  -- <command>

# After fix, rerun same command same scope:
chimera-memory wrap \
  --failure-origin organic_real \
  --scope-path <scope> \
  --repair-loop-id <same-slug> \
  --repair-phase same_scope_after_fix \
  -- <same command>
```

### 5. Close out

```bash
chimera-memory session end --status PASSED   # or FAILED
chimera-memory verify
chimera-memory receipt bundle \
  --output-dir ./receipts \
  --include-preflight \
  --scope-path <scope>
```

---

## Rules

- `--scope-path` is required on every wrap
- `--failure-origin` is required on every wrap
- Never label `test_first_contract` or `synthetic` as `organic_real`
- M2B BLOCKED in a fresh ledger is expected — do not reclassify to unblock it
- `same_scope_after_fix` → `fixed_same_scope` in preflight
- `regression_check` → `later_regression_validated` (not `fixed_same_scope`)
