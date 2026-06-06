# chimera-memory 0.5.0 — Release Note

**Released:** 2026-06-06
**Theme:** M2B Readiness Transparency + DQ Summary
**Status:** RC complete — pending token + explicit operator approval

---

## Packages

| Package | Version |
|---|---|
| `chimera-memory` | 0.5.0 |
| `chimera-memory-types` | 0.5.0 |

## Changes from 0.4.0

### M2B readiness JSON/text parity

- `dq_cohort_summary` now includes `comparable_groups`, `legacy_excluded_from_dq`,
  and `legacy_exclusion_reason` — text and JSON fully agree
- `group_summaries` renamed to `effective_group_summaries` in JSON output
- `effective_group_summaries` uses errata-corrected `failure_origin` — test fixture
  groups (e.g. `agent=test`) show `organic_real=0, organic_failed=0`
- `group_summaries_note` added explaining errata-correction
- Text output unchanged

### Group summary transparency

Before: raw `group_summaries` used pre-errata `failure_origin` from metadata.
Test fixture claims marked `organic_real` in raw metadata appeared as organic groups.

After: `effective_group_summaries` applies errata map. Test fixture claims corrected
to `test_first_contract` show `organic_real=0`. Comparable group count unaffected (still 2).

### `chimera-memory dq-summary`

New read-only command showing:
- Total claims / legacy unlabeled count
- Errata applied count
- Effective failure_origin counts (errata-corrected)
- Verification scope counts
- Repair phase counts
- Legacy exclusion reason

### Doctor M2B blockers

`chimera-memory doctor` now shows M2B blockers inline:
```
✓ M2B readiness: blocked
  ↳ organic_real failures too few: 3 < 5
```
`doctor --json` includes `m2b_blockers` list.

### DQ playbook update

Added explicit rules:
- Legacy claims not backfilled
- M2B scoring requires honest readiness
- Errata are additive overlays only
- `effective_group_summaries` uses errata-corrected origins

## What is not built

- M2B scoring: not built
- `chimera-memory score`: does not exist
- `chimera-memory migrate-labels`: does not exist
- Legacy backfill: not done
- Model routing: not built
- Hosted/cloud sync: not built
- Evidence write-import: dry-run only
- Dashboard: not built

## Verification summary

| Check | Result |
|---|---|
| `pytest` (546+/546+) | ✅ |
| `mypy` memory + types | ✅ 0 errors |
| `ruff check` | ✅ clean |
| `chimera-memory --version` | ✅ `chimera-memory 0.5.0` (from wheel) |
| `dq-summary` | ✅ |
| `m2b-readiness` | ✅ effective groups correct |
| `doctor` shows blockers | ✅ |
| `verify` | ✅ 0 broken |

## M2B readiness state

```
readiness_level: blocked
organic_real_failed: 3/5
effective_group_summaries: buffy=2/19, kiro=1/193, test=0/0 (fixture excluded)
```

Not a release blocker.
