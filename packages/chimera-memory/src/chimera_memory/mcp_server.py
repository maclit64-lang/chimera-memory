"""Local MCP tool layer for Chimera Memory (v0.24).

Implements a minimal stdio MCP server (JSON-RPC 2.0 subset) that exposes
Chimera's claim/xray primitives to MCP-capable coding agents (Claude, Codex,
Cursor, etc.) running locally.

Architecture decision
---------------------
We implement the MCP stdio protocol directly rather than pulling in the
official ``mcp`` Python SDK (~12 transitive dependencies including anyio and
httpx). The subset we need is small and fully specifiable:

  * ``initialize``            — capability negotiation
  * ``tools/list``            — return available tool schemas
  * ``tools/call``            — dispatch to a tool function

This keeps the install minimal, the behavior auditable, and the protocol
compliance testable without a heavy framework.

Permission model
----------------
Tools are divided into three classes:

  read_only   — default; no ledger mutations, no command execution
  write       — requires ``--allow-write``; ledger writes and report output
  execute     — requires ``--allow-execute``; runs sealed project commands

Safety requirements
-------------------
  No network.
  No remote transport.
  No telemetry.
  No shell=True.
  Shell strings in command arrays are rejected.
  No raw ledger files in tool output.
  Token and private path redaction follows the same rules as the CLI.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Permission model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolPermissions:
    allow_write: bool = False
    allow_execute: bool = False

    @property
    def read_only(self) -> bool:
        return not self.allow_write and not self.allow_execute


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

_TOOLS: list[dict[str, Any]] = []


def _tool(
    *,
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
    permission: str = "read",
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
        "_permission": permission,  # internal; stripped in list_tools output
    }


_TOOLS = [
    _tool(
        name="chimera_claim_validate",
        description=(
            "Dry-run validate a claim spec (intent, scope, falsifiers). "
            "Reports hard errors and warnings. "
            "Does NOT create a claim record or write to .chimera-memory/. "
            "Safe to call without --allow-write."
        ),
        properties={
            "intent": {"type": "string", "description": "Task intent"},
            "scope_path": {"type": "string", "description": "Declared scope path"},
            "falsifiers": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "string"}},
                "description": "Command arrays for falsifier checks",
            },
            "must_not_break": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "string"}},
                "description": "Command arrays for must-not-break checks",
            },
            "predicted_outcome": {
                "type": "string",
                "description": "Expected outcome string (optional)",
            },
        },
        required=["intent", "falsifiers"],
        permission="read",
    ),
    _tool(
        name="chimera_claim_lock_auto",
        description=(
            "Create a sealed claim using the auto-lock seam. "
            "Requires --allow-write. "
            "If dry_run=true, validates and returns the spec without locking."
        ),
        properties={
            "intent": {"type": "string"},
            "scope_path": {"type": "string"},
            "falsifiers": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "string"}},
            },
            "must_not_break": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "string"}},
            },
            "predicted_outcome": {"type": "string"},
            "dry_run": {
                "type": "boolean",
                "description": "If true, validate only — do not write to ledger",
                "default": False,
            },
        },
        required=["intent", "falsifiers"],
        permission="write",
    ),
    _tool(
        name="chimera_claim_show",
        description="Read one claim record by id. No ledger mutation.",
        properties={
            "claim_id": {"type": "string", "description": "Claim id (clm_...)"},
        },
        required=["claim_id"],
        permission="read",
    ),
    _tool(
        name="chimera_claim_list",
        description="List recent claim lock records. No ledger mutation.",
        properties={
            "limit": {
                "type": "integer",
                "description": "Maximum number of claims to return (default: 20)",
                "default": 20,
            },
        },
        required=[],
        permission="read",
    ),
    _tool(
        name="chimera_claim_settle",
        description=(
            "Settle a claim against its pre-committed sealed falsifier and "
            "must-not-break checks. "
            "WARNING: This runs the local project commands defined in the sealed claim. "
            "Requires --allow-execute. "
            "Settlement cannot substitute a different command — only the sealed checks run."
        ),
        properties={
            "claim_id": {"type": "string", "description": "Claim id to settle"},
        },
        required=["claim_id"],
        permission="execute",
    ),
    _tool(
        name="chimera_xray_generate",
        description=(
            "Generate a Merge X-Ray (PR_EVIDENCE.md) from git diff and claim evidence. "
            "Requires --allow-write. "
            "Reports settled claims, evidence-dark changes, scope drift, and reviewer focus. "
            "This is settled evidence, not proof of code correctness."
        ),
        properties={
            "base": {
                "type": "string",
                "description": "Base git ref (e.g. main). Default: working-tree mode.",
            },
            "head": {
                "type": "string",
                "description": "Head git ref (e.g. HEAD). Used with base.",
            },
            "output_path": {
                "type": "string",
                "description": "Write Markdown report to this path (optional).",
            },
            "json_output": {
                "type": "boolean",
                "description": "Return structured JSON instead of Markdown",
                "default": False,
            },
        },
        required=[],
        permission="write",
    ),
    _tool(
        name="chimera_tool_notes_suggest",
        description=(
            "Suggest local tool/workflow lessons (agent skill memory) by exact match "
            "on task_kind / tool_name / workflow_name / tag (omit all to return every "
            "note). Read-only: never writes, creates a store, runs commands, spawns "
            "agents, or calls models. Exact-match with AND across filters; stored order, "
            "no ranking. Advisory — local operational lessons only; not a correctness, "
            "safety, approval, merge, production-readiness, or speed guarantee."
        ),
        properties={
            "root": {
                "type": "string",
                "description": "Repo root to read .chimera-memory from (default: server root).",
                "default": ".",
            },
            "task_kind": {"type": "string", "description": "Exact task_kind filter (optional)."},
            "tool_name": {"type": "string", "description": "Exact tool_name filter (optional)."},
            "workflow_name": {
                "type": "string",
                "description": "Exact workflow_name filter (optional).",
            },
            "tag": {"type": "string", "description": "Exact tag filter, membership (optional)."},
        },
        required=[],
        permission="read",
    ),
]

_PERM_RANK = {"read": 0, "write": 1, "execute": 2}


def _allowed(tool: dict[str, Any], perms: ToolPermissions) -> bool:
    p = tool.get("_permission", "read")
    if p == "read":
        return True
    if p == "write":
        return perms.allow_write
    if p == "execute":
        return perms.allow_execute
    return False


def list_tools(perms: ToolPermissions) -> list[dict[str, Any]]:
    """Return tools visible under the given permissions."""
    result = []
    for t in _TOOLS:
        if _allowed(t, perms):
            clean = {k: v for k, v in t.items() if k != "_permission"}
            result.append(clean)
    return result


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _tool_validate(args: dict[str, Any], *, root: Path) -> dict[str, Any]:
    from chimera_memory.claim_lock import ClaimSpec, validate_claim_spec
    spec = ClaimSpec(
        intent=args.get("intent", ""),
        scope_path=args.get("scope_path", "."),
        predicted_outcome=args.get("predicted_outcome", "pre-committed checks pass"),
        falsifiers=args.get("falsifiers", []),
        must_not_break=args.get("must_not_break", []),
    )
    result = validate_claim_spec(spec, root=root)
    return {
        "ok": result["valid"],
        "errors": result["errors"],
        "warnings": result["warnings"],
        "generated_spec": spec.sealed_payload(),
    }


def _tool_lock_auto(
    args: dict[str, Any],
    *,
    root: Path,
    perms: ToolPermissions,
) -> dict[str, Any]:
    from chimera_memory.claim_lock import (
        build_claim_spec_from_auto_inputs,
        lock_claim,
        validate_claim_spec,
    )
    from chimera_memory.storage import MemoryStore

    dry_run = bool(args.get("dry_run", False))
    spec, extra_meta = build_claim_spec_from_auto_inputs(
        intent=args.get("intent"),
        scope_path=args.get("scope_path"),
        falsifiers_json=json.dumps(args["falsifiers"]),
        must_not_break_json=(
            json.dumps(args["must_not_break"]) if args.get("must_not_break") else None
        ),
        predicted_outcome=args.get("predicted_outcome"),
        root=root,
    )
    validation = validate_claim_spec(spec, root=root)
    if not validation["valid"]:
        return {
            "claim_id": None,
            "status": "VALIDATION_ERROR",
            "errors": validation["errors"],
            "warnings": validation["warnings"],
            "dry_run": dry_run,
        }

    if dry_run:
        return {
            "claim_id": None,
            "status": "DRY_RUN",
            "errors": [],
            "warnings": validation["warnings"],
            "generated_spec": extra_meta["generated_spec"],
            "dry_run": True,
        }

    store = MemoryStore.from_paths(root=root)
    if not store.memory_dir.exists():
        store.initialize()
    record = lock_claim(store, spec, root=root)
    return {
        "claim_id": record["claim_id"],
        "status": record["settlement"]["status"],
        "errors": [],
        "warnings": record["quality"]["warnings"],
        "generated_spec": extra_meta["generated_spec"],
        "dry_run": False,
    }


def _tool_claim_show(args: dict[str, Any], *, root: Path) -> dict[str, Any]:
    from chimera_memory.storage import MemoryStore

    store = MemoryStore.from_paths(root=root)
    record = store.latest_claim_lock(args["claim_id"])
    if record is None:
        return {"claim": None, "error": f"no claim with id {args['claim_id']!r}"}
    return {"claim": record}


def _tool_claim_list(args: dict[str, Any], *, root: Path) -> dict[str, Any]:
    from chimera_memory.storage import MemoryStore

    limit = int(args.get("limit", 20))
    store = MemoryStore.from_paths(root=root)
    claims = store.latest_claim_locks()[-limit:]
    return {
        "claims": [
            {
                "claim_id": c.get("claim_id"),
                "intent": c.get("intent"),
                "scope_path": c.get("scope_path"),
                "status": c.get("settlement", {}).get("status", "LOCKED"),
                "created_at": c.get("created_at"),
            }
            for c in claims
        ],
        "count": len(claims),
    }


def _tool_settle(args: dict[str, Any], *, root: Path) -> dict[str, Any]:
    from chimera_memory.claim_lock import settle_claim
    from chimera_memory.storage import MemoryStore

    store = MemoryStore.from_paths(root=root)
    record = settle_claim(store, args["claim_id"], root=root)
    settlement = record.get("settlement", {})
    return {
        "claim_id": record.get("claim_id"),
        "settlement_status": settlement.get("status"),
        "commands": [
            {
                "command": c.get("command"),
                "role": c.get("role"),
                "outcome": c.get("outcome"),
                "exit_code": c.get("exit_code"),
            }
            for c in settlement.get("commands", [])
        ],
        "changed_files": settlement.get("changed_files", []),
        "scope_drift_files": settlement.get("scope_drift_files", []),
        "warnings": record.get("quality", {}).get("warnings", []),
    }


def _tool_xray(args: dict[str, Any], *, root: Path) -> dict[str, Any]:
    from chimera_memory.storage import MemoryStore
    from chimera_memory.xray import generate_xray, render_markdown

    store = MemoryStore.from_paths(root=root)
    result = generate_xray(
        store,
        root=root,
        base=args.get("base") or None,
        head=args.get("head") or None,
    )
    output_path = args.get("output_path")
    if output_path and not args.get("json_output", False):
        md = render_markdown(result)
        Path(output_path).write_text(md, encoding="utf-8")

    return {
        "ok": True,
        "output_path": output_path,
        "mode": result["diff"]["mode"],
        "verdict": result["verdict"],
        "summary": {
            "changed_files": result["counts"]["changed_files"],
            "evidence_dark": result["counts"]["evidence_dark"],
            "scope_drift": result["counts"]["scope_drift"],
            "validated": result["counts"]["validated"],
        },
        "xray": result if args.get("json_output", False) else None,
    }


def _tool_tool_notes_suggest(args: dict[str, Any], *, root: Path) -> dict[str, Any]:
    """Read-only: suggest local tool/workflow lessons by exact-match filters.

    Never writes, creates a store, runs commands, or calls models. Reuses the
    same exact-match filter as the CLI; stored order, no ranking.
    """
    from chimera_memory.storage import MemoryStore
    from chimera_memory.tool_notes import filter_tool_notes, read_tool_notes

    arg_root = args.get("root")
    store_root = Path(arg_root) if arg_root else root
    store = MemoryStore.from_paths(root=store_root)
    task_kind = args.get("task_kind")
    tool_name = args.get("tool_name")
    workflow_name = args.get("workflow_name")
    tag = args.get("tag")
    matched = filter_tool_notes(
        read_tool_notes(store),
        task_kind=task_kind,
        tool_name=tool_name,
        workflow_name=workflow_name,
        tag=tag,
    )
    return {
        "schema_version": 1,
        "advisory": (
            "local operational lessons only; not a correctness, safety, approval, "
            "merge, production-readiness, or speed guarantee"
        ),
        "filters": {
            "task_kind": task_kind,
            "tool_name": tool_name,
            "workflow_name": workflow_name,
            "tag": tag,
        },
        "suggestions": [n.to_dict() for n in matched],
    }


_TOOL_DISPATCH: dict[str, Any] = {
    "chimera_claim_validate": lambda a, *, root, perms: _tool_validate(a, root=root),
    "chimera_claim_lock_auto": lambda a, *, root, perms: _tool_lock_auto(a, root=root, perms=perms),
    "chimera_claim_show": lambda a, *, root, perms: _tool_claim_show(a, root=root),
    "chimera_claim_list": lambda a, *, root, perms: _tool_claim_list(a, root=root),
    "chimera_claim_settle": lambda a, *, root, perms: _tool_settle(a, root=root),
    "chimera_xray_generate": lambda a, *, root, perms: _tool_xray(a, root=root),
    "chimera_tool_notes_suggest": lambda a, *, root, perms: _tool_tool_notes_suggest(a, root=root),
}


def call_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    perms: ToolPermissions,
    root: Path,
) -> dict[str, Any]:
    """Dispatch a tool call, enforcing permissions. Returns result dict."""
    tool_def = next((t for t in _TOOLS if t["name"] == name), None)
    if tool_def is None:
        return {"error": f"unknown tool: {name!r}"}
    if not _allowed(tool_def, perms):
        needed = tool_def.get("_permission", "read")
        flag_map = {"write": "--allow-write", "execute": "--allow-execute"}
        flag = flag_map.get(needed, f"--allow-{needed}")
        return {
            "error": (
                f"tool {name!r} requires {flag} permission. "
                f"Restart with: chimera-memory mcp serve {flag}"
            )
        }
    fn = _TOOL_DISPATCH[name]
    try:
        return fn(arguments, root=root, perms=perms)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Minimal stdio MCP server
# ---------------------------------------------------------------------------

_PROTOCOL_VERSION = "2024-11-05"
_SERVER_INFO = {"name": "chimera-memory", "version": "0.24.0"}


def _send(obj: dict[str, Any]) -> None:
    """Write one JSON-RPC message to stdout."""
    line = json.dumps(obj, separators=(",", ":"))
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _send_result(req_id: Any, result: Any) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _send_error(req_id: Any, code: int, message: str) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


def serve_mcp(perms: ToolPermissions, *, root: Path | None = None) -> None:
    """Run the stdio MCP server loop until stdin closes.

    Reads newline-delimited JSON-RPC messages from stdin. Dispatches
    ``initialize``, ``tools/list``, and ``tools/call``. All other methods
    return a standard not-found error.

    Human-readable log lines (if any) go to stderr only — never to stdout,
    which is the MCP protocol channel.
    """
    resolve_root = root or Path.cwd()

    if perms.allow_execute:
        print(
            "chimera-memory mcp: execute tools enabled — "
            "claim settlement may run local project commands from sealed claims.",
            file=sys.stderr,
        )

    initialized = False

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError as exc:
            _send_error(None, -32700, f"parse error: {exc}")
            continue

        req_id = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params") or {}

        # Notifications (no id) — acknowledge but don't respond
        if req_id is None and method:
            continue

        if method == "initialize":
            initialized = True
            _send_result(req_id, {
                "protocolVersion": _PROTOCOL_VERSION,
                "serverInfo": _SERVER_INFO,
                "capabilities": {"tools": {}},
            })

        elif method == "tools/list":
            if not initialized:
                _send_error(req_id, -32002, "not initialized")
                continue
            tools = list_tools(perms)
            # Strip internal _permission field before sending
            _send_result(req_id, {"tools": tools})

        elif method == "tools/call":
            if not initialized:
                _send_error(req_id, -32002, "not initialized")
                continue
            name = params.get("name", "")
            arguments = params.get("arguments") or {}
            result = call_tool(name, arguments, perms=perms, root=resolve_root)
            # MCP tool results are wrapped in content blocks
            content_text = json.dumps(result, separators=(",", ":"))
            _send_result(req_id, {
                "content": [{"type": "text", "text": content_text}],
                "isError": "error" in result,
            })

        elif method == "ping":
            _send_result(req_id, {})

        else:
            _send_error(req_id, -32601, f"method not found: {method!r}")
