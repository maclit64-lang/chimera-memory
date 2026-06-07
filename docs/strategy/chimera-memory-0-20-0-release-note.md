# chimera-memory 0.20.0 Release Note

**Theme:** Project Run Reports / Checks Result Summary

**Release date:** 2026-06-08

---

## What changed

- `checks run --bundle` now generates `report.md` and `report.json`
- report.json: schema_version, result, checks with status/exit_code, receipt_path, next_actions
- report.md: human-readable check result table
- 4 new tests

---

## Why it matters

- Users can understand and share check results without reading terminal scrollback
- Machines can parse run results via report.json
- Reports clearly state M2B is not built

---

## What did not change

- No M2B scoring
- No model ranking
- No routing
- No hosted/cloud
- No dashboard
- No write-import
- No telemetry

---

## M2B status

- Still BLOCKED
