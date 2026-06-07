# Repair Loops JSON Contract

## Purpose

`chimera-memory repair-loops --json` emits a structured audit of all repair loops in the local ledger, classified into open, complete, and malformed categories. Intended for agents and CI tooling that need to programmatically identify incomplete repair loops and retrieve exact remediation command templates.

## Schema version

`"schema_version": 1` — stable from v0.9. Integer.

## Classification rules

| Category | Criteria |
|---|---|
| `complete` | Has at least one CONTRADICTED `baseline`/`repair_attempt` claim AND at least one VALIDATED `same_scope_after_fix` claim with the same `repair_loop_id` |
| `open` | Has CONTRADICTED `baseline`/`repair_attempt` but no VALIDATED `same_scope_after_fix` |
| `malformed` | Has VALIDATED `same_scope_after_fix` but no CONTRADICTED baseline, or loop has only VALIDATED claims |

**`regression_check` does NOT make a loop complete.** Only `same_scope_after_fix` closes a repair loop as `fixed_same_scope`.

## Stable fields

| Field | Type | Description |
|---|---|---|
| `schema_version` | `int` | Always `1` |
| `open_loops` | `array` | Open loop objects |
| `complete_loops` | `array` | Complete loop objects |
| `malformed_loops` | `array` | Malformed loop objects |
| `next_actions` | `array[string]` | Per-open-loop remediation strings |

### Loop object fields

| Field | Type | Present in |
|---|---|---|
| `repair_loop_id` | `string` | all |
| `scope_paths` | `array[string]` | all (may be empty) |
| `baseline_count` | `int` | all |
| `same_scope_after_fix_count` | `int` | all |
| `regression_check_count` | `int` | all |
| `status` | `string` | all (`"open"`, `"complete"`, or `"malformed"`) |
| `missing_phase` | `string\|null` | all (`"same_scope_after_fix"` for open, `"baseline"` for malformed, `null` for complete) |
| `next_action` | `string\|null` | open only (null for complete/malformed) |
| `reason` | `string\|null` | malformed only |

## Additive-change policy

New fields may be added to loop objects at any time. Consumers must tolerate unknown keys. `schema_version` will increment only on breaking removals or renames.

## Example output

```json
{
  "schema_version": 1,
  "open_loops": [
    {
      "repair_loop_id": "v060-fixture-loop-2",
      "scope_paths": ["packages/chimera-memory"],
      "baseline_count": 1,
      "same_scope_after_fix_count": 0,
      "regression_check_count": 0,
      "status": "open",
      "missing_phase": "same_scope_after_fix",
      "next_action": "chimera-memory wrap \\\n    --failure-origin organic_real \\\n    --scope-path packages/chimera-memory \\\n    --verification-scope package \\\n    --repair-loop-id v060-fixture-loop-2 \\\n    --repair-phase same_scope_after_fix \\\n    -- <same check that failed>"
    }
  ],
  "complete_loops": [
    {
      "repair_loop_id": "v070-agent-onboarding-2026-06",
      "scope_paths": ["packages/chimera-memory"],
      "baseline_count": 1,
      "same_scope_after_fix_count": 1,
      "regression_check_count": 3,
      "status": "complete",
      "missing_phase": null,
      "next_action": null
    }
  ],
  "malformed_loops": [],
  "next_actions": [
    "Complete repair loop v060-fixture-loop-2 (scope: packages/chimera-memory) with --repair-phase same_scope_after_fix.\n  Run: chimera-memory repair-loops for the exact wrap command template."
  ]
}
```

## Non-goals

- Not M2B scoring
- Not model ranking
- Not routing
- Not a merge gate
- Not a reliability dashboard
- `complete` means the repair-loop evidence is present — not that the underlying bug is certified fixed
