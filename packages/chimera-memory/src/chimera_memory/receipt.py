"""Chimera Memory M1-4: receipt builder + text/JSON formatters.

A receipt summarizes a closed session as a single human-readable block. Drift is
computed against the same store the session lives in (session.repo_path/.chimera-memory);
if sparse/unavailable, drift shows INSUFFICIENT_DATA.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chimera_memory.drift import detect_drift
from chimera_memory.redaction import redact as _redact
from chimera_memory.session import Session
from chimera_memory.storage import MemoryStore


def _commands_for_session(
    session_id: str,
    session_commands_observed: list[str],
    *,
    root: str | Path | None = None,
    memory_dir: str | Path | None = None,
    store_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Derive commands_observed from claims linked to this session.

    Falls back to session.commands_observed (legacy string list) if the store
    has no linked claims or cannot be read.
    """
    try:
        store = MemoryStore.from_paths(root=root, memory_dir=memory_dir, store_path=store_path)
        claims = store.read_claims()
    except Exception:
        claims = []

    seen_claim_ids: set[str] = set()
    commands: list[dict[str, Any]] = []
    for claim in claims:
        meta = claim.metadata or {}
        if meta.get("session_id") != session_id:
            continue
        cid = claim.claim_id
        if cid in seen_claim_ids:
            continue
        # Only use the settled record (has event metadata with wrapped_args)
        if not (claim.settlement and claim.settlement.events):
            continue
        seen_claim_ids.add(cid)
        evt_meta = claim.settlement.events[-1].metadata or {}
        wrapped_args: list[str] = list(evt_meta.get("wrapped_args") or [])
        exit_code: int | None = evt_meta.get("exit_code")
        status = claim.claim_status.value if claim.claim_status else "unknown"
        commands.append({
            "command": _redact(" ".join(wrapped_args)) if wrapped_args else "(unknown)",
            "task_type": meta.get("task_type"),
            "status": status,
            "exit_code": exit_code,
            "claim_id": cid,
        })

    if commands:
        return commands

    # Fallback: legacy string list from Session.commands_observed
    return [{"command": c, "task_type": None, "status": None, "exit_code": None, "claim_id": None}
            for c in session_commands_observed]


def build_receipt(
    session_dict: dict[str, Any],
    *,
    root: str | Path | None = None,
    memory_dir: str | Path | None = None,
    store_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build a structured receipt dict from a closed session.

    Drift is computed against the same store the session lives in. Pass an
    explicit `root` / `memory_dir` / `store_path` to override; otherwise the
    session's repo_path is used.
    """
    session = Session.from_dict(session_dict)

    # Resolve store root: prefer explicit arg, fall back to session's repo_path
    effective_root = root if (root or memory_dir or store_path) else session.repo_path

    drift = _drift_for_session(
        session, root=effective_root, memory_dir=memory_dir, store_path=store_path
    )
    commands_observed = _commands_for_session(
        session.session_id,
        list(session.commands_observed or []),
        root=effective_root,
        memory_dir=memory_dir,
        store_path=store_path,
    )
    from chimera_memory.integrity import integrity_report_to_summary, verify_integrity

    _memory_dir = (
        Path(memory_dir) if memory_dir
        else Path(store_path).parent if store_path
        else Path(str(effective_root)) / ".chimera-memory"
    )
    try:
        _integrity = integrity_report_to_summary(verify_integrity(_memory_dir))
    except Exception:
        _integrity = None

    return {
        "task_label": session.task_label,
        "session_id": session.session_id,
        "started_at": session.started_at,
        "ended_at": session.ended_at,
        "agent": {
            "app": session.agent_app,
            "model": session.model,
            "attribution": session.attribution_confidence.value,
            "identity_source": session.identity_source.value,
        },
        "git": {
            "start_commit": session.start_commit,
            "end_commit": session.end_commit,
            "dirty": session.end_dirty_state,
            "files_changed_during": session.files_changed_during,
        },
        "outcome": session.final_status.value if session.final_status else "unknown",
        "drift": drift,
        "commands_observed": commands_observed,
        "claims_created": list(session.claims_created or []),
        "outcomes_settled": list(session.outcomes_settled or []),
        "integrity": _integrity,
    }


def _drift_for_session(
    session: Session,
    *,
    root: str | Path | None = None,
    memory_dir: str | Path | None = None,
    store_path: str | Path | None = None,
) -> str:
    """Compute drift scoped to the session's store.

    Returns one of: "OK", "DRIFT_ADVISORY", "INSUFFICIENT_DATA".
    """
    # If no explicit memory context, fall back to the session's repo_path
    # (the same store the session was started in). This is correction 3.
    if root is None and memory_dir is None and store_path is None:
        root = session.repo_path

    result = detect_drift(root=root, memory_dir=memory_dir, store_path=store_path)
    groups_raw = result.get("groups", [])
    groups: list[dict[str, object]] = list(groups_raw) if isinstance(groups_raw, list) else []
    if not groups:
        return "INSUFFICIENT_DATA"

    statuses = [g.get("status") for g in groups]
    if "DRIFT_ADVISORY" in statuses:
        return "DRIFT_ADVISORY"
    if "INSUFFICIENT_DATA" in statuses:
        return "INSUFFICIENT_DATA"
    return "OK"


def format_receipt_text(receipt: dict[str, Any]) -> str:
    """Format a receipt dict as the canonical text block.

    The block is stable across runs so diffs and humans can compare receipts
    line-by-line. Includes the FILES/GIT/COMMIT lines (correction 2).
    """
    agent = receipt["agent"]
    git_block = receipt["git"]
    lines = [
        "Chimera Session Receipt",
        "",
        f"Task: {receipt['task_label']}",
        f"Agent: {agent['app']}",
        f"Model: {agent['model']}",
        f"Attribution: {agent['attribution']}",
        f"Identity source: {agent['identity_source']}",
        f"Start commit: {git_block['start_commit']}",
        f"FILES       {git_block['files_changed_during']} changed",
        f"GIT         {'dirty' if git_block['dirty'] else 'clean'}",
        f"COMMIT      {git_block['end_commit']}",
        "",
    ]

    cmds = receipt.get("commands_observed") or []
    if cmds:
        lines.append("Commands observed:")
        for c in cmds:
            if isinstance(c, dict):
                cmd_str = c.get("command", "(unknown)")
                task = c.get("task_type") or ""
                status = str(c.get("status") or "").upper()
                task_part = f" [{task}]" if task else ""
                lines.append(f"- {cmd_str}{task_part} → {status}")
            else:
                lines.append(f"- {c}")
    else:
        lines.append("Commands observed: (none)")
    lines.append("")

    lines.append("Outcome:")
    lines.append(str(receipt["outcome"]).upper())
    lines.append("")
    lines.append("Reliability memory updated.")
    lines.append(f"Drift: {receipt['drift']}")
    integ = receipt.get("integrity")
    if integ:
        status = integ["status"]
        chained = integ["chained_records"]
        broken = integ["broken_records"]
        gaps = integ["unsigned_gaps"]
        legacy = integ.get("legacy_unsigned", 0)
        lines.append(
            f"Integrity: {status} (chained={chained}, legacy={legacy},"
            f" broken={broken}, unsigned_gaps={gaps})"
        )
    return "\n".join(lines) + "\n"


def format_receipt_json(receipt: dict[str, Any]) -> str:
    """Format a receipt dict as canonical JSON."""
    return json.dumps(receipt, indent=2, sort_keys=True) + "\n"


def format_receipt_markdown(receipt: dict[str, Any]) -> str:
    """Format a receipt dict as GitHub-flavoured markdown for sharing."""
    agent = receipt["agent"]
    git_block = receipt["git"]
    outcome = str(receipt["outcome"]).upper()
    drift = receipt["drift"]

    lines = [
        "# Chimera Memory Receipt",
        "",
        "## Session",
        "| Field | Value |",
        "|---|---|",
        f"| session_id | `{receipt['session_id']}` |",
        f"| task | {receipt['task_label']} |",
        f"| agent | {agent['app']} |",
        f"| model | {agent['model']} |",
        f"| attribution | {agent['attribution']} / {agent['identity_source']} |",
        f"| outcome | **{outcome}** |",
        f"| drift | {drift} |",
        "",
        "## Git",
        "| Field | Value |",
        "|---|---|",
        f"| commit | `{git_block['end_commit']}` |",
        f"| files changed | {git_block['files_changed_during']} |",
        f"| dirty | {git_block['dirty']} |",
        "",
    ]

    cmds = receipt.get("commands_observed") or []
    if cmds:
        lines.append("## Commands Observed")
        lines.append("")
        lines.append("| Command | Task | Status | Exit |")
        lines.append("|---|---|---|---|")
        for c in cmds:
            if isinstance(c, dict):
                cmd = c.get("command", "(unknown)")
                task = c.get("task_type") or ""
                status = str(c.get("status") or "").upper()
                exit_code = c.get("exit_code", "")
                # Bound long commands in table display
                cmd_display = cmd if len(cmd) <= 80 else cmd[:77] + "..."
                lines.append(f"| `{cmd_display}` | {task} | {status} | {exit_code} |")
            else:
                lines.append(f"| `{c}` | | | |")
    else:
        lines.append("## Commands Observed")
        lines.append("")
        lines.append("_none_")

    integ = receipt.get("integrity")
    if integ:
        lines += [
            "",
            "## Integrity",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| Status | {integ['status']} |",
            f"| Claims total | {integ['claims_total']} |",
            f"| Legacy unsigned | {integ.get('legacy_unsigned', 0)} |",
            f"| Chained records | {integ['chained_records']} |",
            f"| Broken records | {integ['broken_records']} |",
            f"| Unsigned gaps | {integ['unsigned_gaps']} |",
        ]

    lines.append("")
    return "\n".join(lines) + "\n"


def format_receipt_github_summary(
    receipt: dict[str, Any],
    *,
    preflight_report: Any = None,
) -> str:
    """Compact GitHub Step Summary markdown — concise, no giant JSON, no secrets.

    Designed for writing to $GITHUB_STEP_SUMMARY in CI.
    Optionally includes a preflight advisory section.
    """
    agent = receipt.get("agent", {})
    outcome = str(receipt.get("outcome", "UNKNOWN")).upper()
    cmds = receipt.get("commands_observed") or []
    validated = sum(
        1 for c in cmds
        if isinstance(c, dict) and str(c.get("status", "")).upper() == "VALIDATED"
    )
    contradicted = sum(
        1 for c in cmds
        if isinstance(c, dict) and str(c.get("status", "")).upper() == "CONTRADICTED"
    )

    icon = "✅" if outcome == "PASSED" else "❌" if outcome in ("FAILED", "CONTRADICTED") else "⚠️"
    lines = [
        f"## {icon} Chimera Memory Receipt — {receipt.get('task_label', '(unnamed)')}",
        "",
        f"**Status:** `{outcome}` · **Agent:** `{agent.get('app', '?')}/{agent.get('model', '?')}` "
        f"· **Harness:** `{agent.get('harness_id', '?')}`",
        "",
        f"**Commands:** {len(cmds)} · ✅ {validated} validated · ❌ {contradicted} contradicted",
        "",
    ]

    if cmds:
        lines += ["| Command | Type | Status |", "|---|---|---|"]
        for c in cmds:
            if not isinstance(c, dict):
                continue
            cmd = c.get("command", "(unknown)")[:80]
            task = c.get("task_type") or ""
            st = str(c.get("status", "")).upper()
            badge = "✅" if st == "VALIDATED" else "❌"
            lines.append(f"| `{cmd}` | {task} | {badge} {st} |")
        lines.append("")

    # Show first failure witness if any
    for c in cmds:
        if not isinstance(c, dict):
            continue
        if str(c.get("status", "")).upper() == "CONTRADICTED":
            w = c.get("stderr_excerpt") or c.get("stdout_excerpt") or ""
            if w:
                excerpt = str(w).strip()[:200]
                lines += [
                    "<details><summary>Failure witness</summary>", "",
                    f"```\n{excerpt}\n```", "", "</details>", ""
                ]
            break

    integ = receipt.get("integrity")
    if integ:
        broken = integ.get("broken_records", 0)
        lines.append(f"**Integrity:** `{integ.get('status', '?')}` — {broken} broken record(s)")
        lines.append("")

    # Optional preflight section
    if preflight_report is not None:
        lines += [
            "---",
            "## 🔍 Preflight Advisory",
            "",
            "Advisory only — no routing/autonomy decision.",
            "",
            f"**Matching claims:** {preflight_report.matching_claim_count}  "
            f"**M2B readiness:** `{preflight_report.m2b_readiness_level}`",
            "",
        ]
        if preflight_report.recent_failures:
            lines.append(f"**Recent failures ({len(preflight_report.recent_failures)}):**")
            for f in preflight_report.recent_failures[:3]:
                origin = f.get("effective_failure_origin") or "unknown"
                lines.append(f"- `[{origin}]` {f.get('command', '')[:60]}")
            lines.append("")
        if preflight_report.recommended_checks:
            lines.append("**Recommended verification:**")
            for chk in preflight_report.recommended_checks[:4]:
                lines.append(f"- `{chk}`")
            lines.append("")

    lines.append("_Local receipt — not hosted/cloud. Data stays on this machine._")
    return "\n".join(lines) + "\n"
