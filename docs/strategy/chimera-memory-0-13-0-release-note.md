# chimera-memory 0.13.0 Release Note

**Theme:** Repair-loop JSON Contract Hardening

**Release date:** 2026-06-07

---

## What changed

- `repair-loops --json` loop objects now include explicit `status` field (`open`, `complete`, `malformed`)
- `repair-loops --json` loop objects now include `missing_phase` field (`same_scope_after_fix`, `baseline`, or `null`)
- Repair-loop JSON contract documentation updated with new fields
- JSON contract docs (repair-loops, doctor, preflight, m2b-readiness) now guarded by 21 tests

---

## Why it matters

- Downstream tools no longer need to infer loop state from array membership
- Agents can read `status` and `missing_phase` directly from JSON
- Contract docs are less likely to drift from CLI behavior undetected

---

## What did not change

- No runtime behavior changes beyond the additive JSON fields
- No M2B scoring
- No model ranking
- No routing
- No hosted/cloud
- No dashboard
- No write-import
- No GitHub Actions/billing work
- No threshold weakening

---

## M2B status

- Still BLOCKED
- No comparable-group advancement claimed
- No repair-loop evidence manufactured
