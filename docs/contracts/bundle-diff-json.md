# Bundle Diff JSON Contract

## Purpose

`chimera-memory bundle diff <old> <new> --json` emits a read-only comparison of two receipt or evidence bundles. Intended for agents and CI that need to understand what changed between bundle snapshots without importing or mutating ledger state.

## Schema version

`"schema_version": 1` — stable from v0.16. Integer.

## Stable fields

| Field | Type | Description |
|---|---|---|
| `schema_version` | `int` | Always `1` |
| `old_path` | `string` | Absolute path to old bundle |
| `new_path` | `string` | Absolute path to new bundle |
| `old_bundle_type` | `string` | `receipt`, `evidence`, or `unknown` |
| `new_bundle_type` | `string` | `receipt`, `evidence`, or `unknown` |
| `status` | `string` | `OK`, `WARNING`, `INCOMPATIBLE`, or `UNKNOWN` |
| `compatible` | `bool` | Whether bundles are comparable |
| `file_delta` | `object` | `{added, removed, common}` arrays |
| `claim_count_delta` | `int\|null` | Change in claim count (null if unavailable) |
| `failure_count_delta` | `int\|null` | Change in failure count (null if unavailable) |
| `evidence_event_count_delta` | `int\|null` | Change in evidence events (null if unavailable) |
| `integrity_status_change` | `string\|null` | e.g. `"OK → BROKEN"` or null |
| `notes` | `array[string]` | Informational notes |
| `warnings` | `array[string]` | Issues to review |
| `next_actions` | `array[string]` | Recommended actions |

## Status model

| Status | Condition |
|---|---|
| `OK` | Same type, comparable, no concerning changes |
| `WARNING` | Comparable but failures increased or integrity changed |
| `INCOMPATIBLE` | Different bundle types |
| `UNKNOWN` | One or both bundles cannot be classified |

## Additive-change policy

New fields may be added. Consumers must tolerate unknown keys. `schema_version` increments only on breaking removals or renames.

## Non-goals

- Not import
- Not write
- Not proof of authenticity
- Not semantic claim matching
- Not hosted/cloud
- Not M2B scoring
