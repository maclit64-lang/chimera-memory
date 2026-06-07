# M2B Readiness JSON Contract

## Purpose

`chimera-memory m2b-readiness --json` emits a structured evidence readiness gate evaluation. Intended for CI scripts and tooling that need to programmatically check readiness status. **This is a readiness gate, not M2B drift scoring.**

## Schema version

`"schema_version": 2` — stable from v0.8. Integer.

## Stable fields

| Field | Type | Description |
|---|---|---|
| `schema_version` | `int` | Always `2` |
| `readiness_level` | `string` | `"blocked"`, `"weak"`, or `"review_ready"` |
| `m2b_ready` | `bool` | `true` only when all gates pass |
| `blockers` | `array[string]` | Reasons readiness is blocked |
| `warnings` | `array[string]` | Non-blocking concerns |
| `thresholds` | `object` | Gate threshold values |
| `thresholds.organic_failures_min` | `int` | Required CONTRADICTED organic_real claims (default: 5) |
| `thresholds.comparable_groups_min` | `int` | Required comparable groups ≥10 organic_real (default: 2) |
| `dq_cohort_summary` | `object` | DQ-cohort evidence summary |
| `dq_cohort_summary.organic_real_failed` | `int` | CONTRADICTED organic_real claims |
| `dq_cohort_summary.comparable_groups` | `int` | Groups with ≥10 organic_real claims |
| `dq_cohort_summary.organic_real` | `int` | Total organic_real claims |
| `evaluation_mode` | `string` | `"dq_cohort"`, `"all_ledger"`, or `"default"` |
| `effective_group_summaries` | `array` | Per-group claim summaries (errata-corrected) |
| `repair_loop_summary` | `object` | Loop counts and IDs |

## Optional `explain` field (v0.10+, only with `--explain`)

When `--explain` is passed, the JSON output gains an additional `explain` object:

```json
"explain": {
  "organic_real_failed_current": 3,
  "organic_real_failed_threshold": 5,
  "organic_real_failed_remaining": 2,
  "comparable_groups_current": 1,
  "comparable_groups_threshold": 2,
  "comparable_groups_remaining": 1,
  "total_organic_real_claims": 103,
  "advice": [
    "Use chimera-memory on real scoped work.",
    "Record real failures honestly as organic_real.",
    "Use same_scope_after_fix only after fixing a real defect.",
    "Do not manufacture failures."
  ]
}
```

Without `--explain`, this key is absent. Existing consumers must not rely on its absence or presence.

## Additive-change policy

New keys may be added at any time. Consumers must tolerate unknown keys. `schema_version` will increment only on breaking removals or renames.

## Example without `--explain` (abbreviated)

```json
{
  "schema_version": 2,
  "readiness_level": "blocked",
  "m2b_ready": false,
  "blockers": [
    "organic_real failures too few: 3 < 5",
    "comparable groups too few: 1 < 2 (need >= 10 organic_real per group)"
  ],
  "thresholds": {
    "organic_failures_min": 5,
    "comparable_groups_min": 2
  },
  "dq_cohort_summary": {
    "organic_real": 103,
    "organic_real_failed": 3,
    "comparable_groups": 1
  }
}
```

## Example with `--explain` (additional key only)

```json
{
  "...existing fields unchanged...",
  "explain": {
    "organic_real_failed_current": 3,
    "organic_real_failed_threshold": 5,
    "organic_real_failed_remaining": 2,
    "comparable_groups_current": 1,
    "comparable_groups_threshold": 2,
    "comparable_groups_remaining": 1,
    "total_organic_real_claims": 103,
    "advice": ["...", "..."]
  }
}
```

## Non-goals

- Not M2B scoring
- Not model ranking
- Not routing
- Not an autonomy gate
- Not statistical proof of reliability
- `m2b_ready: true` means the evidence gate is cleared, not that the model is validated
- `readiness_level` is a heuristic classification, not a scientific measurement
