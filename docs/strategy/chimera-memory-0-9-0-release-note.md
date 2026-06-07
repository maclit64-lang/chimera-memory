# chimera-memory 0.9.0 Release Note

**Theme:** Repair Loop Guidance + JSON Contract Hardening

**Release date:** 2026-06-07

---

## What changed

### Repair-loops command hardened

`chimera-memory repair-loops` now classifies all repair loops into three sections:

**Open** — has a CONTRADICTED baseline but no VALIDATED `same_scope_after_fix`. Each open loop includes an exact `to close:` command template.

**Complete** — has CONTRADICTED baseline AND VALIDATED `same_scope_after_fix`. Shows `fixed_same_scope ✓`.

**Malformed** — has `same_scope_after_fix` but no baseline contradiction (or only VALIDATED claims with no phase linkage).

Key rule enforced: `regression_check` does NOT close a repair loop. Only `same_scope_after_fix` produces `fixed_same_scope`.

### Repair-loops JSON contract (`--json`)

```json
{
  "schema_version": 1,
  "open_loops": [...],
  "complete_loops": [...],
  "malformed_loops": [],
  "next_actions": [...]
}
```

Stable from v0.9. `schema_version: 1` is an integer.

### Doctor next_actions improvement

Open loop next actions now include a pointer:

```
Complete repair loop <id> (scope: <scope>) with --repair-phase same_scope_after_fix.
Run: chimera-memory repair-loops for the exact wrap command template.
```

### Preflight open-loop context

`chimera-memory preflight --scope-path <scope>` now shows open repair loops for matching scopes using path-boundary matching. Additive JSON field: `open_repair_loops_for_scope`.

### Agent-guide phase semantics upgrade

`chimera-memory agent-guide` now includes an explicit 5-phase table with critical rules:

- `same_scope_after_fix` closes the loop as `fixed_same_scope`
- `regression_check` does NOT close the loop; produces `later_regression_validated`
- Warning: do not manufacture baseline failures to satisfy M2B

### Template dogfood repair-loop scaffold

`chimera-memory template dogfood` now includes a commented real-bug repair-loop pattern showing the baseline → fix → same_scope_after_fix sequence. Explicitly notes that `regression_check` does not close the loop.

### JSON contract docs

Three new docs covering stable JSON output contracts:

- `docs/contracts/doctor-json.md`
- `docs/contracts/preflight-json.md`
- `docs/contracts/repair-loops-json.md`

Each covers: purpose, schema_version, stable fields, additive-change policy, example output, and non-goals.

---

## Why it matters

v0.8 could detect open repair loops. v0.9 gives users the exact command to close them. The path from `organic_real_failed 3/5` to `5/5` requires completing real repair loops honestly — this release removes the guidance gap that was leaving loops open indefinitely.

---

## What did not change

- No M2B scoring
- No model ranking
- No routing
- No write-import
- No hosted/cloud or dashboard
- No storage schema changes (`schema_version` remains 2 for preflight)
- No ledger migration
- No GitHub Actions work

---

## Verification

- pytest: 633/633 passing (29 new tests: 22 in `test_repair_loops_guidance.py` + 7 expanded existing)
- mypy: 0 errors (chimera-memory and chimera-memory-types)
- ruff: clean
- DQ wraps: 13/13 VALIDATED in feature pass; 14/14 VALIDATED in release closeout
- No `repair_loop_id` or `repair_phase` used in DQ sessions (clean validation sessions)

---

## Caveats

- GitHub Actions remains blocked by external account billing lock — not a release blocker
- M2B readiness: BLOCKED (organic_real_failed 3/5) — expected, not a release blocker
- Dev ledger shows one open fixture loop (`v060-fixture-loop-2`) — doctor and repair-loops guidance working correctly, not a package defect
