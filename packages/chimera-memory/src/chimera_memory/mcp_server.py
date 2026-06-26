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
            "limit": {
                "type": "integer",
                "description": "Max suggestions to return (>=0, optional).",
            },
        },
        required=[],
        permission="read",
    ),
    _tool(
        name="chimera_tool_note_show",
        description=(
            "Show one local tool note by exact note_id. Read-only: never writes, "
            "creates a store, runs commands, or calls models. Returns found=false when "
            "the id is unknown. Advisory — local operational notes only; not a "
            "correctness, safety, approval, merge, production-readiness, or speed guarantee."
        ),
        properties={
            "root": {
                "type": "string",
                "description": "Repo root whose store to read (default: server root).",
                "default": ".",
            },
            "note_id": {"type": "string", "description": "Exact note id (tn_...)."},
        },
        required=["note_id"],
        permission="read",
    ),
    _tool(
        name="chimera_tool_note_add",
        description=(
            "Records a local advisory operational note (agent skill memory) about a "
            "tool or workflow that helped. Requires --allow-write. Append-only to "
            "tool_notes.jsonl; does not touch the claims/outcomes/scores/sessions "
            "ledger. The supplied note is stored as-is — it is not judged true or "
            "validated, and is not a correctness, safety, approval, merge, "
            "production-readiness, or speed guarantee."
        ),
        properties={
            "root": {
                "type": "string",
                "description": "Repo root whose store to write (default: server root).",
                "default": ".",
            },
            "task_kind": {"type": "string", "description": "Task kind this lesson applies to."},
            "tool_name": {"type": "string", "description": "Tool the lesson is about."},
            "lesson": {"type": "string", "description": "The operational lesson (what to do)."},
            "workflow_name": {"type": "string", "description": "Workflow name (optional)."},
            "evidence": {"type": "string", "description": "Supporting evidence text (optional)."},
            "caveat": {"type": "string", "description": "Caveats / costs / failures (optional)."},
            "source": {
                "type": "string",
                "description": "Provenance label (default: manual).",
                "default": "manual",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags.",
            },
        },
        required=["task_kind", "tool_name", "lesson"],
        permission="write",
    ),
    _tool(
        name="chimera_tool_activity_add",
        description=(
            "Record one local tool/workflow activity (what happened operationally). "
            "Requires --allow-write. Append-only to tool_activity.jsonl; does not touch "
            "the claims/outcomes/scores/sessions ledger or tool_notes. Observational only "
            "— it saves no Tool Note, runs nothing, and judges nothing."
        ),
        properties={
            "root": {
                "type": "string",
                "description": "Repo root whose store to write (default: server root).",
                "default": ".",
            },
            "task_kind": {"type": "string", "description": "Task kind this activity belongs to."},
            "tool_name": {"type": "string", "description": "Tool that ran."},
            "summary": {"type": "string", "description": "What happened (operational summary)."},
            "workflow_name": {"type": "string", "description": "Workflow name (optional)."},
            "phase": {"type": "string", "description": "Phase label (optional)."},
            "evidence": {"type": "string", "description": "Supporting evidence (optional)."},
            "caveat": {"type": "string", "description": "Caveats / costs / failures (optional)."},
            "status": {"type": "string", "description": "Status, e.g. completed (optional)."},
            "duration_seconds": {"type": "number", "description": "Seconds (optional)."},
            "cost_units": {"type": "number", "description": "Cost units (optional)."},
            "artifact_refs": {
                "type": "array", "items": {"type": "string"},
                "description": "Artifact references (optional).",
            },
            "tags": {
                "type": "array", "items": {"type": "string"}, "description": "Tags (optional).",
            },
            "source": {"type": "string", "description": "Provenance (default: manual)."},
        },
        required=["task_kind", "tool_name", "summary"],
        permission="write",
    ),
    _tool(
        name="chimera_tool_note_candidates",
        description=(
            "Project candidate tool lessons from recorded tool activity, by exact "
            "task_kind/tool_name/workflow_name/tag (all optional, AND) with optional "
            "limit. Read-only: never writes, creates a store, saves a Tool Note, runs "
            "commands, or calls models. Advisory — candidate local operational lessons "
            "to review before saving; not a correctness, safety, approval, merge, "
            "production-readiness, or speed guarantee."
        ),
        properties={
            "root": {
                "type": "string",
                "description": "Repo root whose store to read (default: server root).",
                "default": ".",
            },
            "task_kind": {"type": "string", "description": "Exact task_kind filter (optional)."},
            "tool_name": {"type": "string", "description": "Exact tool_name filter (optional)."},
            "workflow_name": {
                "type": "string",
                "description": "Exact workflow_name filter (optional).",
            },
            "tag": {"type": "string", "description": "Exact tag filter (optional)."},
            "limit": {"type": "integer", "description": "Max candidates after filters (>=0)."},
        },
        required=[],
        permission="read",
    ),
    _tool(
        name="chimera_tool_note_candidate_show",
        description=(
            "Look up one candidate tool lesson by exact candidate_id. Read-only: never "
            "writes, creates a store, saves a Tool Note, runs commands, or calls models. "
            "Returns found:false when absent. Advisory — candidate local operational "
            "lesson to review before saving; not a correctness, safety, approval, merge, "
            "production-readiness, or speed guarantee."
        ),
        properties={
            "root": {
                "type": "string",
                "description": "Repo root whose store to read (default: server root).",
                "default": ".",
            },
            "candidate_id": {"type": "string", "description": "Exact candidate id (cand_...)."},
        },
        required=["candidate_id"],
        permission="read",
    ),
    _tool(
        name="chimera_work_packet",
        description=(
            "Build one portable, local, advisory work packet (evidence + operational "
            "memory): claims, open/unresolved items, next inspection targets, tool "
            "lessons, and candidate lessons, with the applied filters. Read-only: never "
            "writes, creates a store, or runs commands. Advisory — a local evidence and "
            "operational memory summary; not a correctness, safety, approval, merge, "
            "production-readiness, or speed guarantee."
        ),
        properties={
            "root": {
                "type": "string",
                "description": "Repo root whose store to read (default: server root).",
                "default": ".",
            },
            "claim_id": {"type": "string", "description": "Exact claim id filter (optional)."},
            "session_id": {"type": "string", "description": "Exact session id filter (optional)."},
            "status": {"type": "string", "description": "Exact latest_status filter (optional)."},
            "task_kind": {
                "type": "string",
                "description": "Exact task_kind filter for tool notes + candidates (optional).",
            },
            "tag": {
                "type": "string",
                "description": "Exact tag filter for tool notes + candidates (optional).",
            },
            "limit_tool_notes": {
                "type": "integer",
                "description": "Max tool lessons after filters (>=0).",
            },
            "limit_candidates": {
                "type": "integer",
                "description": "Max candidate lessons after filters (>=0).",
            },
        },
        required=[],
        permission="read",
    ),
    _tool(
        name="chimera_work_packet_thread_list",
        description=(
            "List the snapshots in a local Work Packet review thread (reads index.json). "
            "Read-only: never writes, creates a store, or mutates the thread directory. "
            "Advisory — a local review thread index; not a correctness, safety, approval, "
            "merge, production-readiness, or speed guarantee."
        ),
        properties={
            "root": {
                "type": "string",
                "description": "Repo root for a relative thread_dir (default: server root).",
                "default": ".",
            },
            "thread_dir": {"type": "string", "description": "Review thread directory."},
        },
        required=["thread_dir"],
        permission="read",
    ),
    _tool(
        name="chimera_work_packet_thread_inspect",
        description=(
            "Verify every snapshot bundle in a local Work Packet review thread (hashes/sizes). "
            "Read-only: never writes, creates a store, or mutates the thread directory. "
            "Advisory — a local review thread integrity check; not a correctness, safety, "
            "approval, merge, production-readiness, or speed guarantee."
        ),
        properties={
            "root": {
                "type": "string",
                "description": "Repo root for a relative thread_dir (default: server root).",
                "default": ".",
            },
            "thread_dir": {"type": "string", "description": "Review thread directory."},
        },
        required=["thread_dir"],
        permission="read",
    ),
    _tool(
        name="chimera_work_packet_thread_diff_latest",
        description=(
            "Compare the latest two snapshots in a local Work Packet review thread. "
            "Read-only: never writes, creates a store, or mutates the thread directory. "
            "Advisory — a local packet comparison; not a correctness, safety, approval, "
            "merge, production-readiness, or speed guarantee."
        ),
        properties={
            "root": {
                "type": "string",
                "description": "Repo root for a relative thread_dir (default: server root).",
                "default": ".",
            },
            "thread_dir": {"type": "string", "description": "Review thread directory."},
        },
        required=["thread_dir"],
        permission="read",
    ),
    _tool(
        name="chimera_branch_primer",
        description=(
            "Build a local starting-context primer for the next agent: current work "
            "state, unresolved items, next inspection targets, relevant tool lessons, "
            "candidate lessons to review, and (with thread_dir) the latest review-thread "
            "delta. Read-only: never writes, creates a store, or mutates a thread. "
            "Advisory — local work context and operational memory; not a correctness, "
            "safety, approval, merge, production-readiness, or speed guarantee."
        ),
        properties={
            "root": {
                "type": "string",
                "description": "Repo root whose store to read (default: server root).",
                "default": ".",
            },
            "claim_id": {"type": "string", "description": "Exact claim id filter (optional)."},
            "session_id": {"type": "string", "description": "Exact session id filter (optional)."},
            "status": {"type": "string", "description": "Exact latest_status filter (optional)."},
            "task_kind": {
                "type": "string",
                "description": "Exact task_kind filter for tool notes + candidates (optional).",
            },
            "tag": {
                "type": "string",
                "description": "Exact tag filter for tool notes + candidates (optional).",
            },
            "thread_dir": {
                "type": "string",
                "description": "Review thread dir (relative resolved vs root) (optional).",
            },
            "limit_tool_notes": {
                "type": "integer",
                "description": "Max tool lessons after filters (>=0).",
            },
            "limit_candidates": {
                "type": "integer",
                "description": "Max candidate lessons after filters (>=0).",
            },
        },
        required=[],
        permission="read",
    ),
    _tool(
        name="chimera_branch_primer_prompt_header",
        description=(
            "Render a compact, pasteable agent prompt header from the local branch "
            "primer (work state, first inspection targets, tool lessons, candidate "
            "lessons, optional thread delta). Read-only: never writes, creates a store, "
            "or mutates a thread. Advisory — local agent starting context; not a "
            "correctness, safety, approval, merge, production-readiness, or speed guarantee."
        ),
        properties={
            "root": {
                "type": "string",
                "description": "Repo root whose store to read (default: server root).",
                "default": ".",
            },
            "claim_id": {"type": "string", "description": "Exact claim id filter (optional)."},
            "session_id": {"type": "string", "description": "Exact session id filter (optional)."},
            "status": {"type": "string", "description": "Exact latest_status filter (optional)."},
            "task_kind": {
                "type": "string",
                "description": "Exact task_kind filter for tool notes + candidates (optional).",
            },
            "tag": {
                "type": "string",
                "description": "Exact tag filter for tool notes + candidates (optional).",
            },
            "thread_dir": {
                "type": "string",
                "description": "Review thread dir (relative resolved vs root) (optional).",
            },
            "since": {
                "type": "string",
                "description": "Diff this snapshot id vs latest (needs thread_dir) (optional).",
            },
            "limit_tool_notes": {
                "type": "integer",
                "description": "Max tool lessons after filters (>=0).",
            },
            "limit_candidates": {
                "type": "integer",
                "description": "Max candidate lessons after filters (>=0).",
            },
        },
        required=[],
        permission="read",
    ),
    _tool(
        name="chimera_work_brief_list",
        description=(
            "List local Agent Work Briefs (task contracts) by exact task_kind/tag with an "
            "optional limit. Read-only: never writes or creates a store. Advisory — local "
            "task context; not a correctness, safety, approval, merge, production-readiness, "
            "or speed guarantee."
        ),
        properties={
            "root": {
                "type": "string",
                "description": "Repo root whose store to read (default: server root).",
                "default": ".",
            },
            "task_kind": {"type": "string", "description": "Exact task_kind filter (optional)."},
            "tag": {"type": "string", "description": "Exact tag filter (optional)."},
            "limit": {"type": "integer", "description": "Max briefs after filters (>=0)."},
        },
        required=[],
        permission="read",
    ),
    _tool(
        name="chimera_work_brief_show",
        description=(
            "Show one local Agent Work Brief by exact brief_id. Read-only: never writes or "
            "creates a store; returns found:false when unknown. Advisory — local task "
            "context; not a correctness, safety, approval, merge, production-readiness, or "
            "speed guarantee."
        ),
        properties={
            "root": {
                "type": "string",
                "description": "Repo root whose store to read (default: server root).",
                "default": ".",
            },
            "brief_id": {"type": "string", "description": "Exact brief id (brief_...)."},
        },
        required=["brief_id"],
        permission="read",
    ),
    _tool(
        name="chimera_work_session_list",
        description=(
            "List local Agent Work Sessions (folded from events) by exact status/tag with an "
            "optional limit. Read-only: never writes or creates a store. Advisory — local task "
            "lifecycle context; not a correctness, safety, approval, merge, production-readiness, "
            "or speed guarantee."
        ),
        properties={
            "root": {
                "type": "string",
                "description": "Repo root whose store to read (default: server root).",
                "default": ".",
            },
            "status": {"type": "string", "description": "Exact status filter (optional)."},
            "tag": {"type": "string", "description": "Exact tag filter (optional)."},
            "limit": {"type": "integer", "description": "Max sessions after filters (>=0)."},
        },
        required=[],
        permission="read",
    ),
    _tool(
        name="chimera_work_session_show",
        description=(
            "Show one local Agent Work Session (projection + events) by exact session_id. "
            "Read-only: never writes or creates a store; returns session:null when unknown. "
            "Advisory — local task lifecycle context; not a correctness, safety, approval, "
            "merge, production-readiness, or speed guarantee."
        ),
        properties={
            "root": {
                "type": "string",
                "description": "Repo root whose store to read (default: server root).",
                "default": ".",
            },
            "session_id": {"type": "string", "description": "Exact session id (sess_...)."},
        },
        required=["session_id"],
        permission="read",
    ),
    _tool(
        name="chimera_work_session_closeout",
        description=(
            "Build a local Agent Session Closeout for one session: state, brief, attached "
            "snapshot delta (local packet comparison), reported checks, done observations, "
            "carryover, and suggested review targets. Read-only: never writes or creates a "
            "store; returns an error for an unknown session. Advisory — local session "
            "closeout context; not a correctness, safety, approval, merge, "
            "production-readiness, or speed guarantee."
        ),
        properties={
            "root": {
                "type": "string",
                "description": "Repo root whose store to read (default: server root).",
                "default": ".",
            },
            "session_id": {"type": "string", "description": "Exact session id (sess_...)."},
        },
        required=["session_id"],
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
    limit = args.get("limit")
    if isinstance(limit, int) and not isinstance(limit, bool):
        matched = matched[: max(limit, 0)]
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


def _tool_tool_note_show(args: dict[str, Any], *, root: Path) -> dict[str, Any]:
    """Read-only: show one tool note by exact note_id. Never writes or creates a store."""
    from chimera_memory.storage import MemoryStore
    from chimera_memory.tool_notes import find_tool_note

    arg_root = args.get("root")
    store_root = Path(arg_root) if arg_root else root
    note = find_tool_note(MemoryStore.from_paths(root=store_root), str(args.get("note_id", "")))
    return {
        "schema_version": 1,
        "tool_note": note.to_dict() if note else None,
        "found": note is not None,
    }


def _tool_tool_note_add(args: dict[str, Any], *, root: Path) -> dict[str, Any]:
    """Write-gated: append one user/agent-supplied tool note. Requires allow_write.

    Validates the required fields, then appends to tool_notes.jsonl only. Does not
    touch the claims/outcomes/scores/sessions ledger. The note is stored as-is —
    it is not judged true or validated.
    """
    from chimera_memory.storage import MemoryStore
    from chimera_memory.tool_notes import add_tool_note, build_tool_note

    task_kind = args.get("task_kind")
    tool_name = args.get("tool_name")
    lesson = args.get("lesson")
    missing = [
        field
        for field, value in (("task_kind", task_kind), ("tool_name", tool_name), ("lesson", lesson))
        if not value
    ]
    if missing:
        return {"error": f"missing required field(s): {', '.join(missing)}"}

    raw_tags = args.get("tags")
    tags = (
        tuple(str(t) for t in raw_tags if isinstance(t, str))
        if isinstance(raw_tags, list)
        else ()
    )
    arg_root = args.get("root")
    store_root = Path(arg_root) if arg_root else root
    store = MemoryStore.from_paths(root=store_root)
    note = build_tool_note(
        task_kind=task_kind,
        tool_name=tool_name,
        workflow_name=args.get("workflow_name"),
        lesson=lesson,
        evidence=args.get("evidence"),
        caveat=args.get("caveat"),
        source=args.get("source") or "manual",
        tags=tags,
    )
    add_tool_note(store, note)
    return {
        "schema_version": 1,
        "tool_note": note.to_dict(),
        "written_to": "tool_notes.jsonl",
    }


def _tool_tool_activity_add(args: dict[str, Any], *, root: Path) -> dict[str, Any]:
    """Write-gated: record one tool/workflow activity. Requires allow_write.

    Appends only to tool_activity.jsonl. Saves no Tool Note, runs nothing.
    """
    from chimera_memory.storage import MemoryStore
    from chimera_memory.tool_activity import add_tool_activity, build_tool_activity

    task_kind = args.get("task_kind")
    tool_name = args.get("tool_name")
    summary = args.get("summary")
    required = (("task_kind", task_kind), ("tool_name", tool_name), ("summary", summary))
    missing = [field for field, value in required if not value]
    if missing:
        return {"error": f"missing required field(s): {', '.join(missing)}"}

    def _num(value: Any) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    def _strs(value: Any) -> tuple[str, ...]:
        return tuple(str(v) for v in value if isinstance(v, str)) if isinstance(value, list) else ()

    arg_root = args.get("root")
    store = MemoryStore.from_paths(root=Path(arg_root) if arg_root else root)
    activity = build_tool_activity(
        task_kind=task_kind,
        tool_name=tool_name,
        workflow_name=args.get("workflow_name"),
        phase=args.get("phase"),
        summary=summary,
        evidence=args.get("evidence"),
        caveat=args.get("caveat"),
        status=args.get("status"),
        duration_seconds=_num(args.get("duration_seconds")),
        cost_units=_num(args.get("cost_units")),
        artifact_refs=_strs(args.get("artifact_refs")),
        tags=_strs(args.get("tags")),
        source=args.get("source") or "manual",
    )
    add_tool_activity(store, activity)
    return {
        "schema_version": 1,
        "tool_activity": activity.to_dict(),
        "written_to": "tool_activity.jsonl",
    }


def _tool_tool_note_candidates(args: dict[str, Any], *, root: Path) -> dict[str, Any]:
    """Read-only: project candidate tool lessons from activity. Never writes."""
    from chimera_memory.storage import MemoryStore
    from chimera_memory.tool_activity import CANDIDATE_ADVISORY, select_candidates

    arg_root = args.get("root")
    store = MemoryStore.from_paths(root=Path(arg_root) if arg_root else root)
    task_kind = args.get("task_kind")
    tool_name = args.get("tool_name")
    workflow_name = args.get("workflow_name")
    tag = args.get("tag")
    raw_limit = args.get("limit")
    limit = int(raw_limit) if isinstance(raw_limit, int) else None
    candidates = select_candidates(
        store,
        task_kind=task_kind,
        tool_name=tool_name,
        workflow_name=workflow_name,
        tag=tag,
        limit=limit,
    )
    return {
        "schema_version": 1,
        "advisory": CANDIDATE_ADVISORY,
        "filters": {
            "task_kind": task_kind,
            "tool_name": tool_name,
            "workflow_name": workflow_name,
            "tag": tag,
            "limit": limit,
        },
        "candidates": [c.to_dict() for c in candidates],
    }


def _tool_tool_note_candidate_show(args: dict[str, Any], *, root: Path) -> dict[str, Any]:
    """Read-only: look up one candidate by exact candidate_id. Never writes."""
    from chimera_memory.storage import MemoryStore
    from chimera_memory.tool_activity import find_candidate

    arg_root = args.get("root")
    store = MemoryStore.from_paths(root=Path(arg_root) if arg_root else root)
    candidate = find_candidate(store, args.get("candidate_id") or "")
    return {
        "schema_version": 1,
        "candidate": candidate.to_dict() if candidate else None,
        "found": candidate is not None,
    }


def _tool_work_packet(args: dict[str, Any], *, root: Path) -> dict[str, Any]:
    """Read-only: build a work packet from the local ledger. Never writes."""
    from datetime import UTC, datetime

    from chimera_memory.storage import MemoryStore
    from chimera_memory.work_packet import build_work_packet

    def _int(value: Any) -> int | None:
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else None

    arg_root = args.get("root")
    store = MemoryStore.from_paths(root=Path(arg_root) if arg_root else root)
    packet = build_work_packet(
        store,
        generated_at=datetime.now(UTC).isoformat(),
        claim_id=args.get("claim_id"),
        session_id=args.get("session_id"),
        status=args.get("status"),
        task_kind=args.get("task_kind"),
        tag=args.get("tag"),
        limit_tool_notes=_int(args.get("limit_tool_notes")),
        limit_candidates=_int(args.get("limit_candidates")),
    )
    return packet.to_dict()


def _thread_dir_from(args: dict[str, Any], *, root: Path) -> Path:
    raw = args.get("thread_dir") or ""
    p = Path(raw)
    return p if p.is_absolute() else root / p


def _tool_work_packet_thread_list(args: dict[str, Any], *, root: Path) -> dict[str, Any]:
    """Read-only: list review-thread snapshots from index.json."""
    from chimera_memory.work_packet import read_thread_index

    index = read_thread_index(_thread_dir_from(args, root=root))
    if index is None:
        return {"error": f"no thread index at {args.get('thread_dir')!r}"}
    return index


def _tool_work_packet_thread_inspect(args: dict[str, Any], *, root: Path) -> dict[str, Any]:
    """Read-only: verify every snapshot bundle in a review thread."""
    from chimera_memory.work_packet import inspect_thread

    return inspect_thread(_thread_dir_from(args, root=root))


def _tool_work_packet_thread_diff_latest(args: dict[str, Any], *, root: Path) -> dict[str, Any]:
    """Read-only: diff the latest two snapshots in a review thread."""
    from chimera_memory.work_packet import ThreadError, thread_diff_latest

    try:
        return thread_diff_latest(_thread_dir_from(args, root=root))
    except ThreadError as exc:
        return {"error": str(exc)}


def _tool_branch_primer(args: dict[str, Any], *, root: Path) -> dict[str, Any]:
    """Read-only: build a starting-context branch primer. Never writes."""
    from datetime import UTC, datetime

    from chimera_memory.branch_primer import build_branch_primer
    from chimera_memory.storage import MemoryStore
    from chimera_memory.work_packet import ThreadError

    def _int(value: Any) -> int | None:
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else None

    arg_root = args.get("root")
    base = Path(arg_root) if arg_root else root
    store = MemoryStore.from_paths(root=base)
    raw_thread = args.get("thread_dir")
    thread_dir: Path | None = None
    if raw_thread:
        p = Path(raw_thread)
        thread_dir = p if p.is_absolute() else base / p
    try:
        store_label = str(store.memory_dir.relative_to(Path.cwd()))
    except ValueError:
        store_label = store.memory_dir.name
    try:
        primer = build_branch_primer(
            store,
            generated_at=datetime.now(UTC).isoformat(),
            store_label=store_label,
            claim_id=args.get("claim_id"),
            session_id=args.get("session_id"),
            status=args.get("status"),
            task_kind=args.get("task_kind"),
            tag=args.get("tag"),
            thread_dir=thread_dir,
            limit_tool_notes=_int(args.get("limit_tool_notes")),
            limit_candidates=_int(args.get("limit_candidates")),
        )
    except ThreadError as exc:
        return {"error": str(exc)}
    return primer.to_dict()


def _tool_branch_primer_prompt_header(args: dict[str, Any], *, root: Path) -> dict[str, Any]:
    """Read-only: render a compact, pasteable agent prompt header. Never writes."""
    from datetime import UTC, datetime

    from chimera_memory.branch_primer import build_branch_primer, render_prompt_header
    from chimera_memory.storage import MemoryStore
    from chimera_memory.work_packet import ThreadError

    def _int(value: Any) -> int | None:
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else None

    arg_root = args.get("root")
    base = Path(arg_root) if arg_root else root
    store = MemoryStore.from_paths(root=base)
    raw_thread = args.get("thread_dir")
    thread_dir: Path | None = None
    if raw_thread:
        p = Path(raw_thread)
        thread_dir = p if p.is_absolute() else base / p
    try:
        store_label = str(store.memory_dir.relative_to(Path.cwd()))
    except ValueError:
        store_label = store.memory_dir.name
    try:
        primer = build_branch_primer(
            store,
            generated_at=datetime.now(UTC).isoformat(),
            store_label=store_label,
            claim_id=args.get("claim_id"),
            session_id=args.get("session_id"),
            status=args.get("status"),
            task_kind=args.get("task_kind"),
            tag=args.get("tag"),
            thread_dir=thread_dir,
            since=args.get("since"),
            limit_tool_notes=_int(args.get("limit_tool_notes")),
            limit_candidates=_int(args.get("limit_candidates")),
        )
    except ThreadError as exc:
        return {"error": str(exc)}
    return {
        "schema_version": 1,
        "artifact": "chimera_branch_primer_prompt_header",
        "prompt_header": render_prompt_header(primer),
        "summary": primer.summary.to_dict(),
    }


def _tool_work_brief_list(args: dict[str, Any], *, root: Path) -> dict[str, Any]:
    """Read-only: list local work briefs by exact task_kind/tag. Never writes."""
    from chimera_memory.storage import MemoryStore
    from chimera_memory.work_brief import filter_work_briefs, read_work_briefs

    arg_root = args.get("root")
    store = MemoryStore.from_paths(root=Path(arg_root) if arg_root else root)
    briefs = filter_work_briefs(
        read_work_briefs(store), task_kind=args.get("task_kind"), tag=args.get("tag")
    )
    raw_limit = args.get("limit")
    if isinstance(raw_limit, int) and not isinstance(raw_limit, bool):
        briefs = briefs[: max(raw_limit, 0)]
    return {"schema_version": 1, "work_briefs": [b.to_dict() for b in briefs]}


def _tool_work_brief_show(args: dict[str, Any], *, root: Path) -> dict[str, Any]:
    """Read-only: show one work brief by exact brief_id. Never writes."""
    from chimera_memory.storage import MemoryStore
    from chimera_memory.work_brief import find_work_brief

    arg_root = args.get("root")
    store = MemoryStore.from_paths(root=Path(arg_root) if arg_root else root)
    brief = find_work_brief(store, args.get("brief_id") or "")
    return {
        "schema_version": 1,
        "work_brief": brief.to_dict() if brief else None,
        "found": brief is not None,
    }


def _tool_work_session_list(args: dict[str, Any], *, root: Path) -> dict[str, Any]:
    """Read-only: list local work sessions by exact status/tag. Never writes."""
    from chimera_memory.storage import MemoryStore
    from chimera_memory.work_session import filter_sessions, sessions_for_store

    arg_root = args.get("root")
    store = MemoryStore.from_paths(root=Path(arg_root) if arg_root else root)
    sessions = filter_sessions(
        sessions_for_store(store), status=args.get("status"), tag=args.get("tag")
    )
    raw_limit = args.get("limit")
    if isinstance(raw_limit, int) and not isinstance(raw_limit, bool):
        sessions = sessions[: max(raw_limit, 0)]
    return {"schema_version": 1, "sessions": [s.to_dict() for s in sessions]}


def _tool_work_session_show(args: dict[str, Any], *, root: Path) -> dict[str, Any]:
    """Read-only: show one work session (projection + events) by exact id. Never writes."""
    from chimera_memory.storage import MemoryStore
    from chimera_memory.work_session import events_for_session, find_session

    arg_root = args.get("root")
    store = MemoryStore.from_paths(root=Path(arg_root) if arg_root else root)
    session_id = args.get("session_id") or ""
    session = find_session(store, session_id)
    return {
        "schema_version": 1,
        "session": session.to_dict() if session else None,
        "events": [e.to_dict() for e in events_for_session(store, session_id)],
    }


def _tool_work_session_closeout(args: dict[str, Any], *, root: Path) -> dict[str, Any]:
    """Read-only: build a session closeout for one session. Never writes."""
    from datetime import UTC, datetime

    from chimera_memory.session_closeout import build_session_closeout
    from chimera_memory.storage import MemoryStore

    arg_root = args.get("root")
    store = MemoryStore.from_paths(root=Path(arg_root) if arg_root else root)
    session_id = args.get("session_id") or ""
    closeout = build_session_closeout(
        store, session_id, generated_at=datetime.now(UTC).isoformat()
    )
    if closeout is None:
        return {"error": f"no work session with id {session_id!r}"}
    return closeout


_TOOL_DISPATCH: dict[str, Any] = {
    "chimera_claim_validate": lambda a, *, root, perms: _tool_validate(a, root=root),
    "chimera_claim_lock_auto": lambda a, *, root, perms: _tool_lock_auto(a, root=root, perms=perms),
    "chimera_claim_show": lambda a, *, root, perms: _tool_claim_show(a, root=root),
    "chimera_claim_list": lambda a, *, root, perms: _tool_claim_list(a, root=root),
    "chimera_claim_settle": lambda a, *, root, perms: _tool_settle(a, root=root),
    "chimera_xray_generate": lambda a, *, root, perms: _tool_xray(a, root=root),
    "chimera_tool_notes_suggest": lambda a, *, root, perms: _tool_tool_notes_suggest(a, root=root),
    "chimera_tool_note_show": lambda a, *, root, perms: _tool_tool_note_show(a, root=root),
    "chimera_tool_note_add": lambda a, *, root, perms: _tool_tool_note_add(a, root=root),
    "chimera_tool_activity_add": lambda a, *, root, perms: _tool_tool_activity_add(a, root=root),
    "chimera_tool_note_candidates": (
        lambda a, *, root, perms: _tool_tool_note_candidates(a, root=root)
    ),
    "chimera_tool_note_candidate_show": (
        lambda a, *, root, perms: _tool_tool_note_candidate_show(a, root=root)
    ),
    "chimera_work_packet": lambda a, *, root, perms: _tool_work_packet(a, root=root),
    "chimera_work_packet_thread_list": (
        lambda a, *, root, perms: _tool_work_packet_thread_list(a, root=root)
    ),
    "chimera_work_packet_thread_inspect": (
        lambda a, *, root, perms: _tool_work_packet_thread_inspect(a, root=root)
    ),
    "chimera_work_packet_thread_diff_latest": (
        lambda a, *, root, perms: _tool_work_packet_thread_diff_latest(a, root=root)
    ),
    "chimera_branch_primer": lambda a, *, root, perms: _tool_branch_primer(a, root=root),
    "chimera_branch_primer_prompt_header": (
        lambda a, *, root, perms: _tool_branch_primer_prompt_header(a, root=root)
    ),
    "chimera_work_brief_list": lambda a, *, root, perms: _tool_work_brief_list(a, root=root),
    "chimera_work_brief_show": lambda a, *, root, perms: _tool_work_brief_show(a, root=root),
    "chimera_work_session_list": (
        lambda a, *, root, perms: _tool_work_session_list(a, root=root)
    ),
    "chimera_work_session_show": (
        lambda a, *, root, perms: _tool_work_session_show(a, root=root)
    ),
    "chimera_work_session_closeout": (
        lambda a, *, root, perms: _tool_work_session_closeout(a, root=root)
    ),
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
