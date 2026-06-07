# chimera-memory 0.8.0 Release Note

**Theme:** Evidence Quality Guardrails + Doctor Intelligence

**Release date:** 2026-06-07

---

## What changed

### Doctor evidence hygiene (`chimera-memory doctor`)

Doctor now audits whether the Chimera Memory protocol was actually followed, not just whether the store is initialized. New "Evidence Hygiene" section covers:

- **Scoped claim ratio** — fraction of claims with `--scope-path` set
- **Unknown failure_origin count** — claims missing or mis-classified `failure_origin`
- **Repair phase without loop_id** — orphaned `--repair-phase` flags
- **Open repair loops** — loops with baseline contradiction but no `same_scope_after_fix`
- **Complete repair loops** — loops with `fixed_same_scope` evidence
- **Test/synthetic claim count** — correctly classified non-organic claims
- **Invocation artifact count** — environment flakes, separately visible

### Doctor next actions

When hygiene issues are detected, doctor prints actionable remediations:

```
Next actions:
  - Add --scope-path to future wrap commands.
  - Set --failure-origin on 2 claim(s) (run: chimera-memory agent-guide --agent generic).
  - Complete repair loop <id> with --repair-phase same_scope_after_fix.
```

### Doctor JSON (`chimera-memory doctor --json`)

Additive fields — all existing keys preserved:

```json
"evidence_hygiene": {
  "total_claims": ...,
  "scoped_claim_count": ...,
  "unscoped_claim_count": ...,
  "scoped_claim_ratio": ...,
  "unknown_failure_origin_count": ...,
  "repair_phase_without_loop_count": ...,
  "open_repair_loop_count": ...,
  "open_repair_loop_ids": [...],
  "complete_repair_loop_count": ...,
  "test_fixture_claim_count": ...,
  "invocation_artifact_count": ...
},
"next_actions": [...]
```

### Preflight empty-ledger guidance

When no historical failures are found for a scope, preflight now directs users to build evidence:

```
No historical failures for this scope yet.
To build preflight intelligence, run a scoped dogfood session:
  chimera-memory template dogfood --scope-path <scope>
```

Preflight JSON gains an additive field when empty: `"intelligence_note": "no_matching_scoped_claims"`.

### README

Added "Is my ledger healthy?" section pointing to `doctor` and `doctor --json`.

---

## Why it matters

v0.7 taught agents the correct session/wrap/repair-loop protocol. v0.8 measures whether that protocol was actually followed. A ledger with 200 claims, all unscoped and unclassified, previously showed "Status: healthy." That was a false signal. v0.8 fixes it.

This is the prerequisite for trustworthy M2B readiness data: clean evidence in, clean scoring out.

---

## What did not change

- No M2B scoring
- No model ranking
- No routing
- No write-import
- No hosted/cloud or dashboard
- No storage schema changes (`schema_version` remains 2)
- No ledger migration
- No GitHub Actions work

---

## Verification

- pytest: 611/611 passing (23 new tests for evidence hygiene)
- mypy: 0 errors (chimera-memory and chimera-memory-types)
- ruff: clean
- DQ wraps: 10/10 VALIDATED in feature pass; 13/13 VALIDATED in release closeout

---

## Caveats

- GitHub Actions remains blocked by external account billing lock — not a release blocker
- M2B readiness: BLOCKED (organic_real_failed 3/5) — expected, not a release blocker
- The dev ledger shows an open historical fixture loop (`v060-fixture-loop-2`) in `doctor` output — this is doctor hygiene correctly detecting real ledger state, not a package defect
