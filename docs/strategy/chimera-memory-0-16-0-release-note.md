# chimera-memory 0.16.0 Release Note

**Theme:** Bundle Diff / Evidence Comparison + Performance Stability

**Release date:** 2026-06-07

---

## What changed

- New CLI command: `chimera-memory bundle diff <old> <new> [--json]`
- Read-only comparison of receipt or evidence bundles
- Reports file delta, claim/event count changes, integrity changes
- Flags incompatible types and increasing failures
- Status: OK / WARNING / INCOMPATIBLE / UNKNOWN
- Storage benchmark test reclassified as `@pytest.mark.slow` for stable verification
- JSON contract doc at `docs/contracts/bundle-diff-json.md`
- 10 new tests for bundle diff

---

## Why it matters

- Users can compare bundles before importing or sharing
- Agents can programmatically detect evidence drift via `--json`
- Normal verification is now stable on loaded machines (no timing flakes)

---

## What did not change

- No M2B scoring
- No model ranking
- No routing
- No hosted/cloud
- No dashboard
- No write-import
- No GitHub Actions/billing work

---

## M2B status

- Still BLOCKED
- No comparable-group advancement claimed
