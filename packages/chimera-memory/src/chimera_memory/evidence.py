"""Chimera Memory Evidence Bundle Export + Dry-Run Import.

Enables portable, local file-based evidence exchange between agents.

Rules:
- No raw secrets (redaction applied)
- No integrity.jsonl / index.sqlite / append_state.json
- Claim IDs preserved
- Dry-run import performs zero writes
- Write-capable import is not built in this slice
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from chimera_memory.storage import MemoryStore


from dataclasses import dataclass


@dataclass
class _ClaimProxy:
    """Minimal claim-like proxy built from bundle event data for M2B projection."""
    claim_id: str
    metadata: dict
    claim_status: object  # ClaimStatus enum

    @property
    def settlement(self) -> None:
        return None


def _events_to_claim_proxies(events: list[dict]) -> list[_ClaimProxy]:
    """Convert bundle events to claim proxies for M2B projection. Zero writes."""
    from chimera_memory_types.knowledge import ClaimStatus
    proxies = []
    for evt in events:
        cid = str(evt.get('claim_id', ''))
        if not cid:
            continue
        dq = evt.get('effective_data_quality') or evt.get('data_quality') or {}
        agent = evt.get('agent') or {}
        outcome_status = (evt.get('outcome') or {}).get('status', '').upper()
        metadata = {
            'failure_origin': dq.get('failure_origin'),
            'verification_scope': (
                dq.get('verification_scope')
                or (evt.get('data_quality') or {}).get('verification_scope')
            ),
            'scope_paths': (evt.get('data_quality') or {}).get('scope_paths'),
            'repair_loop_id': (evt.get('data_quality') or {}).get('repair_loop_id'),
            'repair_phase': (evt.get('data_quality') or {}).get('repair_phase'),
            'agent_id': agent.get('id'),
            'model_version': agent.get('model'),
            'harness_id': agent.get('harness_id'),
            'session_id': evt.get('session_id'),
            'attribution_confidence': agent.get('attribution_confidence'),
            'identity_source': agent.get('identity_source'),
            'task_type': (evt.get('task') or {}).get('type'),
        }
        if outcome_status == 'VALIDATED':
            status = ClaimStatus.VALIDATED
        elif outcome_status == 'CONTRADICTED':
            status = ClaimStatus.CONTRADICTED
        else:
            status = ClaimStatus.PROPOSED
        proxies.append(_ClaimProxy(claim_id=cid, metadata=metadata, claim_status=status))
    return proxies


SCHEMA_VERSION = 1
BUNDLE_README = """\
# Chimera Memory Evidence Bundle

Portable evidence artifact for cross-agent DQ analysis.

Contents:
  manifest.json  - bundle metadata and provenance summary
  events.jsonl   - exported settled clean claims (JSONL, one event per line)
  errata.jsonl   - errata corrections if any exist (optional)

Rules:
  - All witness/command output is redacted
  - Claim IDs are preserved original UUIDs
  - integrity.jsonl is intentionally excluded (chain is local-only)
  - index.sqlite / append_state.json are excluded (derived caches)
  - This bundle does not authorise write import; use --dry-run first

Importing:
  chimera-memory evidence import <bundle-dir> --dry-run
"""

_REDACTION_PATTERNS = [
    "ghp_", "github_pat_", "sk-", "AKIA", "xoxb-", "xoxp-",
    "Bearer ", "password=", "api_key=", "token=", "secret=",
]


def _check_possible_secrets(events: list[dict[str, Any]]) -> list[str]:
    """Scan command/witness fields for common unredacted secret patterns."""
    found: list[str] = []
    for evt in events:
        cmd = evt.get("command") or {}
        witness = evt.get("witness") or {}
        text = " ".join([
            str(cmd.get("display") or ""),
            str(witness.get("stdout_excerpt") or ""),
            str(witness.get("stderr_excerpt") or ""),
        ])
        for pat in _REDACTION_PATTERNS:
            if pat.lower() in text.lower():
                cid = str(evt.get("claim_id", "?"))[:12]
                found.append(f"Possible unredacted secret '{pat}' in event {cid}")
    return found


# ---------------------------------------------------------------------------
# Bundle export
# ---------------------------------------------------------------------------


def build_evidence_bundle(
    store: MemoryStore,
    output_dir: Path,
) -> dict[str, Any]:
    """Export clean claims and errata into a portable evidence bundle directory."""
    from chimera_memory.errata import load_errata
    from chimera_memory.export import build_engine_events, format_events_jsonl

    output_dir.mkdir(parents=True, exist_ok=True)

    def _write(name: str, content: str) -> None:
        tmp = output_dir / f".{name}.tmp"
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, output_dir / name)

    events = build_engine_events(store, clean_only=True)
    events_jsonl = format_events_jsonl(events)
    if events_jsonl:
        _write("events.jsonl", events_jsonl + "\n")

    agent_ids: set[str] = set()
    model_versions: set[str] = set()
    harness_ids: set[str] = set()
    for evt in events:
        _raw_agent = evt.get("agent") or {}
        ab: dict[str, Any] = _raw_agent if isinstance(_raw_agent, dict) else {}  # type: ignore[assignment]
        if ab.get("id"):
            agent_ids.add(str(ab["id"]))
        if ab.get("model"):
            model_versions.add(str(ab["model"]))
        if ab.get("harness_id"):
            harness_ids.add(str(ab["harness_id"]))

    errata_map = load_errata(store.memory_dir)
    errata_count = 0
    if errata_map:
        exported_ids = {str(evt.get("claim_id")) for evt in events}
        relevant_errata = [rec for cid, rec in errata_map.items() if cid in exported_ids]
        if relevant_errata:
            errata_content = "\n".join(
                json.dumps(r, sort_keys=True) for r in relevant_errata
            )
            _write("errata.jsonl", errata_content + "\n")
            errata_count = len(relevant_errata)

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "source_agent_ids": sorted(agent_ids),
        "source_model_versions": sorted(model_versions),
        "source_harness_ids": sorted(harness_ids),
        "claim_count": len(events),
        "event_count": len(events),
        "errata_count": errata_count,
        "redaction_note": "Command args and witness excerpts are redacted.",
        "local_only_note": (
            "integrity.jsonl, index.sqlite, append_state.json excluded. "
            "Import is dry-run only in this version."
        ),
    }
    _write("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
    _write("README.md", BUNDLE_README)

    files = sorted(p.name for p in output_dir.iterdir() if not p.name.startswith("."))
    print(f"Evidence bundle written to {output_dir}/ ({len(files)} files): {', '.join(files)}")
    return manifest


# ---------------------------------------------------------------------------
# Dry-run import inspection
# ---------------------------------------------------------------------------


def _build_m2b_preview(
    current: Any,
    projected: Any,
    all_dupes: bool,
) -> dict[str, Any]:
    """Build full-parity M2B preview dict from real M2BReadinessReport objects."""
    def _report_dict(r: Any) -> dict[str, Any]:
        if r is None:
            return {"readiness_level": "unknown", "m2b_ready": False,
                    "blockers": [], "warnings": []}
        return {
            "readiness_level": r.readiness_level,
            "m2b_ready": r.m2b_ready,
            "blockers": r.blockers[:],
            "warnings": r.warnings[:],
            "evaluation_mode": getattr(r, "evaluation_mode", "unknown"),
            "dq_cohort_summary": dict(r.dq_cohort_summary),
            "readiness_evaluation_summary": dict(r.readiness_evaluation_summary),
            "repair_loop_summary": dict(r.repair_loop_summary),
        }

    cur = _report_dict(current)
    proj = _report_dict(projected)
    cur_cs = current.dq_cohort_summary if current else {}
    proj_cs = projected.dq_cohort_summary if projected else {}
    cur_ev = current.readiness_evaluation_summary if current else {}
    proj_ev = projected.readiness_evaluation_summary if projected else {}
    cur_rl = current.repair_loop_summary if current else {}
    proj_rl = projected.repair_loop_summary if projected else {}

    return {
        "current": cur,
        "projected": proj,
        "delta": {
            "all_duplicates": all_dupes,
            "comparable_groups_delta": (
                proj_ev.get("comparable_groups", 0) - cur_ev.get("comparable_groups", 0)
            ),
            "organic_real_delta": (
                proj_cs.get("organic_real", 0) - cur_cs.get("organic_real", 0)
            ),
            "organic_real_failed_delta": (
                proj_cs.get("organic_real_failed", 0) - cur_cs.get("organic_real_failed", 0)
            ),
            "repair_loop_delta": (
                proj_rl.get("complete_loops", 0) - cur_rl.get("complete_loops", 0)
            ),
        },
        "notes": (
            "Full parity M2B preview using same gate logic as chimera-memory m2b-readiness. "
            "Includes repair-loop projection (repair_loop_id + repair_phase from events). "
            "Dry-run only — no ledger mutation."
        ),
    }


def dry_run_import(
    store: MemoryStore,
    bundle_dir: Path,
) -> dict[str, Any]:
    """Inspect an evidence bundle and report what would change. Zero writes."""
    errors: list[str] = []
    warnings: list[str] = []

    manifest_path = bundle_dir / "manifest.json"
    if not manifest_path.exists():
        return {"schema_version": SCHEMA_VERSION, "writes_performed": False,
                "errors": ["manifest.json not found — not a valid evidence bundle"]}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"schema_version": SCHEMA_VERSION, "writes_performed": False,
                "errors": [f"manifest.json invalid JSON: {exc}"]}

    bundle_schema = manifest.get("schema_version", 0)
    if bundle_schema > SCHEMA_VERSION:
        warnings.append(f"Bundle schema_version {bundle_schema} > local {SCHEMA_VERSION}.")

    events: list[dict[str, Any]] = []
    events_path = bundle_dir / "events.jsonl"
    if events_path.exists():
        for i, raw_line in enumerate(events_path.read_text(encoding="utf-8").splitlines()):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                evt = json.loads(raw_line)
                if not isinstance(evt.get("claim_id"), str):
                    errors.append(f"events.jsonl line {i+1}: missing claim_id")
                    continue
                events.append(evt)
            except json.JSONDecodeError as exc:
                errors.append(f"events.jsonl line {i+1}: {exc}")

    declared = manifest.get("event_count", 0)
    if declared and len(events) != declared:
        warnings.append(f"Manifest declares {declared} events but {len(events)} parsed.")

    bundle_errata: list[dict[str, Any]] = []
    errata_path = bundle_dir / "errata.jsonl"
    if errata_path.exists():
        for raw_line in errata_path.read_text(encoding="utf-8").splitlines():
            raw_line = raw_line.strip()
            if raw_line:
                try:
                    bundle_errata.append(json.loads(raw_line))
                except json.JSONDecodeError:
                    warnings.append("errata.jsonl: could not parse some lines")

    mec = manifest.get("errata_count", 0)
    if mec > 0 and not errata_path.exists():
        warnings.append(f"Manifest declares {mec} errata but errata.jsonl is missing.")

    # Field validation warnings
    n_agent = sum(1 for e in events if not (e.get("agent") or {}).get("id"))
    n_model = sum(1 for e in events if not (e.get("agent") or {}).get("model"))
    n_harness = sum(1 for e in events if not (e.get("agent") or {}).get("harness_id"))
    n_dq = sum(1 for e in events
               if not e.get("data_quality") and not e.get("effective_data_quality"))
    n_edq = sum(1 for e in events if not e.get("effective_data_quality"))
    for n, msg in [
        (n_agent, "missing agent_id"),
        (n_model, "missing model_version"),
        (n_harness, "missing harness_id"),
        (n_dq, "missing DQ metadata"),
        (n_edq, "missing effective_data_quality"),
    ]:
        if n:
            warnings.append(f"{n} event(s) {msg}.")

    warnings.extend(_check_possible_secrets(events))

    existing_ids: set[str] = set()
    try:
        for c in store.read_claims():
            existing_ids.add(c.claim_id)
    except Exception:
        warnings.append("Could not read existing claims for deduplication check.")

    new_ids_set = {
        str(e["claim_id"]) for e in events if str(e.get("claim_id")) not in existing_ids
    }
    dup_ids_set = {
        str(e["claim_id"]) for e in events if str(e.get("claim_id")) in existing_ids
    }

    incoming_am: Counter[str] = Counter()
    new_am: Counter[str] = Counter()
    dup_am: Counter[str] = Counter()
    origin_ctr: Counter[str] = Counter()
    scope_ctr: Counter[str] = Counter()

    for evt in events:
        dq = evt.get("effective_data_quality") or evt.get("data_quality") or {}
        origin_ctr[str(dq.get("failure_origin") or "unknown")] += 1
        scope_ctr[str((evt.get("data_quality") or {}).get("verification_scope") or "unknown")] += 1
        ag: dict[str, Any] = evt.get("agent") or {}
        am_key = f"{ag.get('id','?')}/{ag.get('model','?')}"
        incoming_am[am_key] += 1
        cid = str(evt.get("claim_id", ""))
        (new_am if cid in new_ids_set else dup_am)[am_key] += 1

    # --- Full parity M2B preview using real compute_m2b_readiness ---
    local_am: Counter[str] = Counter()
    all_dupes = len(new_ids_set) == 0
    current_report = None
    projected_report = None
    new_am_groups: set[str] = set()

    try:
        from chimera_memory.m2b_readiness import compute_m2b_readiness
        from chimera_memory.query import build_claim_read_model

        # Local clean claims for group tracking
        rm = build_claim_read_model(store)
        for c in rm.clean_claims:
            m = c.metadata or {}
            local_am[f"{m.get('agent_id','?')}/{m.get('model_version','?')}"] += 1

        # Current readiness (no extra claims)
        current_report = compute_m2b_readiness(store)

        if not all_dupes:
            # Build synthetic claim proxies for new events only
            new_events = [e for e in events if str(e.get("claim_id","")) in new_ids_set]
            proxies = _events_to_claim_proxies(new_events)
            # Projected readiness = local + incoming new claims
            projected_report = compute_m2b_readiness(store, extra_clean_claims=proxies)
            new_am_groups = set(new_am.keys()) - set(local_am.keys())
            if new_am_groups:
                warnings.append(
                    f"New agent/model groups would be added: {sorted(new_am_groups)}. "
                    "comparable_groups count may increase."
                )
        else:
            projected_report = current_report
    except Exception as exc:
        warnings.append(f"M2B preview computation failed: {exc}")

    would_change = (
        not all_dupes
        and current_report is not None
        and projected_report is not None
        and current_report.readiness_level != projected_report.readiness_level
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "writes_performed": False,
        "source_manifest": manifest,
        "new_claim_count": len(new_ids_set),
        "duplicate_claim_count": len(dup_ids_set),
        "event_count": len(events),
        "errata_count": len(bundle_errata),
        "agent_model_groups": dict(incoming_am),
        "dq_summary": {
            "failure_origin_counts": dict(origin_ctr),
            "verification_scope_counts": dict(scope_ctr),
        },
        "provenance_summary": {
            "local_claim_count": sum(local_am.values()),
            "incoming_event_count": len(events),
            "new_claim_count": len(new_ids_set),
            "duplicate_claim_count": len(dup_ids_set),
            "source_agents": sorted(manifest.get("source_agent_ids", [])),
            "source_models": sorted(manifest.get("source_model_versions", [])),
            "source_harnesses": sorted(manifest.get("source_harness_ids", [])),
            "incoming_agent_model_groups": dict(incoming_am),
            "local_agent_model_groups": dict(local_am),
            "new_agent_model_groups": dict(new_am),
            "duplicate_agent_model_groups": dict(dup_am),
        },
        "m2b_preview": _build_m2b_preview(current_report, projected_report, all_dupes),
        "would_change_m2b_readiness": would_change,
        "warnings": warnings,
        "errors": errors,
    }


def format_dry_run_text(result: dict[str, Any]) -> str:
    lines = [
        "Chimera Memory Evidence Import — Dry Run",
        "dry-run only — no ledger mutation — writes_performed: False",
        "",
    ]
    if result.get("errors"):
        lines.append("Errors:")
        for e in result["errors"]:
            lines.append(f"  ✗ {e}")
        return "\n".join(lines) + "\n"

    mf = result.get("source_manifest", {})
    lines += [
        f"Bundle exported: {mf.get('exported_at', 'unknown')}",
        f"Source agents:   {mf.get('source_agent_ids', [])}",
        f"Source models:   {mf.get('source_model_versions', [])}",
        "",
        f"Events in bundle:     {result['event_count']}",
        f"New claims:           {result['new_claim_count']}",
        f"Duplicates (skipped): {result['duplicate_claim_count']}",
        f"Errata records:       {result['errata_count']}",
        "",
    ]

    preview = result.get("m2b_preview", {})
    if preview:
        cur = (preview.get("current") or {}).get("readiness_level", "?")
        proj = (preview.get("projected") or {}).get("readiness_level", "?")
        delta = preview.get("delta") or {}
        suffix = " (unchanged — all duplicates)" if delta.get("all_duplicates") else ""
        lines.append(f"M2B readiness:  {cur} → {proj}{suffix}")
        cur_cs = (preview.get("current") or {}).get("dq_cohort_summary") or {}
        proj_cs = (preview.get("projected") or {}).get("dq_cohort_summary") or {}
        cur_ev = (preview.get("current") or {}).get("readiness_evaluation_summary") or {}
        proj_ev = (preview.get("projected") or {}).get("readiness_evaluation_summary") or {}
        lines += [
            "  comparable_groups: " +
            f"{cur_ev.get('comparable_groups','?')} → {proj_ev.get('comparable_groups','?')}",
            "  organic_real:      " +
            f"{cur_cs.get('organic_real','?')} → {proj_cs.get('organic_real','?')}",
            "",
        ]
        proj_blockers = (preview.get("projected") or {}).get("blockers", [])
        if proj_blockers:
            lines.append("Projected blockers:")
            for b in proj_blockers:
                lines.append(f"  - {b}")
            lines.append("")

    if result.get("warnings"):
        lines.append("Warnings:")
        for w in result["warnings"]:
            lines.append(f"  - {w}")
        lines.append("")

    lines.append("Agent/model groups in bundle:")
    for am, cnt in sorted(result.get("agent_model_groups", {}).items()):
        lines.append(f"  {am}: {cnt} claim(s)")
    lines += ["", "dry-run only — no ledger mutation"]
    return "\n".join(lines) + "\n"
