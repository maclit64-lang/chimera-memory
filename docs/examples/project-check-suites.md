# Project Check Suites

Run verification commands through Chimera Memory with one config file.

## Setup

```bash
chimera-memory init
chimera-memory checks init --preset python
```

This creates `chimera-memory.checks.toml`:

```toml
schema_version = 1
scope_path = "."
verification_scope = "package"
failure_origin = "organic_real"

[[checks]]
name = "python-version"
command = ["python", "--version"]
```

## Add your own checks

```toml
[[checks]]
name = "pytest"
command = ["pytest", "tests/", "-q"]

[[checks]]
name = "mypy"
command = ["mypy", "src/"]

[[checks]]
name = "ruff"
command = ["ruff", "check", "src/"]
```

## Run

```bash
chimera-memory checks run
```

## Run with receipt bundle

```bash
chimera-memory checks run --bundle --output-dir ./chimera-run
chimera-memory bundle inspect ./chimera-run/receipt
```

## What happens

1. Reads `chimera-memory.checks.toml`
2. Starts a session automatically
3. Wraps each command through Chimera Memory
4. Ends session (PASSED or FAILED)
5. Verifies ledger integrity
6. Optionally creates a receipt bundle

## Safety

- Commands must be `list[str]` — no shell execution
- Chimera Memory itself makes no network calls
- Your commands run normally (they may do whatever they do)
- Config file is plain TOML, readable and auditable

## Non-goals

- Not CI (use your existing CI for that)
- Not hosted/cloud
- Not M2B scoring
- Not model ranking or routing
