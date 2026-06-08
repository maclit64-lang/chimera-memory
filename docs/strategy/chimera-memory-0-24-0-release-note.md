# chimera-memory 0.24.0 — Local MCP Tool Layer

## Release theme

v0.24.0 adds the local MCP tool layer: a stdio MCP server that exposes
Chimera's claim and X-Ray primitives to MCP-capable coding agents.

## New CLI

```bash
chimera-memory mcp serve
chimera-memory mcp serve --allow-write
chimera-memory mcp serve --allow-write --allow-execute
```

## MCP client config

```json
{
  "mcpServers": {
    "chimera-memory": {
      "command": "chimera-memory",
      "args": ["mcp", "serve", "--allow-write"]
    }
  }
}
```

## Tools

| Tool | Permission | Description |
|---|---|---|
| `chimera_claim_validate` | read | Dry-run validate — no ledger write |
| `chimera_claim_show` | read | Read one claim |
| `chimera_claim_list` | read | List claims |
| `chimera_claim_lock_auto` | `--allow-write` | Seal claim via auto-lock seam |
| `chimera_xray_generate` | `--allow-write` | Generate PR_EVIDENCE.md |
| `chimera_claim_settle` | `--allow-execute` | Settle — runs sealed local commands |

## Architecture decision

Implemented the MCP protocol subset directly (no `mcp` SDK dependency).
Only `initialize`, `tools/list`, `tools/call`, and `ping`. Keeps install
minimal (~0 new transitive dependencies) and behavior auditable.

## Permission model

Three classes, explicitly gated:
- **read** — default; no ledger mutation, no command execution
- **write** — `--allow-write`; ledger writes, report output
- **execute** — `--allow-execute`; runs sealed project commands

## Safety

No network. No cloud. No telemetry. `shell=False` throughout. Shell string
commands rejected. No raw ledger data in tool output.

## Tests

+32 tests: permission gating, all 6 tools, MCP protocol smoke.

## Honesty

- This is not a hosted MCP server.
- MCP-capable clients connect to the local process.
- Not an official Claude/Codex/Cursor integration.
- Execute tools run commands from sealed claims.
- Scope coverage remains path-based.
- This is settled evidence, not proof of code correctness.

## Not built

- Claude hooks, Codex plugin, Cursor extension
- Remote/hosted transport
- Model ranking/routing/M2B scoring
- Hosted/cloud/dashboard
- Coverage.py/lcov ingestion
- Multi-scope claims, full multi-terminal orchestration

## Dependency

```text
chimera-memory-types>=0.24.0,<1.0
```
