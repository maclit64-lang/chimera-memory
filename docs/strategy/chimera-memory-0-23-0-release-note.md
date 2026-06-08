# chimera-memory 0.23.0 — Agent-Seam Auto-Lock Foundation

## Release theme

v0.23.0 turns manual `claim.toml` authoring into an agent-callable auto-lock
primitive. This is the stable seam that future MCP/hooks integrations will call.

## New CLI surface

```bash
chimera-memory claim lock --auto
chimera-memory claim lock --auto --json
chimera-memory claim lock --auto --dry-run
chimera-memory claim lock --auto --dry-run --json
chimera-memory claim lock --auto --save-spec claim.generated.toml
```

## Target workflow

```bash
CHIMERA_INTENT="fix checkout null dereference" \
CHIMERA_SCOPE_PATH="packages/cart" \
CHIMERA_FALSIFIERS_JSON='[["uv","run","pytest","tests/test_checkout.py::test_empty_cart"]]' \
CHIMERA_MUST_NOT_BREAK_JSON='[["uv","run","pytest","tests/test_cart.py"]]' \
chimera-memory claim lock --auto --json
```

## Highlights

### Env-var driven claim generation

| Env var | Required | Purpose |
|---|---|---|
| `CHIMERA_INTENT` | Yes | Task intent |
| `CHIMERA_SCOPE_PATH` | No | Declared scope (defaults to `.`) |
| `CHIMERA_FALSIFIERS_JSON` | Yes* | JSON array of command arrays |
| `CHIMERA_MUST_NOT_BREAK_JSON` | No | JSON array of command arrays |
| `CHIMERA_PREDICTED_OUTCOME` | No | Outcome string |

### Dry-run mode

`--dry-run` validates and prints the generated spec without sealing or writing
anything. Safe for agent preview.

### Checks-config fallback

`--from-checks` reads `chimera-memory.checks.toml` as the falsifier source
with honest `AUTO_FROM_CHECKS_CONFIG` and `MISSING_TARGETED_FALSIFIER` warnings.

### Validation reuse

All v0.22.1 validation applies: hard errors refuse, warnings are stored in
`quality.warnings` on the locked claim.

### Session/attribution inheritance

Inherits agent/model/harness from active session or env vars
(`AGENT_NAME`, `MODEL_NAME`, `HARNESS_ID`). Unknown values are recorded
honestly as null/"unknown" — never fabricated.

### JSON output for agents

```json
{
  "claim_id": "clm_...",
  "status": "LOCKED",
  "auto_lock": true,
  "generated_spec": {...},
  "validation": {"errors": [], "warnings": [...]},
  "attribution": {...}
}
```

## Tests

+25 tests covering all auto-lock paths, dry-run, session inheritance, flag
overrides, error handling, and regressions.

## This is not

- Claude hooks
- An MCP server
- A Codex/Cursor plugin
- A GitHub Action/App

It is the **primitive** those integrations will call.

## Honesty

Settled evidence, not proof of correctness. Commands are `list[str]` executed
with `shell=False`. JSON arrays required; shell strings rejected. Warnings are
heuristic.

## Not built

- MCP server, hooks, Codex/Cursor/Claude integration
- GitHub Action/App
- Model ranking/routing/M2B scoring
- Hosted/cloud/dashboard
- Coverage.py/lcov ingestion
- Multi-scope claims
- Multi-terminal orchestration

## Dependency

```text
chimera-memory-types>=0.23.0,<1.0
```
