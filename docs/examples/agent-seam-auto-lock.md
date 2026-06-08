# Agent-Seam Auto-Lock

`chimera-memory claim lock --auto` is the agent-callable primitive that turns
intent + scope + checks into a sealed claim without writing a `claim.toml` file.

This is the stable seam that future MCP/hooks integrations will call. It is
not those integrations — it is the primitive they will call.

## Basic usage

Set env vars and call `claim lock --auto`:

```bash
CHIMERA_INTENT="fix checkout null dereference" \
CHIMERA_SCOPE_PATH="packages/cart" \
CHIMERA_FALSIFIERS_JSON='[["uv","run","pytest","tests/test_checkout.py::test_empty_cart"]]' \
CHIMERA_MUST_NOT_BREAK_JSON='[["uv","run","pytest","tests/test_cart.py"],["uv","run","ruff","check","packages/cart"]]' \
chimera-memory claim lock --auto --json
```

Output:

```json
{
  "claim_id": "clm_...",
  "status": "LOCKED",
  "auto_lock": true,
  "generated_spec": {
    "intent": "fix checkout null dereference",
    "scope_path": "packages/cart",
    "predicted_outcome": "pre-committed checks pass",
    "falsifiers": [{"command": ["uv", "run", "pytest", "tests/test_checkout.py::test_empty_cart"]}],
    "must_not_break": [...]
  },
  "validation": {"errors": [], "warnings": []},
  "attribution": {"session_id": null, "agent_name": null, ...}
}
```

Then continue the workflow:

```bash
# edit code...
chimera-memory claim settle <claim_id>
chimera-memory xray generate --base main --head HEAD --output PR_EVIDENCE.md
```

## Env var reference

| Variable | Required | Description |
|---|---|---|
| `CHIMERA_INTENT` | Yes | Task intent (what you plan to do) |
| `CHIMERA_SCOPE_PATH` | No | Declared scope. Defaults to `.` with a `BROAD_SCOPE_PATH` warning |
| `CHIMERA_FALSIFIERS_JSON` | Yes* | JSON array of command arrays for falsifier checks |
| `CHIMERA_MUST_NOT_BREAK_JSON` | No | JSON array of command arrays for must-not-break checks |
| `CHIMERA_PREDICTED_OUTCOME` | No | Predicted outcome string. Default: `"pre-committed checks pass"` |

*Required unless `--from-checks` is used.

## CLI flags (override env vars)

```bash
chimera-memory claim lock --auto \
  --intent "fix checkout null dereference" \
  --scope-path packages/cart \
  --falsifiers-json '[["uv","run","pytest","tests/test_checkout.py::test_empty_cart"]]' \
  --must-not-break-json '[["uv","run","pytest","tests/test_cart.py"]]' \
  --predicted-outcome "checkout test passes"
```

## Dry-run mode

Preview the generated claim without sealing it:

```bash
CHIMERA_INTENT="..." \
CHIMERA_FALSIFIERS_JSON='[...]' \
chimera-memory claim lock --auto --dry-run --json
```

Returns the spec + validation warnings. No ledger mutation.

## Save generated spec

If you want to review or version-control the generated spec:

```bash
chimera-memory claim lock --auto --save-spec claim.generated.toml
```

## Fallback: checks.toml

If you have a `chimera-memory.checks.toml` and no `CHIMERA_FALSIFIERS_JSON`:

```bash
CHIMERA_INTENT="run project checks" \
chimera-memory claim lock --auto --from-checks
```

Produces `AUTO_FROM_CHECKS_CONFIG` and `MISSING_TARGETED_FALSIFIER` warnings
because the claim is generated from broad check-suite commands rather than a
targeted falsifier. Still honest — those warnings are stored on the claim.

## Command format

Commands must be JSON arrays of string arrays. Shell strings are never accepted
as executable contracts:

```json
// ✓ correct
[["uv", "run", "pytest", "tests/test_checkout.py"]]

// ✗ rejected — shell string
["pytest tests/test_checkout.py"]
```

## Validation

Auto-lock reuses the v0.22.1 validation logic:
- Hard errors (missing intent, invalid JSON, non-list command) refuse to lock
- Warnings (`BROAD_COMMAND`, `BROAD_SCOPE_PATH`, `MISSING_MUST_NOT_BREAK`) are
  stored in `quality.warnings` on the locked claim and do not block locking

## What this is not

This is not:
- Claude hooks
- An MCP server
- A Codex/Cursor plugin
- A GitHub Action

It is the **primitive** those integrations will call. The env/flag interface is
stable so hooks can call `claim lock --auto` with just a few env vars set.

## Full workflow example

```bash
# 1. Set intent and checks
export CHIMERA_INTENT="migrate checkout to typed cart model"
export CHIMERA_SCOPE_PATH="packages/cart"
export CHIMERA_FALSIFIERS_JSON='[["uv","run","pytest","packages/cart/tests/"]]'
export CHIMERA_MUST_NOT_BREAK_JSON='[["uv","run","mypy","packages/cart/src"],["uv","run","ruff","check","packages/cart"]]'

# 2. Lock before editing (agent calls this)
chimera-memory claim lock --auto --json > /tmp/claim.json
CLAIM_ID=$(python3 -c "import json; print(json.load(open('/tmp/claim.json'))['claim_id'])")

# 3. Edit code...

# 4. Settle against sealed checks
chimera-memory claim settle "$CLAIM_ID"

# 5. Generate PR evidence
chimera-memory xray generate --base main --head HEAD --output PR_EVIDENCE.md
```

See [claim-lock-json.md](../contracts/claim-lock-json.md) for the full schema.
