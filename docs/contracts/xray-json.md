# Merge X-Ray JSON Contract

## Purpose

`chimera-memory xray generate --json` emits the structured Merge X-Ray for the
current change set. The Markdown form (`PR_EVIDENCE.md`) is rendered from the
same structure. Intended for reviewers, agents, and future CI/PR integrations
that need a machine-readable view of which changed files carry settled claim
evidence.

This report shows **settled evidence, not proof of correctness**.

## Schema version

`"schema_version": 1` — stable from v0.22. Integer. Additive evolution only.

## Change-set resolution

| Invocation | `diff.mode` | Change set |
|---|---|---|
| `xray generate` | `working_tree` | Working-tree changes vs `HEAD` (+ untracked) |
| `xray generate --base main --head HEAD` | `range` | `git diff --name-only main HEAD` |

The `.chimera-memory/` ledger directory is always excluded from the change set.

## Top-level fields

| Field | Type | Description |
|---|---|---|
| `schema_version` | `int` | Always `1` |
| `generated_at` | `string` | ISO-8601 UTC |
| `mode` | `string` | `claim_locked` or `post_hoc` (no pre-edit claims existed) |
| `diff` | `object` | `{mode, base, head}` |
| `working_tree_warning` | `string \| null` | Warning message when working-tree mode may include build/cache artefacts. `null` in commit-range mode |
| `verdict` | `string` | One-line reviewer verdict |
| `changed_files` | `array[string]` | All changed files in scope of this X-Ray |
| `settled_claims` | `array[object]` | Per-claim view (see below) |
| `evidence_dark_files` | `array[string]` | Changed files with no settled claim coverage (all, for backward compat) |
| `evidence_dark_classified` | `object` | Same files split into `source_files` and `likely_cache_or_build` |
| `weakly_covered_files` | `array[string]` | Changed files touched only by CONTRADICTED/UNSETTLED claims |
| `scope_drift_files` | `array[string]` | Changed files outside any declared claim scope |
| `reviewer_focus` | `array[string]` | Ordered manual-review guidance |
| `counts` | `object` | Aggregate counts (see below) |
| `caveat` | `string` | Always the non-claims caveat |

### `settled_claims[]`

| Field | Type |
|---|---|
| `claim_id` | `string` |
| `status` | `string` (`LOCKED`, `VALIDATED`, `CONTRADICTED`, `UNSETTLED`, `SCOPE_DRIFT`) |
| `intent` | `string` |
| `scope_path` | `string` |
| `predicted_outcome` | `string` |
| `falsifiers` | `array[string[]]` |
| `must_not_break` | `array[string[]]` |
| `quality` | `object` |
| `attribution` | `object` |
| `changed_files_in_scope` | `array[string]` |
| `scope_drift_files` | `array[string]` |

### `counts`

`changed_files`, `claims`, `settled_claims`, `validated`, `contradicted`,
`unsettled`, `evidence_dark`, `evidence_dark_source`, `evidence_dark_cache`,
`scope_drift` — all integers.

## Markdown sections

The rendered `PR_EVIDENCE.md` always contains, in order:

```
# PR Evidence — Merge X-Ray
## Verdict
## Settled Claims
## Evidence-Dark Changes
## Scope Drift
## Weak / Unsettled Evidence
## Reviewer Focus
## Non-Claims
```

## Coverage semantics

- A changed file is **covered** if it is under the `scope_path` of a `VALIDATED`
  or `SCOPE_DRIFT` claim.
- It is **evidence-dark** if no settled claim's scope covers it.
- Coverage is **path-based** — "covered by declared claim scope", never a
  guarantee that the file is tested or correct.

## Non-claims

The X-Ray does not prove the code is correct, secure, or complete. It does not
rank or route models, and it does not assert M2B readiness. It states which
claims settled against which checks at which declared scope.

## Example

```json
{
  "schema_version": 1,
  "mode": "claim_locked",
  "diff": {"mode": "range", "base": "main", "head": "HEAD"},
  "verdict": "Review required: 2 evidence-dark file(s), 1 scope drift warning(s).",
  "changed_files": [
    "packages/cart/checkout.py",
    "packages/cart/discount.py",
    "packages/payments/refund.py"
  ],
  "settled_claims": [
    {
      "claim_id": "clm_feaf0125d1784a64",
      "status": "VALIDATED",
      "intent": "fix checkout null dereference",
      "scope_path": "packages/cart",
      "changed_files_in_scope": ["packages/cart/checkout.py"]
    }
  ],
  "evidence_dark_files": [
    "packages/cart/discount.py",
    "packages/payments/refund.py"
  ],
  "weakly_covered_files": [],
  "scope_drift_files": ["packages/payments/refund.py"],
  "reviewer_focus": [
    "Review `packages/payments/refund.py` manually — it changed outside the declared scope.",
    "Review `packages/cart/discount.py` manually — no settled claim covers it.",
    "Skim `packages/cart/checkout.py`; it has a settled claim, but this is not proof of correctness."
  ],
  "counts": {"changed_files": 3, "evidence_dark": 2, "scope_drift": 1},
  "caveat": "This report shows settled evidence, not proof of correctness."
}
```
