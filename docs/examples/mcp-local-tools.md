# Local MCP Tools for Coding Agents

`chimera-memory mcp serve` starts a local stdio MCP server that exposes
Chimera's claim/xray primitives to MCP-capable coding agents.

This is not a hosted server. All data stays local. No network. No cloud.

## Start the server

```bash
# Read-only mode (default): validate, show, list
chimera-memory mcp serve

# With local-write tools: claim lock, xray generate
chimera-memory mcp serve --allow-write

# With execute tools: claim settle (runs local commands)
chimera-memory mcp serve --allow-write --allow-execute
```

## MCP client config (Claude Desktop / Cursor / Codex)

Read-only + write:
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

With settlement (runs local project commands from sealed claims):
```json
{
  "mcpServers": {
    "chimera-memory": {
      "command": "chimera-memory",
      "args": ["mcp", "serve", "--allow-write", "--allow-execute"]
    }
  }
}
```

> `--allow-execute` is required for claim settlement because it runs the
> local commands defined in the sealed claim (tests, linters, etc.).
> MCP-capable clients can connect to this local server.
> This is not an official Claude/Codex/Cursor integration — it uses the
> standard MCP protocol.

## Available tools

### Read-only (always available)

**`chimera_claim_validate`** — Validate a claim spec without writing anything.
```json
{
  "intent": "fix checkout null dereference",
  "scope_path": "packages/cart",
  "falsifiers": [["uv","run","pytest","tests/test_checkout.py"]],
  "must_not_break": [["uv","run","pytest","tests/test_cart.py"]]
}
```

**`chimera_claim_show`** — Read one claim by id.
```json
{"claim_id": "clm_..."}
```

**`chimera_claim_list`** — List recent claims.
```json
{"limit": 20}
```

### Write tools (`--allow-write`)

**`chimera_claim_lock_auto`** — Create a sealed claim.
```json
{
  "intent": "fix checkout null dereference",
  "scope_path": "packages/cart",
  "falsifiers": [["uv","run","pytest","tests/test_checkout.py"]],
  "dry_run": false
}
```

**`chimera_xray_generate`** — Generate PR_EVIDENCE.md.
```json
{
  "base": "main",
  "head": "HEAD",
  "output_path": "PR_EVIDENCE.md"
}
```

### Execute tools (`--allow-execute`)

**`chimera_claim_settle`** — Settle a claim against its sealed checks.
```json
{"claim_id": "clm_..."}
```

> Settlement runs the commands from the sealed claim. This can include
> test runners, linters, or any commands defined in the original falsifier.

## Typical agent workflow

```
1. agent calls chimera_claim_validate (preview, no write)
2. agent calls chimera_claim_lock_auto (seal the claim)
3. agent makes code edits
4. agent calls chimera_claim_settle (runs sealed checks)
5. agent calls chimera_xray_generate (produce PR_EVIDENCE.md)
```

## Permission summary

| Tool | Permission | Why |
|---|---|---|
| `chimera_claim_validate` | read-only | No ledger mutation |
| `chimera_claim_show` | read-only | No ledger mutation |
| `chimera_claim_list` | read-only | No ledger mutation |
| `chimera_claim_lock_auto` | `--allow-write` | Writes to claim_locks.jsonl |
| `chimera_xray_generate` | `--allow-write` | May write PR_EVIDENCE.md |
| `chimera_claim_settle` | `--allow-execute` | Runs local project commands |

## Honesty

- This is settled evidence, not proof of code correctness.
- Scope coverage is path-based.
- Execute tools run whatever commands were sealed in the claim.
- No model ranking, routing, or M2B scoring.
