# chimera-memory 0.10.0 Release Note

**Theme:** M2B Readiness Explain + Dependency Constraint Hygiene

**Release date:** 2026-06-07

---

## What changed

### `m2b-readiness --explain`

```bash
chimera-memory m2b-readiness --explain
chimera-memory m2b-readiness --explain --json
```

`--explain` appends a section showing exactly what evidence is missing and why:

```
Why readiness is blocked:

  organic_real_failed:
    current:   3
    required:  5
    remaining: 2

  comparable_groups:
    current:   1
    required:  2
    remaining: 1

How to build qualifying evidence honestly:
  - Use chimera-memory on real scoped work.
  - Record real failures honestly as organic_real.
  - Use same_scope_after_fix only after fixing a real defect.
  - Do not manufacture failures.
  - M2B readiness is a quality gate, not a deadline.
```

With `--explain --json`, an `"explain"` key is added additively. Without `--explain`, existing JSON is unchanged.

### Dependency constraint

`chimera-memory-types>=0.10.0,<1.0` — prevents stale companion package installs when both packages are released together.

### JSON contract doc

`docs/contracts/m2b-readiness-json.md` — stable fields, optional `explain` object, additive policy, non-goals.

### README

Added `m2b-readiness --explain` reference under M2B readiness section.

---

## Why it matters

Users and agents seeing "M2B BLOCKED" had no clear path forward. `--explain` shows the exact gap (`organic_real_failed: 3/5`, `comparable_groups: 1/2`) and states the only honest path: real work, real evidence, no shortcuts. This removes the pressure to game thresholds while giving a concrete answer to "what do I actually need to do?"

---

## What did not change

- No M2B scoring
- No model ranking
- No routing
- No write-import
- No hosted/cloud or dashboard
- No threshold weakening
- No storage migration
- No GitHub Actions work

---

## Verification

- pytest: 645/645 passing (13 new tests)
- Flake audit: prior timing flake in `test_storage_state_hardening.py` confirmed transient; 645/645 on two consecutive full-suite runs before release
- mypy: 0 errors (chimera-memory and chimera-memory-types)
- ruff: clean
- DQ wraps: 12/12 VALIDATED in feature pass; 13/13 VALIDATED in release closeout
- No `repair_loop_id` or `repair_phase` used in DQ sessions (clean validation sessions)

---

## Caveats

- GitHub Actions remains blocked by external account billing lock — not a release blocker
- M2B readiness: BLOCKED (organic_real_failed 3/5) — expected, not a release blocker
