# chimera-memory 0.19.0 Release Note

**Theme:** Project Check Suites / Local Verification Recipes

**Release date:** 2026-06-07

---

## What changed

- New CLI commands: `chimera-memory checks init` and `chimera-memory checks run`
- Define verification commands in `chimera-memory.checks.toml`
- Run all checks with one command, get a receipt bundle automatically
- Commands must be list[str] — no shell execution
- 8 new tests + docs example

---

## Why it matters

- Repeat-use verification is now one command instead of five
- Config is readable TOML, easy to audit and version control
- Receipt bundles capture verification state for later comparison

---

## What did not change

- No M2B scoring
- No model ranking
- No routing
- No hosted/cloud
- No dashboard
- No write-import
- No telemetry
- No network calls by Chimera Memory

---

## M2B status

- Still BLOCKED
- No comparable-group advancement claimed
