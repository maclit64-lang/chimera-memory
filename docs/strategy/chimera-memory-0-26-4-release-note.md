# chimera-memory v0.26.4 — X-Ray / PR_EVIDENCE Wrap-Evidence Gap Patch

## Classification

Narrow patch. No evidence settlement semantics changed. No M2B scoring/routing/registry features added. No v0.27 work.

## Summary

v0.26.4 fixes a silent gap in PR_EVIDENCE reporting discovered during the first
naive external alpha trial (gbrain, Node.js / Bun / pnpm).

The tester used `chimera-memory wrap -- pnpm run build` which correctly settled
evidence in the ledger (`claims.jsonl` / `outcomes.jsonl`). However, `xray generate`
only reads `claim_locks.jsonl`. With no claim locks present, it reported
"no pre-edit claims were locked" and gave no indication that settled wrap evidence
existed — making the tester believe their evidence was not captured.

## Root cause

Two separate evidence storage paths:
- `claim lock` + `claim settle` → `claim_locks.jsonl` ← X-Ray reads this
- `chimera-memory wrap` → `claims.jsonl` + `outcomes.jsonl` ← X-Ray did NOT surface this

When `wrap` was used without `claim lock`, xray entered post-hoc mode and silently
ignored all wrap-based VALIDATED outcomes.

## Fix

When `xray generate` enters post-hoc mode (no claim locks found), it now:

1. Checks `outcomes.jsonl` for wrap-based VALIDATED outcomes
2. Exposes `wrap_outcomes_count` in the xray JSON result
3. Adds a "Wrap-Based Evidence (Not Linked to Diff)" section to `PR_EVIDENCE.md`
   explaining that the evidence exists but cannot be linked to changed files
   without file-level scope, and guiding the user toward `claim lock` + `claim settle`

## What did not change

- Settlement logic unchanged
- claim_locks.jsonl schema unchanged
- outcomes.jsonl schema unchanged
- M2B readiness rules unchanged
- No automatic file-scope inference from wrap evidence
- No merge of the two evidence paths

## Tests added

3 new regression tests in `test_xray.py`:
- `test_xray_post_hoc_detects_wrap_outcomes_in_verdict`
- `test_xray_post_hoc_wrap_outcomes_count_in_result`
- `test_xray_post_hoc_no_wrap_outcomes_unchanged`
