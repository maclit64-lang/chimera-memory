# chimera-memory 0.15.0 Release Note

**Theme:** Bundle Inspect / Public Evidence Verification

**Release date:** 2026-06-07

---

## What changed

- New CLI command: `chimera-memory bundle inspect <path> [--json]`
- Read-only safety inspection of receipt or evidence bundles
- Detects bundle type (receipt / evidence / unknown)
- Flags raw ledger files as CRITICAL
- Flags token-like strings and private paths as WARNING
- Reports status: OK / WARNING / CRITICAL / UNKNOWN
- JSON contract doc at `docs/contracts/bundle-inspect-json.md`
- 9 new tests

---

## Why it matters

- Users can verify bundle safety before sharing or importing
- Agents can programmatically check bundles via `--json`
- Reduces risk of accidentally sharing raw ledger data or secrets

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
