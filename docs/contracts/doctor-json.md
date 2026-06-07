# Doctor JSON Contract

## Purpose

`chimera-memory doctor --json` emits a machine-readable health check for the local Chimera Memory store. Intended for CI scripts, tooling, and agents that need structured health data without parsing text.

## Schema version

`"schema_version": "1"` — stable from v0.8. This value will not change unless a breaking removal is made (which requires a major schema bump and deprecation notice).

## Stable fields

| Field | Type | Description |
|---|---|---|
| `schema_version` | `string` | Always `"1"` |
| `overall_status` | `string` | `"healthy"`, `"warnings"`, or `"critical"` |
| `exit_code` | `int` | `0` healthy, `1` warnings, `2` critical |
| `checks` | `array` | Per-check objects: `name`, `ok` (bool), `message` |
| `counts.unique_claims` | `int` | Total unique claims in ledger |
| `counts.settled_claims` | `int` | Settled (non-proposed) claims |
| `counts.organic_real_failures` | `int` | CONTRADICTED organic_real claims |
| `counts.failure_by_origin` | `object` | Failure count per failure_origin value |
| `counts.m2b_readiness_level` | `string` | M2B readiness string |
| `counts.m2b_blockers` | `array` | Blocker description strings |
| `warnings` | `array[string]` | Active warning descriptions |
| `critical` | `array[string]` | Active critical descriptions |
| `next_steps` | `array[string]` | Basic initialization next steps |
| `evidence_hygiene` | `object` | See sub-fields below (v0.8+) |
| `next_actions` | `array[string]` | Actionable remediation items (v0.8+) |

### `evidence_hygiene` sub-fields (v0.8+)

| Field | Type | Description |
|---|---|---|
| `total_claims` | `int` | Settled claims counted |
| `scoped_claim_count` | `int` | Claims with `scope_paths` set |
| `unscoped_claim_count` | `int` | Claims missing `scope_paths` |
| `scoped_claim_ratio` | `float` | `scoped / total`, 0.0–1.0 |
| `unknown_failure_origin_count` | `int` | Claims with missing/unknown `failure_origin` |
| `repair_phase_without_loop_count` | `int` | Claims with `repair_phase` but no `repair_loop_id` |
| `open_repair_loop_count` | `int` | Loops with baseline but no SSAF |
| `open_repair_loop_ids` | `array[string]` | IDs of open loops |
| `complete_repair_loop_count` | `int` | Loops with baseline + SSAF |
| `test_fixture_claim_count` | `int` | `test_first_contract` + `synthetic` claims |
| `invocation_artifact_count` | `int` | `invocation_artifact` claims |

## Additive-change policy

New keys may be added at any time. Consumers must tolerate unknown keys. Keys will not be removed or renamed without a schema_version bump and deprecation notice. The `evidence_hygiene` and `next_actions` keys were added in v0.8 and are stable.

## Example output (abbreviated)

```json
{
  "schema_version": "1",
  "overall_status": "warnings",
  "exit_code": 1,
  "checks": [
    {"name": "initialized", "ok": true, "message": "initialized"},
    {"name": "active_session", "ok": false, "message": "no active session"}
  ],
  "counts": {
    "unique_claims": 68,
    "settled_claims": 68,
    "organic_real_failures": 3,
    "m2b_readiness_level": "blocked"
  },
  "evidence_hygiene": {
    "total_claims": 68,
    "scoped_claim_count": 68,
    "unscoped_claim_count": 0,
    "scoped_claim_ratio": 1.0,
    "open_repair_loop_count": 1,
    "open_repair_loop_ids": ["v060-fixture-loop-2"]
  },
  "next_actions": [
    "Complete repair loop v060-fixture-loop-2 with --repair-phase same_scope_after_fix.\n  Run: chimera-memory repair-loops for the exact wrap command template."
  ]
}
```

## Non-goals

- Not M2B scoring
- Not model ranking
- Not routing or merge-gating
- Not a dashboard or time-series API
- `exit_code` reflects health status only — not a deployment gate
