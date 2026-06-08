# MCP Tools Contract

## Overview

`chimera-memory mcp serve` exposes a local stdio MCP server (JSON-RPC 2.0 over
stdin/stdout). MCP-capable clients connect to it as a local subprocess.

## Protocol

Subset of MCP 2024-11-05:
- `initialize` — capability negotiation
- `tools/list` — list available tools
- `tools/call` — call a tool
- `ping` — keepalive

## Permission model

Tools are gated by permission class:

| Class | Flag | Tools |
|---|---|---|
| `read` | default | `chimera_claim_validate`, `chimera_claim_show`, `chimera_claim_list` |
| `write` | `--allow-write` | `chimera_claim_lock_auto`, `chimera_xray_generate` |
| `execute` | `--allow-execute` | `chimera_claim_settle` |

Attempting to call a tool without the required flag returns a structured error.

## Tool schemas

### chimera_claim_validate
- Permission: read
- Input: `intent` (required), `falsifiers` (required), `scope_path`, `must_not_break`, `predicted_outcome`
- Output: `{ok, errors, warnings, generated_spec}`
- No ledger mutation.

### chimera_claim_lock_auto
- Permission: write
- Input: `intent` (required), `falsifiers` (required), `scope_path`, `must_not_break`, `predicted_outcome`, `dry_run`
- Output: `{claim_id, status, errors, warnings, generated_spec, dry_run}`
- If `dry_run=true`: no ledger write.

### chimera_claim_show
- Permission: read
- Input: `claim_id` (required)
- Output: `{claim}`

### chimera_claim_list
- Permission: read
- Input: `limit` (default: 20)
- Output: `{claims, count}`

### chimera_claim_settle
- Permission: execute
- Input: `claim_id` (required)
- Output: `{claim_id, settlement_status, commands, changed_files, scope_drift_files, warnings}`
- **Runs local commands** from the sealed claim.

### chimera_xray_generate
- Permission: write
- Input: `base`, `head`, `output_path`, `json_output`
- Output: `{ok, output_path, mode, verdict, summary}`
- `mode` is `working_tree` or `range`.

## Error format

Tool errors return `{"error": "message"}` in the content text. The MCP
response sets `isError: true`.

## Safety guarantees

- No network calls.
- No remote transport.
- No telemetry.
- All commands via `shell=False`.
- Shell string commands are rejected.
- No raw ledger data in tool output.
- Token redaction follows the same rules as the CLI.

## Caveat

This is settled evidence, not proof of code correctness.
