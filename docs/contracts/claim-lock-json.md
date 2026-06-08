# Claim-Lock JSON Contract

## Purpose

A *claim lock* is a sealed, scope-bound prediction recorded **before** an agent
edits code. `chimera-memory claim lock` writes a `LOCKED` record;
`chimera-memory claim settle <claim_id>` appends an updated record carrying the
settlement result. Records live append-only in
`.chimera-memory/claim_locks.jsonl`; the latest record for a `claim_id` is
authoritative.

This contract produces **settled evidence, not proof of correctness**. Scope
coverage is path-based ("covered by declared claim scope"), never "guaranteed
tested".

## Schema version

`"schema_version": 1` — stable from v0.22. Integer. Additive evolution only.

## Top-level fields

| Field | Type | Description |
|---|---|---|
| `schema_version` | `int` | Always `1` |
| `record_type` | `string` | Always `"claim_lock"` |
| `claim_id` | `string` | Stable id, prefix `clm_` |
| `created_at` | `string` | ISO-8601 UTC timestamp |
| `intent` | `string` | What the author intends to do |
| `scope_path` | `string` | Declared scope (forward-slash, no trailing slash; `.` = repo root) |
| `predicted_outcome` | `string` | e.g. `"all pass"` |
| `falsifiers` | `array[{command: string[]}]` | Pre-committed checks that would disprove the claim |
| `must_not_break` | `array[{command: string[]}]` | Pre-committed checks that must keep passing |
| `pre_edit_state` | `object` | Git state at lock time |
| `seal` | `object` | Tamper-evident seal of the sealed payload |
| `attribution` | `object` | Multi-terminal attribution seam |
| `quality` | `object` | Claim-quality band + warnings |
| `settlement` | `object` | Settlement result |

### `pre_edit_state`

| Field | Type | Description |
|---|---|---|
| `git_head` | `string \| null` | HEAD SHA at lock time, or `null` if git unavailable |
| `tracked_dirty_files` | `array[string]` | Tracked files dirty at lock time |
| `dirty_state` | `string` | `clean`, `dirty`, or `unknown` |

### `seal`

| Field | Type | Description |
|---|---|---|
| `payload_hash` | `string` | sha256 over the canonical sealed payload (intent, scope_path, predicted_outcome, falsifiers, must_not_break). Stable for identical payloads |
| `sealed_at` | `string` | ISO-8601 UTC |
| `seal_version` | `int` | Always `1` |

### `attribution`

Multi-terminal readiness seam. Unknown values are recorded honestly as `null`
or `"unknown"`; attribution is never fabricated.

| Field | Type |
|---|---|
| `session_id` | `string \| null` |
| `terminal_id` | `string \| null` |
| `worktree_path` | `string` |
| `branch` | `string \| null` |
| `agent_name` | `string \| null` |
| `model_name` | `string \| null` |
| `harness_id` | `string \| null` |
| `attribution_confidence` | `string` (`session`, `env`, or `unknown`) |

### `quality`

| Field | Type | Description |
|---|---|---|
| `claim_quality` | `string` | `strong`, `medium`, `weak`, or `unknown` |
| `warnings` | `array[string]` | e.g. `WEAK_FALSIFIER`, `DIRTY_PRE_EDIT_STATE`, `NO_GIT_PRE_EDIT_STATE` |

### `settlement`

| Field | Type | Description |
|---|---|---|
| `status` | `string` | `LOCKED`, `VALIDATED`, `CONTRADICTED`, `UNSETTLED`, or `SCOPE_DRIFT` |
| `settled_at` | `string \| null` | ISO-8601 UTC, `null` before settlement |
| `commands` | `array[object]` | Per-check result: `command`, `role`, `outcome` (`PASS`/`FAIL`/`UNRUNNABLE`), `exit_code`, excerpts |
| `changed_files` | `array[string]` | Files changed since `pre_edit_state.git_head` (ledger files excluded) |
| `evidence_dark_files` | `array[string]` | Reserved; populated by the Merge X-Ray aggregate |
| `scope_drift_files` | `array[string]` | Changed files outside the declared scope |

## Status model

| Status | Meaning |
|---|---|
| `LOCKED` | Claim sealed, not yet settled |
| `VALIDATED` | All sealed falsifier + must-not-break checks passed, no scope drift |
| `CONTRADICTED` | One or more sealed checks failed |
| `UNSETTLED` | A sealed command could not be run, or no falsifier was declared |
| `SCOPE_DRIFT` | Checks passed, but changed files fall outside the declared scope |

Status precedence: `CONTRADICTED` > `UNSETTLED` > `SCOPE_DRIFT` > `VALIDATED`.

## Auto-lock (v0.23)

`claim lock --auto` builds a claim spec from env vars / flags without a
`claim.toml` file. The JSON response includes additional fields:

| Field | Description |
|---|---|
| `auto_lock` | `true` when claim was created via `--auto` |
| `generated_spec` | The generated claim spec as an object |
| `validation` | `{errors, warnings}` from pre-lock validation |

For `--dry-run`, `claim_id` is `null` and `status` is `"DRY_RUN"`.

## Dry-run validation
without writing anything. The result schema is::

    {"valid": bool, "errors": list[str], "warnings": list[str]}

Hard errors block locking. Warnings are stored on the locked claim and do not
block locking.

## Warning codes

| Code | Condition |
|---|---|
| `BROAD_COMMAND` | A command has no explicit target/path (e.g. bare `mypy`, `ruff check`, `pytest`) |
| `MISSING_MUST_NOT_BREAK` | No must_not_break checks declared |
| `BROAD_SCOPE_PATH` | scope_path is `.` (covers entire repo) |
| `DIRTY_PRE_EDIT_STATE` | Working tree was dirty when the claim was locked |
| `NO_GIT_PRE_EDIT_STATE` | git was not available at lock time |
| `WEAK_FALSIFIER` | Falsifier command is a no-op (e.g. `true`, `echo`) |



- Commands are always `list[str]` executed with `shell=False`.
- A shell-string command is rejected; the explicit list form is required.
- The `.chimera-memory/` ledger directory is never part of `changed_files`.
- Command output excerpts are redacted for secrets before storage.

## Non-claims

This contract does not provide semantic proof of correctness, security
guarantees, model ranking, model routing, or M2B readiness. Settlement runs
only the pre-committed checks — it can never substitute a different check.

## Example

```json
{
  "schema_version": 1,
  "record_type": "claim_lock",
  "claim_id": "clm_feaf0125d1784a64",
  "created_at": "2026-06-08T09:00:00+00:00",
  "intent": "fix checkout null dereference",
  "scope_path": "packages/cart",
  "predicted_outcome": "all pass",
  "falsifiers": [
    {"command": ["pytest", "tests/test_checkout.py::test_empty_cart"]}
  ],
  "must_not_break": [
    {"command": ["pytest", "tests/test_cart.py"]}
  ],
  "pre_edit_state": {
    "git_head": "abc1234",
    "tracked_dirty_files": [],
    "dirty_state": "clean"
  },
  "seal": {
    "payload_hash": "…",
    "sealed_at": "2026-06-08T09:00:00+00:00",
    "seal_version": 1
  },
  "attribution": {
    "session_id": null,
    "terminal_id": null,
    "worktree_path": "/repo",
    "branch": "feat/cart-fix",
    "agent_name": null,
    "model_name": null,
    "harness_id": null,
    "attribution_confidence": "unknown"
  },
  "quality": {"claim_quality": "strong", "warnings": []},
  "settlement": {
    "status": "VALIDATED",
    "settled_at": "2026-06-08T09:10:00+00:00",
    "commands": [
      {"command": ["pytest", "tests/test_checkout.py::test_empty_cart"],
       "role": "falsifier", "outcome": "PASS", "exit_code": 0}
    ],
    "changed_files": ["packages/cart/checkout.py"],
    "evidence_dark_files": [],
    "scope_drift_files": []
  }
}
```
