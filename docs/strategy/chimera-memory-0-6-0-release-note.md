# chimera-memory 0.6.0 — Release Note

**Released:** 2026-06-06
**Theme:** Preflight Intelligence / Known Failure Retrieval
**Status:** RC complete — pending token + explicit operator approval to publish

---

## Packages

| Package | Version |
|---|---|
| `chimera-memory` | 0.6.0 |
| `chimera-memory-types` | 0.6.0 |

## What changed

### Preflight Intelligence (`preflight` schema_version 2)

`chimera-memory preflight` now synthesizes actionable historical context from
the local ledger before starting work.

**New typed structures:**
- `KnownFailure` — historical organic_real/controlled_real failures with lesson,
  repair status, redacted witness, and scope match reason
- `RepairLoopLesson` — synthesized lesson from loops with baseline + fix validation
- `HygieneWarning` — recurring invocation_artifact patterns, clearly separated
  from product defects
- `FailureSignature` — stable fingerprint by command family, scope, exit code

**New JSON fields** (all additive, v1 fields unchanged):
```json
"schema_version": 2,
"known_failures": [...],
"repair_loop_lessons": [...],
"hygiene_warnings": [...],
"failure_signatures": [...],
"preflight_intelligence_note": "Historical failure context only..."
```

**Scope matching:** Path-boundary matching replaces naive `startswith`.
`packages/chimera-memory` no longer false-matches `packages/chimera-memory-types`.

**Origin filtering:**
- `organic_real` + `controlled_real` → known_failures
- `invocation_artifact` → hygiene_warnings
- `test_first_contract`, `synthetic`, `unknown` → excluded from both

**Repair status:**
- `fixed_same_scope` — baseline CONTRADICTED + same_scope_after_fix VALIDATED
- `later_regression_validated` — baseline + regression_check VALIDATED
- `classified_errata` — errata changed effective origin
- `open` — no fix validation found

**`recent_failures` hardened:** excludes `test_first_contract` and `synthetic`
(consistent with `known_failures`).

**README:** Added Preflight Intelligence section with usage example.

## What did not change

- Storage format: unchanged
- M2B scoring: not built
- Model ranking: not built
- Routing: not built
- Hosted/cloud: not built
- Evidence write-import: dry-run only
- Dashboard: not built

## Verification

| Check | Result |
|---|---|
| `pytest` (569/569) | ✅ |
| `mypy` memory + types | ✅ 0 errors |
| `ruff check` | ✅ clean |
| `chimera-memory --version` | ✅ `chimera-memory 0.6.0` (from wheel) |
| `preflight --json schema_version` | ✅ 2 |
| Realistic fixture ledger validation | ✅ known_failures=4, lessons=3, hygiene=1 |
| DQ wraps 8/8 VALIDATED | ✅ |
| `verify` 0 broken | ✅ |
| Local fresh-venv smoke | ✅ |

## Caveats

- **GitHub Actions:** blocked by external GitHub account billing lock.
  CI validation is not a release blocker — package is validated locally.
- **M2B readiness:** BLOCKED (organic_real_failed 3/5). Not a release blocker.
  Standalone ledger starts fresh; intelligence fills as wrapped sessions accumulate.
