# chimera-memory 0.11.0 Release Note

**Theme:** Public Adoption + Output Polish

**Release date:** 2026-06-07

---

## What changed

### README first-user cleanup

- **Python version corrected:** `3.10+` → `3.12+` (matches `requires-python = ">=3.12"`)
- **Quickstart `wrap` now includes `--scope-path .`** — the flag was missing from the 5-command example
- **PyPI docs/prompts link fixed:** was `../../docs/prompts/` (broken on PyPI); now links to source repo
- **Duplicate "Preflight check" section removed** — it duplicated the "Preflight Intelligence" section
- **Stale `0.1.x` wording fixed** in evidence dry-run section

### Metadata

- **MacOS Trove classifier corrected:** `Operating System :: MacOS` → `Operating System :: MacOS :: MacOS X`

### Fresh install transcript

`docs/examples/fresh-install-smoke.md` — shows the full install → init → session → wrap → receipt → doctor → preflight → m2b-readiness flow with real trimmed output and placeholder values. Useful for new users and for integration testing.

### Docs guard tests

`tests/test_public_docs.py` — 10 tests asserting the transcript contains required commands, does not contain private paths or tokens, and the README has accurate Python version and no broken PyPI links.

---

## Why it matters

A first-time user installing from PyPI saw: wrong Python version, a broken docs link, a missing flag in the quickstart, and a duplicate section. These are trust-eroding. v0.11 fixes them.

The transcript and guard tests prevent this class of regression from shipping again.

---

## What did not change

- No M2B scoring
- No model ranking
- No routing
- No write-import
- No hosted/cloud or dashboard
- No threshold weakening
- No storage migration
- No GitHub Actions work

---

## Verification

- pytest: 655/655 passing (10 new guard tests)
- mypy: 0 errors (chimera-memory and chimera-memory-types)
- ruff: clean
- DQ wraps: 10/10 VALIDATED in dogfood sprint; 11/11 VALIDATED in release closeout
- No `repair_loop_id` or `repair_phase` used (no real defects during sprint)

---

## Caveats

- GitHub Actions remains blocked by external account billing lock — not a release blocker
- M2B readiness: BLOCKED (organic_real_failed 3/5) — expected, not a release blocker
- This sprint did not advance M2B — no real defects occurred during docs/metadata work
