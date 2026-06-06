# chimera-memory Preflight Intelligence (v0.6)

`chimera-memory preflight` now synthesizes actionable historical context from
the local ledger, answering: *"What has gone wrong in this scope before, was it
fixed, and what should I watch for?"*

---

## What it shows

### Known failures (`known_failures`)

Historical CONTRADICTED claims from matching scope paths, filtered to
`organic_real` and `controlled_real` origins (product defects). Each entry includes:

- `command` — the command that failed (redacted)
- `effective_failure_origin` — errata-corrected origin
- `repair_loop_id` — the repair loop this failure belongs to, if any
- `repair_status` — whether the failure was fixed, validated, classified, or open
- `lesson` — a conservative observed-pattern text
- `witness_excerpt` — bounded, redacted witness from failure output
- `scope_match_reason` — `exact`, `parent`, or `child`

### Repair-loop lessons (`repair_loop_lessons`)

Synthesis of repair loops with baseline failures and fix validations in the
matched scope. Status:

- `fixed` — baseline CONTRADICTED + same_scope_after_fix or regression_check VALIDATED
- `has_validations` — validated claims but no recorded baseline failure
- `open` — baseline failures with no fix validation yet

### Hygiene warnings (`hygiene_warnings`)

Recurring `invocation_artifact` patterns — shell quoting, missing tools,
wrong paths. Not product defects. Grouped by command family.

### Failure signatures (`failure_signatures`)

Stable fingerprints of recurring failures by `(command_family, scope, exit_code)`.

---

## What it does NOT show

- M2B scoring, model ranking, routing, statistical confidence
- `test_first_contract` failures (test fixtures, excluded by default)
- `synthetic` failures (excluded)
- `unknown` origin failures (legacy unlabeled)
- Failures from unrelated scopes

---

## Scope matching

Uses path-boundary matching, not naive string prefix.

| filter | claim | match | reason |
|---|---|---|---|
| `packages/chimera-memory` | `packages/chimera-memory` | ✅ | exact |
| `packages/chimera-memory` | `packages/chimera-memory/src` | ✅ | parent |
| `packages/chimera-memory/src` | `packages/chimera-memory` | ✅ | child |
| `packages/chimera-memory` | `packages/chimera-memory-types` | ❌ | no match |

---

## Repair status definitions

| Status | Meaning |
|---|---|
| `fixed_same_scope` | Failure in loop, followed by `same_scope_after_fix` VALIDATED |
| `later_regression_validated` | Failure in loop, followed by `regression_check` VALIDATED |
| `classified_errata` | Errata changed effective_failure_origin away from original |
| `open` | No fix validation found for this failure |

---

## Privacy / redaction

All command strings and witness excerpts are passed through the existing
`_redact()` helper before display or JSON output. Common secret patterns
(tokens, keys, credentials) are replaced with `[REDACTED:...]`.

---

## JSON contract (schema_version 2)

All v1 fields are preserved unchanged. New fields added:

```json
{
  "schema_version": 2,
  "known_failures": [...],
  "repair_loop_lessons": [...],
  "hygiene_warnings": [...],
  "failure_signatures": [...],
  "preflight_intelligence_note": "Historical failure context only..."
}
```

---

## Non-goals

- No M2B scoring or model ranking
- No routing or gating decisions
- No write-import
- No hosted/cloud sync
- No legacy backfill
- No dashboard
