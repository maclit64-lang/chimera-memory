# PR Evidence — Merge X-Ray Example

The Merge X-Ray turns locked + settled claims plus a `git diff` into a single
reviewer-facing artifact: `PR_EVIDENCE.md`. It answers, for one branch:

- What did the agent claim before editing?
- What falsifier was sealed?
- Did the claim settle?
- Which changed files are within a declared claim scope?
- Which changed files are evidence-dark?
- Did scope drift occur?
- What should the reviewer inspect first?

## Generate

```bash
# Recommended for PR reviews: commit-range mode, no untracked noise
chimera-memory xray generate --base main --head HEAD --output PR_EVIDENCE.md

# For active dev: working-tree mode (includes uncommitted/untracked files)
chimera-memory xray generate --output PR_EVIDENCE.md

# Machine-readable
chimera-memory xray generate --base main --head HEAD --json
```

### Which mode to use

| Mode | When | Untracked files? |
|---|---|---|
| `--base main --head HEAD` | PR review, CI, final evidence | **No** — clean signal |
| Working-tree (no `--base`) | Active dev, mid-edit review | **Yes** — may include cache/build artefacts |

For PR reviews, always use `--base main --head HEAD`. Working-tree mode can
surface `__pycache__/`, `.pytest_cache/`, `.mypy_cache/` etc. as evidence-dark
entries. The report classifies these automatically, but commit-range mode
eliminates the noise entirely.

## Example output

```md
# PR Evidence — Merge X-Ray

## Verdict

Review required: 2 evidence-dark files, 1 scope drift warning.

## Settled Claims

### VALIDATED — fix checkout null dereference

- Scope: `packages/cart`
- Falsifier: `pytest tests/test_checkout.py::test_empty_cart`
- Must-not-break: `pytest tests/test_cart.py`
- Changed files under declared scope:
  - `packages/cart/checkout.py`

## Evidence-Dark Changes

These files changed but have no settled claim coverage:

- `packages/payments/refund.py`
- `packages/cart/discount.py`

## Scope Drift

Files changed outside the declared claim scope(s):

- `packages/payments/refund.py`

## Weak / Unsettled Evidence

_No weak or unsettled evidence._

## Reviewer Focus

1. Review `packages/payments/refund.py` manually — it changed outside the declared scope.
2. Review `packages/cart/discount.py` manually — no settled claim covers it.
3. Skim `packages/cart/checkout.py`; it has a settled claim, but this is not proof of correctness.

## Non-Claims

This report shows settled evidence, not proof of correctness.

It shows which claims settled against which checks at which declared scope. It
does not prove the code is correct, secure, or complete, and it does not rank or
route models.
```

## Post-hoc mode

If no claim was locked before editing, the X-Ray still runs and reports
`mode: post_hoc`: every changed file is treated as evidence-dark and the verdict
asks the reviewer to inspect all changes manually. This is honest about the
absence of pre-edit evidence rather than inventing it.

## Reading the report

| Section | Use |
|---|---|
| Verdict | One-line ship/review signal |
| Settled Claims | What was predicted and how it settled |
| Evidence-Dark | Highest-attention files — no settled coverage |
| Scope Drift | Files changed outside what was claimed |
| Reviewer Focus | Ordered manual-review checklist |
| Non-Claims | The honesty boundary of the report |

See [xray-json.md](../contracts/xray-json.md) for the machine-readable schema.
