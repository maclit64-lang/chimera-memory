# chimera-memory 0.12.0 Release Note

**Theme:** Package Metadata + Release Documentation

**Release date:** 2026-06-07

---

## What changed

- Added package authors metadata (`ORIAS <hello@orias.dev>`)
- Added project URLs: Homepage, Source, Issues
- Added GitHub Release draft (`docs/releases/v0.11.0.md`)
- Added release-doc guard tests (`test_release_docs.py`, 7 assertions)

Both `chimera-memory` and `chimera-memory-types` now show author and project links on PyPI.

---

## Why it matters

- PyPI pages now show maintainer identity and links to source/issues
- Users can find the repo and file bugs directly from PyPI
- Release documentation is guarded against overclaiming or leaking private paths
- No runtime behavior change — metadata-only improvement

---

## What did not change

- No runtime feature changes
- No M2B scoring
- No model ranking
- No routing
- No write-import
- No hosted/cloud
- No dashboard
- No threshold weakening
- No storage migration
- No GitHub Actions/billing work

---

## Verification

- pytest: 662/662 passing (7 new release-doc guard tests)
- mypy: 0 errors (chimera-memory and chimera-memory-types)
- ruff: clean
- Artifact metadata validated: authors, URLs, license, classifiers all correct
- DQ wraps: 10/10 VALIDATED in dogfood sprint

---

## M2B status

- Still BLOCKED
- organic_real volume blocker cleared (31 >= 25)
- organic_real_failed: 0 < 5 (still blocking)
- comparable_groups: 1 < 2 (still blocking)
- repair_loops: 0 < 3 (still blocking)
- This release does not enable M2B scoring
