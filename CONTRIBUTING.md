# Contributing to chimera-memory

Thank you for contributing to chimera-memory!

## Local Setup

```bash
# Clone the repo
git clone https://github.com/maclit64-lang/chimera-memory.git
cd chimera-memory

# Install dependencies (requires uv)
uv sync

# Verify the installation
chimera-memory doctor
```

## Running Tests

```bash
# All fast tests
uv run pytest packages/chimera-memory/tests -m "not slow"

# Type checks
uv run mypy packages/chimera-memory/src
uv run mypy packages/chimera-memory-types/src

# Lint
uv run ruff check packages/chimera-memory/src packages/chimera-memory/tests packages/chimera-memory-types/src

# Full integrity check
chimera-memory verify

# M2B readiness check
chimera-memory m2b-readiness --explain
```

## Diagnostic Commands

Always include `chimera-memory doctor` and `chimera-memory verify` output when reporting issues.

## Filing Issues

Use the bug report template for broken behavior.
Use the feature request template for proposals.

**Do not** include:
- Tokens, API keys, or `ghp_` / `pypi-` strings
- Absolute paths (e.g. `/Users/yourname/...`)
- `.chimera-memory/` directories or receipt bundles

## What NOT to claim

M2B scoring, model ranking, and model routing are **not yet built**.
Do not add claims to docs or code suggesting these features exist.

## What NOT to commit

- `.chimera-memory/` directory (it is in `.gitignore` for a reason)
- Ledger files, receipts, evidence bundles
- Tokens or private credentials
