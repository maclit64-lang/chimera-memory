"""Chimera Memory J1A: engine-ready event export.

Converts settled claims into neutral JSONL evidence events for later
ingestion by the Chimera engine or any downstream system.

Design constraints:
- stdlib only (json, pathlib, typing, datetime)
- no runtime engine, app, or substrate imports
- does not mutate the store
- deterministic event IDs (evt-{claim_id})
- settled claims only; unsettled claims are omitted
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from chimera_memory.storage import MemoryStore

SCHEMA_VERSION = 1
SOURCE = "chimera-memory"


def _safe_str(val: object) -> str | None:
    """Return a stripped string or None."""
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _claim_to_event(
    claim: Any,
    integrity_status: str = "UNKNOWN",
    errata_map: dict | None = None,
) -> dict[str, object]:
    """Convert a single settled Claim to an engine-ready event dict."""
    m = claim.metadata or {}
    evt_meta: dict[str, Any] = {}
    if claim.settlement and claim.settlement.events:
        evt_meta = claim.settlement.events[-1].metadata or {}

    wrapped_args: list[str] = list(evt_meta.get("wrapped_args") or [])
    git_block: dict[str, Any] = m.get("git") or {}

    # Outcome
    status_val = claim.claim_status.value if claim.claim_status else "unknown"
    exit_code = evt_meta.get("exit_code")

    # Timestamps
    ts: str | None = None
    if claim.temporal_seal:
        ct = claim.temporal_seal.claim_time
        ts = ct.isoformat() if ct else None

    return {
        "schema_version": SCHEMA_VERSION,
        "event_type": "memory.claim.settled",
        "event_id": f"evt-{claim.claim_id}",
        "source": SOURCE,
        "session_id": _safe_str(m.get("session_id")),
        "claim_id": claim.claim_id,
        "timestamp": ts,
        "agent": {
            "id": _safe_str(m.get("agent_id")),
            "model": _safe_str(m.get("model_version")),
            "harness_id": _safe_str(m.get("harness_id")),
            "attribution_confidence": _safe_str(m.get("attribution_confidence")),
            "identity_source": _safe_str(m.get("identity_source")),
        },
        "task": {
            "type": _safe_str(m.get("task_type")),
            "label": _safe_str(claim.title),
        },
        "command": {
            "args": wrapped_args,
            "display": " ".join(str(a) for a in wrapped_args) if wrapped_args else None,
        },
        "outcome": {
            "status": status_val.upper(),
            "exit_code": exit_code,
        },
        "witness": {
            "stdout_excerpt": _safe_str(evt_meta.get("stdout_excerpt", "")),
            "stderr_excerpt": _safe_str(evt_meta.get("stderr_excerpt", "")),
        },
        "git": {
            "branch": _safe_str(git_block.get("branch")),
            "commit": _safe_str(git_block.get("commit_sha")),
            "dirty": bool(git_block.get("dirty_state", False)),
            "files_changed": list(git_block.get("files_changed") or []),
        },
        "integrity": {
            "status": integrity_status,
        },
        "data_quality": {
            "failure_origin": m.get("failure_origin"),
            "verification_scope": m.get("verification_scope"),
            "scope_paths": m.get("scope_paths"),
            "scope_intent": m.get("scope_intent"),
            "repair_loop_id": m.get("repair_loop_id"),
            "repair_phase": m.get("repair_phase"),
            "repair_of_claim_id": m.get("repair_of_claim_id"),
            "baseline_claim_id": m.get("baseline_claim_id"),
            "residual_out_of_scope": m.get("residual_out_of_scope"),
        },
        "effective_data_quality": _effective_dq(claim, errata_map or {}),
    }


def _effective_dq(claim: Any, errata_map: dict) -> dict:
    """Return effective data quality block after errata corrections."""
    from chimera_memory.errata import effective_metadata as _em
    em = _em(claim, errata_map)
    eff = em["effective"]
    result: dict = {
        "failure_origin": eff.get("failure_origin"),
        "verification_scope": eff.get("verification_scope"),
        "errata_applied": em["errata_applied"],
    }
    if em["errata_applied"]:
        result["corrected_from"] = (claim.metadata or {}).get("failure_origin")
        result["errata_reason"] = em["errata_reason"]
    return result


def iter_engine_events(
    store: MemoryStore,
    *,
    failures_only: bool = False,
    clean_only: bool = False,
    session_id: str | None = None,
) -> Iterator[dict[str, object]]:
    """Yield engine-ready events for settled unique claims.

    filters (applied in order):
    - clean_only: only D0-clean attributed claims (uses shared read model)
    - session_id: only claims linked to this session
    - failures_only: only CONTRADICTED claims
    """
    from chimera_memory.integrity import integrity_report_to_summary, verify_integrity

    try:
        integrity_status = integrity_report_to_summary(
            verify_integrity(Path(store.memory_dir))
        )["status"]
    except Exception:
        integrity_status = "UNKNOWN"

    if clean_only:
        from chimera_memory.query import build_claim_read_model
        claims_to_export = build_claim_read_model(store).clean_claims
    else:
        from chimera_memory.query import latest_claims_from_records
        claims_to_export = [
            c for c in latest_claims_from_records(store.read_claims())
            if c.claim_status is not None
            and c.claim_status.value in ("validated", "contradicted")
        ]

    if session_id is not None:
        claims_to_export = [
            c for c in claims_to_export
            if (c.metadata or {}).get("session_id") == session_id
        ]

    if failures_only:
        from chimera_memory_types.knowledge import ClaimStatus
        claims_to_export = [
            c for c in claims_to_export
            if c.claim_status == ClaimStatus.CONTRADICTED
        ]

    # Load errata for effective_data_quality block
    from chimera_memory.errata import load_errata
    errata_map = load_errata(Path(store.memory_dir))

    for claim in claims_to_export:
        yield _claim_to_event(
            claim,
            integrity_status=str(integrity_status),
            errata_map=errata_map,
        )


def build_engine_events(
    store: MemoryStore,
    *,
    failures_only: bool = False,
    clean_only: bool = False,
    session_id: str | None = None,
) -> list[dict[str, object]]:
    """Return all engine events as a list."""
    return list(iter_engine_events(
        store,
        failures_only=failures_only,
        clean_only=clean_only,
        session_id=session_id,
    ))


def format_events_jsonl(events: Iterable[dict[str, object]]) -> str:
    """Format events as JSONL (one JSON object per line)."""
    return "\n".join(json.dumps(e, sort_keys=True) for e in events)
