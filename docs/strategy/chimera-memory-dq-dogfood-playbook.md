# Chimera Memory DQ Dogfood Playbook

When running `chimera-memory wrap`, add data-quality flags to build labeled evidence
for future M2B reliability intelligence. This doc explains what to use and when.

---

## failure_origin — why could this claim fail?

| Value | When to use |
|---|---|
| `organic_real` | A genuine failure from real work — the code actually broke, the types are actually wrong |
| `synthetic` | An intentional test fixture (e.g. `python -c "raise SystemExit(7)"`) — failure is by design |
| `invocation_artifact` | Command typo, wrong args, missing tool — failure is not about the code quality |
| `controlled_real` | Intentional real failure created to serve as a baseline before a fix |
| `test_first_contract` | TDD — test written before the fix, expected to fail initially |
| `unresolved_downstream` | Failure caused by a broken upstream dependency, not the work being verified |
| `unknown` | You genuinely cannot classify it. Prefer other values if you can. |

**Rule:** Only use `organic_real` for genuine, unplanned failures from real work.
Never mark synthetic fixtures or intentional failures as `organic_real`.

---

## verification_scope — what does this command cover?

| Value | When to use |
|---|---|
| `focused_file` | A single file: `mypy src/chimera_memory/storage.py` |
| `focused_subdir` | A subdirectory: `ruff check packages/chimera-memory/src/chimera_memory/` |
| `package` | A full package: `pytest packages/chimera-memory/tests` |
| `workspace` | Multiple packages: `ruff check packages/` |
| `full_suite` | Everything: `pytest apps/ packages/` |
| `baseline_sweep` | A broad sweep to establish current state before changes |
| `repair_check` | Re-running the exact failing scope after a fix |
| `regression_check` | Broader check after a fix, verifying nothing else broke |
| `unknown` | Cannot classify. Prefer other values. |

---

## Repair loop linking

Use `--repair-loop-id` to link a baseline failure → fix attempt → verification
into a traceable group. Use `--repair-phase` to label each step.

| Phase | When to use |
|---|---|
| `baseline` | The initial run that reveals the failing state |
| `repair_attempt` | A fix attempt (may or may not pass) |
| `same_scope_after_fix` | Same command as baseline, run after fix — should now pass |
| `regression_check` | Broader verification after the fix |
| `none` | Not part of a repair loop |

Pick a stable, descriptive loop ID such as `chm-storage-fix-2026-06-05`.

---

## Recommended command patterns

### Clean passing verification (organic baseline)
```bash
chimera-memory wrap \
  --failure-origin organic_real \
  --verification-scope package \
  --scope-path packages/chimera-memory \
  --repair-loop-id chm-baseline-2026-06-05 \
  --repair-phase baseline \
  -- pytest packages/chimera-memory/tests -m "not slow"
```

### After fixing a bug (same scope, should now pass)
```bash
chimera-memory wrap \
  --failure-origin organic_real \
  --verification-scope package \
  --scope-path packages/chimera-memory \
  --repair-loop-id chm-storage-fix-2026-06-05 \
  --repair-phase same_scope_after_fix \
  -- pytest packages/chimera-memory/tests -m "not slow"
```

### Regression check (broader scope after fix)
```bash
chimera-memory wrap \
  --failure-origin organic_real \
  --verification-scope workspace \
  --repair-loop-id chm-storage-fix-2026-06-05 \
  --repair-phase regression_check \
  -- pytest packages/ -m "not slow"
```

### Synthetic fixture (intentional failure for testing the ledger)
```bash
chimera-memory wrap \
  --failure-origin synthetic \
  --verification-scope focused_file \
  -- python -c "raise SystemExit(7)"
```

---

## What NOT to do

- **Do not backfill labels onto old legacy claims.** The store is append-only.
- **Do not mark synthetic fixtures as `organic_real`.** Mislabeling poisons reliability rates.
- **Do not mark invocation/operator mistakes as `organic_real`.** Shell quoting errors, wrong paths, typos, and missing tools are `invocation_artifact` — not product defects.
- **Do not compare agents across different verification scopes.** Use filters to keep comparisons fair.
- **Do not treat M2B readiness as drift scoring.** `m2b-readiness` is a gate, not a ranking.
- **Do not share receipts containing raw secrets.** Witness output is redacted, but command args may contain tokens — use env vars instead.

---

## Correcting a misclassified claim (errata)

If a claim was recorded with the wrong `failure_origin`, use `chimera-memory errata add` to correct it for DQ readiness calculations. The original claim record is never modified.

```bash
# Example: pytest failed due to shell quoting — NOT a product defect
chimera-memory errata add <claim_id> \
  --failure-origin invocation_artifact \
  --reason "Shell quoting error: pytest -m \"not slow\" parsed incorrectly" \
  --note "Should have been labeled invocation_artifact at record time"

# Verify the correction
chimera-memory errata list
chimera-memory m2b-readiness  # organic_real_failed count will be corrected
```

Rules:
- Errata are stored in `.chimera-memory/errata.jsonl` (append-only, auditable)
- The original claim remains in `claims.jsonl` unchanged
- The corrected failure origin is used by `m2b-readiness` and organic-only filters
- The claim still appears in `chimera-memory failures` (it was CONTRADICTED)

---

## Classification cheat sheet

| Situation | failure_origin |
|---|---|
| Command correctly invoked, genuine code/test failure | `organic_real` |
| `python -c "raise SystemExit(7)"` intentional test fixture | `synthetic` |
| Shell quoting typo, wrong path, missing tool, bad flag | `invocation_artifact` |
| Test written before fix (TDD) — expected to fail | `test_first_contract` |
| Fix blocked by upstream breakage | `unresolved_downstream` |
| Intentional baseline before a fix | `controlled_real` |
| Intentional negative-path / error-message check (expected nonzero) | `controlled_real` |

**Negative-path verification rule:**

Commands intentionally run to verify error handling, missing-path messages, or expected CLI failures are `controlled_real` (or `test_first_contract`), not `organic_real`.

Examples that should be `controlled_real`:
```bash
chimera-memory evidence import /tmp/nonexistent --dry-run  # verifies missing-bundle error
chimera-memory preflight --failure-origin not_valid_enum   # verifies enum validation
chimera-memory session start <with missing args>           # verifies required-arg error
```

These should not count toward `organic_real_failed` unless the error itself reveals an unexpected product defect.

## Legacy unlabeled claims

Legacy claims (predating DQ metadata) are excluded from the DQ cohort readiness gate. They are not backfilled automatically.

**Rules:**
- Do not bulk-label legacy claims as `organic_real` or `package` — they were not created with DQ intent.
- Legacy claims remain visible in `all_ledger_summary` and `dq-summary`.
- `m2b-readiness` correctly counts them as `legacy_unlabeled` and excludes them from the DQ cohort.
- `effective_group_summaries` in `m2b-readiness --json` uses errata-corrected origins — test fixture groups show `organic_real=0`.

## M2B scoring policy

M2B scoring requires readiness to advance honestly:
- `organic_real_failed >= 5` from genuine repair cycles (not test fixtures)
- `comparable_groups >= 2` with `>= 10 organic_real` each

Do not build M2B scoring until readiness clears naturally. Do not manufacture failures.

## Errata policy

Errata are additive overlays over immutable raw claims. They never edit raw records.

Use errata to correct misclassification (e.g., `organic_real → test_first_contract`). Do not use errata to retroactively label legacy unlabeled claims as DQ-cohort evidence.

---

## Checking your data quality

```bash
# How labeled is your ledger?
chimera-memory m2b-readiness

# Organic-only reliability
chimera-memory reliability --organic-only --verification-scope package

# Repair loop summary
chimera-memory repair-loops

# DQ breakdown in status
chimera-memory status --json | python3 -c "import sys,json; print(json.load(sys.stdin)['data_quality'])"
```
