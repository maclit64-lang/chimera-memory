# Preflight JSON Contract

## Purpose

`chimera-memory preflight --json` emits a machine-readable advisory report of historical failure context for a scope. Intended for agents and tooling that need structured preflight data. **Advisory only — not a routing or merge-gate decision.**

## Schema version

`"schema_version": 2` — stable from v0.6. Integer, not string.

## Stable fields

| Field | Type | Description |
|---|---|---|
| `schema_version` | `int` | Always `2` |
| `source` | `string` | `explicit_scope`, `git_changes`, `mixed`, or `none` |
| `matching_claim_count` | `int` | Claims matching the scope filter |
| `m2b_readiness_level` | `string` | M2B readiness level string |
| `recent_failures` | `array` | Recent CONTRADICTED claims for scope |
| `repair_loops` | `array` | Repair loop summaries for scope |
| `recommended_checks` | `array[string]` | Suggested verification commands |
| `dq_caveats` | `array[string]` | Data quality caveats |
| `known_failures` | `array` | Historical failure objects (v0.6+) |
| `repair_loop_lessons` | `array` | Lessons from completed repair loops (v0.6+) |
| `hygiene_warnings` | `array` | Invocation artifact warnings (v0.6+) |
| `failure_signatures` | `array` | Recurring failure pattern summaries (v0.6+) |
| `preflight_intelligence_note` | `string` | Advisory disclaimer text |
| `intelligence_note` | `string` | Present when no scope matches: `"no_matching_scoped_claims"` (v0.8+) |
| `open_repair_loops_for_scope` | `array[string]` | Open loop IDs matching this scope (v0.9+) |

### `known_failures` object fields

| Field | Type | Description |
|---|---|---|
| `command` | `string` | Command that failed |
| `failure_origin` | `string` | Effective failure origin |
| `repair_loop_id` | `string\|null` | Associated repair loop ID |
| `repair_status` | `string` | `open`, `fixed_same_scope`, `later_regression_validated`, `classified_errata` |
| `lesson` | `string` | Human-readable lesson text |

## Additive-change policy

New keys may be added at any time. `schema_version` will increment only on breaking changes. Fields added in v0.8 (`intelligence_note`) and v0.9 (`open_repair_loops_for_scope`) are additive and may be absent in older ledgers.

## Example output (abbreviated)

```json
{
  "schema_version": 2,
  "source": "explicit_scope",
  "matching_claim_count": 12,
  "m2b_readiness_level": "blocked",
  "known_failures": [
    {
      "command": "pytest packages/chimera-memory/tests",
      "failure_origin": "organic_real",
      "repair_loop_id": "fix-scope-match-2026-05",
      "repair_status": "fixed_same_scope",
      "lesson": "Fixed scope match path boundary bug."
    }
  ],
  "open_repair_loops_for_scope": ["v060-fixture-loop-2"],
  "preflight_intelligence_note": "Historical failure context only. Not M2B scoring, model ranking, routing, or statistical proof."
}
```

## Non-goals

- Not M2B scoring
- Not model ranking
- Not routing
- Not a merge gate
- Not statistical proof of reliability
- `repair_status: fixed_same_scope` is evidence, not certification
