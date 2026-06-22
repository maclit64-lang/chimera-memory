from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chimera_memory.adapters.git import capture_git_evidence
from chimera_memory.adapters.pytest_ci import run_command, run_pytest
from chimera_memory.data_quality import (
    K_BASELINE_CLAIM_ID,
    K_FAILURE_ORIGIN,
    K_REPAIR_LOOP_ID,
    K_REPAIR_OF_CLAIM_ID,
    K_REPAIR_PHASE,
    K_RESIDUAL_OUT_OF_SCOPE,
    K_SCOPE_INTENT,
    K_SCOPE_PATHS,
    K_VERIFICATION_SCOPE,
    validate_failure_origin,
    validate_repair_phase,
    validate_verification_scope,
)
from chimera_memory.drift import detect_drift
from chimera_memory.ledger import build_dogfood_status, export_report, record_claim, settle_claim
from chimera_memory.receipt import (
    build_receipt,
    format_receipt_json,
    format_receipt_markdown,
    format_receipt_text,
)
from chimera_memory.redaction import redact as _redact
from chimera_memory.session import FinalStatus, Session
from chimera_memory.session_lifecycle import end_session, start_session
from chimera_memory.storage import MemoryStore
from chimera_memory_types.finding import EvidenceRefType

_GITIGNORE_ENTRY = ".chimera-memory/"


def _ensure_gitignore(root: Path) -> None:
    """Ensure .chimera-memory/ is in .gitignore. Idempotent."""
    gitignore = root / ".gitignore"
    if gitignore.exists():
        text = gitignore.read_text(encoding="utf-8")
        lines = text.splitlines()
        for line in lines:
            if line.strip() == _GITIGNORE_ENTRY.rstrip("/") or line.strip() == _GITIGNORE_ENTRY:
                return  # already present
        sep = "" if text.endswith("\n") else "\n"
        gitignore.write_text(text + sep + _GITIGNORE_ENTRY + "\n", encoding="utf-8")
        print(f"Added {_GITIGNORE_ENTRY} to .gitignore")
    else:
        gitignore.write_text(_GITIGNORE_ENTRY + "\n", encoding="utf-8")
        print(f"Created .gitignore with {_GITIGNORE_ENTRY}")


_KNOWN_ORIGINS_FOR_HYGIENE = {
    "organic_real", "controlled_real", "invocation_artifact",
    "test_first_contract", "synthetic",
}
_TEST_FIXTURE_ORIGINS = {"test_first_contract", "synthetic"}


def _build_evidence_hygiene(store: MemoryStore) -> dict[str, object]:
    """Compute evidence hygiene metrics from existing claims. Read-only."""
    from chimera_memory.data_quality import (
        K_FAILURE_ORIGIN,
        K_REPAIR_LOOP_ID,
        K_REPAIR_PHASE,
        K_SCOPE_PATHS,
    )
    from chimera_memory.errata import effective_failure_origin, load_errata
    from chimera_memory.query import latest_claims_from_records
    from chimera_memory_types.knowledge import ClaimStatus

    raw = store.read_claims()
    unique = latest_claims_from_records(raw)
    settled = [c for c in unique if c.claim_status is not None]

    errata = load_errata(store.memory_dir)

    total = len(settled)
    scoped = 0
    unknown_origin = 0
    repair_phase_no_loop = 0
    test_fixture = 0
    invocation_artifact = 0

    # Repair loop tracking: loop_id -> set of repair phases with VALIDATED same_scope_after_fix
    loop_has_contradiction: dict[str, bool] = {}
    loop_has_ssaf_validated: dict[str, bool] = {}

    for c in settled:
        m = c.metadata or {}

        # Scoped?
        sp = m.get(K_SCOPE_PATHS)
        if sp and (isinstance(sp, list) and sp) or (isinstance(sp, str) and sp):
            scoped += 1

        # Failure origin
        fo = effective_failure_origin(c, errata) or m.get(K_FAILURE_ORIGIN) or ""
        if not fo or fo not in _KNOWN_ORIGINS_FOR_HYGIENE:
            unknown_origin += 1
        if fo in _TEST_FIXTURE_ORIGINS:
            test_fixture += 1
        if fo == "invocation_artifact":
            invocation_artifact += 1

        # Repair phase without loop id
        rp = m.get(K_REPAIR_PHASE)
        rl = m.get(K_REPAIR_LOOP_ID)
        if rp and rp != "none" and not rl:
            repair_phase_no_loop += 1

        # Repair loop completeness
        if rl:
            if c.claim_status == ClaimStatus.CONTRADICTED:
                loop_has_contradiction[rl] = True
            if (c.claim_status == ClaimStatus.VALIDATED
                    and rp == "same_scope_after_fix"):
                loop_has_ssaf_validated[rl] = True

    all_loop_ids = set(loop_has_contradiction) | set(loop_has_ssaf_validated)
    complete_ids = {
        lid for lid in all_loop_ids
        if loop_has_contradiction.get(lid) and loop_has_ssaf_validated.get(lid)
    }
    open_ids = sorted(all_loop_ids - complete_ids)

    ratio = round(scoped / total, 2) if total > 0 else 0.0

    return {
        "total_claims": total,
        "scoped_claim_count": scoped,
        "unscoped_claim_count": total - scoped,
        "scoped_claim_ratio": ratio,
        "unknown_failure_origin_count": unknown_origin,
        "repair_phase_without_loop_count": repair_phase_no_loop,
        "open_repair_loop_count": len(open_ids),
        "open_repair_loop_ids": open_ids,
        "complete_repair_loop_count": len(complete_ids),
        "test_fixture_claim_count": test_fixture,
        "invocation_artifact_count": invocation_artifact,
    }


def _build_next_actions(hygiene: dict[str, Any]) -> list[str]:
    """Return actionable remediation items based on hygiene metrics."""
    actions: list[str] = []
    unscoped = int(hygiene.get("unscoped_claim_count") or 0)
    unknown_fo = int(hygiene.get("unknown_failure_origin_count") or 0)
    open_ids: list[str] = list(hygiene.get("open_repair_loop_ids") or [])
    rp_no_loop = int(hygiene.get("repair_phase_without_loop_count") or 0)
    total = int(hygiene.get("total_claims") or 0)
    scoped = int(hygiene.get("scoped_claim_count") or 0)

    if unscoped > 0:
        actions.append("Add --scope-path to future wrap commands.")
    if unknown_fo > 0:
        actions.append(
            f"Set --failure-origin on {unknown_fo} claim(s) "
            f"(run: chimera-memory agent-guide --agent generic)."
        )
    for lid in open_ids[:3]:
        actions.append(
            f"Complete repair loop {lid} with --repair-phase same_scope_after_fix.\n"
            f"  Run: chimera-memory repair-loops for the exact wrap command template."
        )
    if rp_no_loop > 0:
        actions.append(
            f"Add --repair-loop-id to {rp_no_loop} wrap command(s) that use --repair-phase."
        )
    if total > 0 and scoped == 0:
        actions.append(
            "Run: chimera-memory template dogfood --scope-path <your-package>"
        )
    return actions


def _doctor(parsed: argparse.Namespace) -> int:
    """Read-only health check for the local chimera-memory store."""
    from chimera_memory.errata import effective_failure_origin, load_errata
    from chimera_memory.integrity import verify_integrity

    root = Path.cwd()
    memory_dir = root / ".chimera-memory"
    checks: list[dict[str, object]] = []
    warnings: list[str] = []
    critical: list[str] = []

    # 1. Initialized?
    initialized = memory_dir.exists()
    msg = "initialized" if initialized else "not initialized — run: chimera-memory init"
    checks.append({"name": "initialized", "ok": initialized, "message": msg})
    if not initialized:
        critical.append("not initialized")

    # 2. .gitignore entry
    gitignore = root / ".gitignore"
    gitignore_ok = False
    if gitignore.exists():
        text = gitignore.read_text(encoding="utf-8")
        gitignore_ok = any(
            ln.strip() in (_GITIGNORE_ENTRY, _GITIGNORE_ENTRY.rstrip("/"))
            for ln in text.splitlines()
        )
    checks.append({"name": "gitignore", "ok": gitignore_ok,
                   "message": ".gitignore contains .chimera-memory/" if gitignore_ok
                   else ".chimera-memory/ not in .gitignore — run: chimera-memory init"})
    if not gitignore_ok:
        warnings.append(".chimera-memory/ not in .gitignore")

    # 3. Active session
    active_session = None
    if initialized:
        try:
            store = MemoryStore.from_paths(root=root)
            active_session = store.current_session()
        except Exception:
            pass
    has_session = active_session is not None
    checks.append({"name": "active_session", "ok": has_session,
                   "message": f"active session: {(active_session or {}).get('session_id', '')}"
                   if has_session else "no active session"})
    if not has_session:
        warnings.append("no active session")

    # 4. Claims count
    unique_claims = 0
    settled_claims = 0
    if initialized:
        try:
            status = build_dogfood_status(root=root)
            unique_claims = status.get("unique_claims", 0)
            settled_claims = status.get("settled_unique_claims", 0)
        except Exception:
            pass
    checks.append({"name": "claims", "ok": True,
                   "message": f"{settled_claims} settled claims ({unique_claims} unique)"})

    # 5. Integrity
    integrity_status = "UNKNOWN"
    broken = 0
    if initialized:
        try:
            report = verify_integrity(memory_dir)
            integrity_status = report.status
            broken = report.broken_records
        except Exception:
            integrity_status = "ERROR"
    integrity_ok = integrity_status in ("OK", "LEGACY_UNSIGNED") and broken == 0
    checks.append({"name": "integrity", "ok": integrity_ok,
                   "message": f"integrity: {integrity_status}, broken: {broken}"})
    if not integrity_ok:
        critical.append(f"integrity {integrity_status}, broken: {broken}")

    # 6. M2B readiness + blockers
    m2b_level = "unknown"
    m2b_blockers: list[str] = []
    if initialized:
        try:
            from chimera_memory.m2b_readiness import compute_m2b_readiness
            store3 = MemoryStore.from_paths(root=root)
            rpt = compute_m2b_readiness(store3)
            m2b_level = rpt.readiness_level
            m2b_blockers = list(rpt.blockers)
        except Exception:
            try:
                st = build_dogfood_status(root=root) or {}
                m2b_level = st.get("m2b_readiness_level", "unknown")
            except Exception:
                pass
    checks.append({"name": "m2b_readiness", "ok": True,
                   "message": f"M2B readiness: {m2b_level}",
                   "blockers": m2b_blockers})

    # 7–8. Failure counts by origin — uses settled claim read model (errata-aware)
    failure_counts: dict[str, int] = {}
    if initialized:
        try:
            from chimera_memory.query import build_claim_read_model
            store2 = MemoryStore.from_paths(root=root)
            errata = load_errata(store2.memory_dir)
            rm = build_claim_read_model(store2)
            for claim in rm.failures:
                fo = effective_failure_origin(claim, errata)
                if fo:
                    failure_counts[fo] = failure_counts.get(fo, 0) + 1
        except Exception:
            pass
    organic_failed = failure_counts.get("organic_real", 0)
    checks.append({"name": "organic_failures", "ok": True,
                   "message": f"organic_real failures: {organic_failed}"})

    # 9. Evidence hygiene
    hygiene: dict[str, Any] = {}
    next_actions: list[str] = []
    if initialized:
        try:
            store_h = MemoryStore.from_paths(root=root)
            hygiene = _build_evidence_hygiene(store_h)
            next_actions = _build_next_actions(hygiene)
            # Hygiene problems are warnings, not critical
            _has_hygiene_issues = (
                hygiene.get("unscoped_claim_count", 0)
                or hygiene.get("unknown_failure_origin_count", 0)
            )
            if _has_hygiene_issues and "evidence hygiene issues" not in warnings:
                warnings.append("evidence hygiene issues detected")
        except Exception:
            pass

    # Overall status
    if critical:
        overall = "critical"
        exit_code = 2
    elif warnings:
        overall = "warnings"
        exit_code = 1
    else:
        overall = "healthy"
        exit_code = 0

    # Next step suggestion
    next_steps: list[str] = []
    if not initialized:
        next_steps.append("chimera-memory init")
    if not has_session and initialized:
        next_steps.append(
            "chimera-memory session start --branch <branch> --task-label <label>"
            " --agent <agent> --model <model> --harness-id <id>"
        )
    if not gitignore_ok and initialized:
        next_steps.append("chimera-memory init  # adds .chimera-memory/ to .gitignore")

    use_json = getattr(parsed, "json", False)
    if use_json:
        payload = {
            "schema_version": "1",
            "overall_status": overall,
            "exit_code": exit_code,
            "checks": checks,
            "counts": {
                "unique_claims": unique_claims,
                "settled_claims": settled_claims,
                "organic_real_failures": organic_failed,
                "failure_by_origin": failure_counts,
                "m2b_readiness_level": m2b_level,
                "m2b_blockers": m2b_blockers,
            },
            "warnings": warnings,
            "critical": critical,
            "next_steps": next_steps,
            "evidence_hygiene": hygiene,
            "next_actions": next_actions,
        }
        print(json.dumps(payload, sort_keys=True))
    else:
        print("Chimera Memory Doctor")
        print(f"Status: {overall}\n")
        print("Checks:")
        for c in checks:
            is_crit = any(str(c["name"]) in str(x) for x in critical)
            sym = "✓" if c["ok"] else ("✗" if is_crit else "⚠")
            print(f"  {sym} {c['message']}")
            if c["name"] == "m2b_readiness" and m2b_blockers:
                for b in m2b_blockers:
                    print(f"    ↳ {b}")

        if hygiene:
            total_c = int(hygiene.get("total_claims", 0))
            scoped_c = int(hygiene.get("scoped_claim_count", 0))
            ratio_pct = int(round(float(hygiene.get("scoped_claim_ratio", 0.0)) * 100))
            unscoped_c = int(hygiene.get("unscoped_claim_count", 0))
            unk_fo = int(hygiene.get("unknown_failure_origin_count", 0))
            rp_no_loop = int(hygiene.get("repair_phase_without_loop_count", 0))
            open_loops = int(hygiene.get("open_repair_loop_count", 0))
            open_ids = list(hygiene.get("open_repair_loop_ids", []))  # type: ignore[arg-type]
            complete_loops = int(hygiene.get("complete_repair_loop_count", 0))
            test_fix = int(hygiene.get("test_fixture_claim_count", 0))
            inv_art = int(hygiene.get("invocation_artifact_count", 0))

            print("\nEvidence Hygiene:")
            sym = "✓" if unscoped_c == 0 else "!"
            print(f"  {sym} scoped claims: {scoped_c}/{total_c} ({ratio_pct}%)")
            if unscoped_c:
                print(f"  ! unscoped claims: {unscoped_c}")
            sym = "✓" if unk_fo == 0 else "!"
            print(f"  {sym} unknown failure_origin: {unk_fo} claim(s)")
            sym = "✓" if rp_no_loop == 0 else "!"
            print(f"  {sym} repair_phase without loop_id: {rp_no_loop}")
            if open_loops:
                ids_str = ": " + ", ".join(open_ids) if open_ids else ""
                print(f"  ! open repair loops: {open_loops}{ids_str}")
            else:
                print("  ✓ open repair loops: 0")
            print(f"  ✓ complete repair loops: {complete_loops}")
            print(f"  ✓ test/synthetic claims: {test_fix} (not organic_real)")
            print(f"  ✓ invocation_artifact claims: {inv_art}")

        if next_actions:
            print("\nNext actions:")
            for na in next_actions:
                print(f"  - {na}")

        print()
        print("Not built: M2B scoring · model routing · hosted/cloud sync · write-import")
        if next_steps:
            print("\nNext steps:")
            for ns in next_steps:
                print(f"  {ns}")

    return exit_code


def _dq_summary(parsed: argparse.Namespace) -> int:
    """Read-only DQ classification summary."""
    from chimera_memory.data_quality import K_FAILURE_ORIGIN, K_REPAIR_PHASE, K_VERIFICATION_SCOPE
    from chimera_memory.errata import effective_failure_origin, load_errata
    from chimera_memory.query import build_claim_read_model

    root = Path.cwd()
    store = MemoryStore.from_paths(root=root)
    errata_map = load_errata(store.memory_dir)
    rm = build_claim_read_model(store)

    all_claims = rm.clean_claims + rm.failures
    failure_origin_raw: dict[str, int] = {}
    failure_origin_eff: dict[str, int] = {}
    verification_scope: dict[str, int] = {}
    repair_phase: dict[str, int] = {}

    for c in all_claims:
        m = c.metadata or {}
        fo_raw = m.get(K_FAILURE_ORIGIN) or "unknown"
        failure_origin_raw[fo_raw] = failure_origin_raw.get(fo_raw, 0) + 1
        fo_eff = effective_failure_origin(c, errata_map) or "unknown"
        failure_origin_eff[fo_eff] = failure_origin_eff.get(fo_eff, 0) + 1
        vs = m.get(K_VERIFICATION_SCOPE) or "unknown"
        verification_scope[vs] = verification_scope.get(vs, 0) + 1
        rp = m.get(K_REPAIR_PHASE) or "none"
        repair_phase[rp] = repair_phase.get(rp, 0) + 1

    # Legacy unlabeled = claims with no failure_origin in raw metadata
    legacy_count = failure_origin_raw.get("unknown", 0)

    payload = {
        "schema_version": "1",
        "total_claims": len(all_claims),
        "errata_applied_count": len(errata_map),
        "legacy_unlabeled_claims": legacy_count,
        "legacy_exclusion_reason": (
            "Legacy claims predate DQ metadata and are not backfilled automatically. "
            "They are excluded from DQ-cohort readiness gates."
        ),
        "failure_origin_raw": dict(sorted(failure_origin_raw.items())),
        "failure_origin_effective": dict(sorted(failure_origin_eff.items())),
        "verification_scope": dict(sorted(verification_scope.items())),
        "repair_phase": dict(sorted(repair_phase.items())),
    }

    use_json = getattr(parsed, "json", False)
    if use_json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print("Chimera Memory DQ Summary\n")
        print(f"Total claims:          {payload['total_claims']}")
        print(f"Legacy unlabeled:      {legacy_count}")
        print(f"Errata applied:        {payload['errata_applied_count']}\n")
        print("Failure origin (effective, errata-applied):")
        for k, v in sorted(failure_origin_eff.items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}")
        print("\nVerification scope:")
        for k, v in sorted(verification_scope.items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}")
        print("\nRepair phase:")
        for k, v in sorted(repair_phase.items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}")
        print(
            "\nNote: Legacy claims are excluded from DQ-cohort readiness gates."
            "\n      They are not backfilled automatically."
        )
    return 0


def _get_version() -> str:
    try:
        from importlib.metadata import version as _version
        return _version("chimera-memory")
    except Exception:
        return "unknown"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chimera-memory",
        description=(
            "Chimera Memory — local-first reliability ledger for AI coding-agent work.\n\n"
            "Records what an agent tried, which command checked it, what happened,\n"
            "and what receipt proves it. All data stays on your machine."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"chimera-memory {_get_version()}"
    )
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="Initialise a local .chimera-memory/ store")
    init_parser.set_defaults(command="init")

    quickstart_parser = subparsers.add_parser(
        "quickstart", help="Show a guided first-run example (no writes)"
    )
    quickstart_parser.set_defaults(command="quickstart")

    demo_parser = subparsers.add_parser(
        "demo", help="Run a local demo showing the full value loop (safe, no network)"
    )
    demo_parser.add_argument(
        "--output-dir", dest="demo_output_dir",
        help="Directory to write demo artifacts (default: temp dir)",
    )
    demo_parser.set_defaults(command="demo")

    for command in ("record", "settle"):
        p = subparsers.add_parser(command, help=argparse.SUPPRESS)
        p.set_defaults(command=command)

    report_parser = subparsers.add_parser(
        "report",
        help="Show raw reliability groups (all claims including pre-attribution records).",
        description=(
            "Prints raw reliability groups by agent/model/task_type.\n"
            "Includes all settled claims, including pre-attribution records.\n"
            "For dogfood gate progress and clean-claim counts, use: chimera-memory status"
        ),
    )
    report_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    report_parser.set_defaults(command="report")

    drift_parser = subparsers.add_parser("drift", help="Show reliability drift advisory")
    drift_parser.add_argument("--by", default="model_version", help="Group by field")
    drift_parser.add_argument("--min-claims", type=int, default=30, help="Min claims for advisory")
    drift_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    drift_parser.set_defaults(command="drift")

    status_parser = subparsers.add_parser(
        "status",
        help="Show dogfood gate progress and clean-claim counts.",        description=(
            "Applies D0 clean-claim counting rules to show gate progress.\n"
            "Distinguishes raw store records from unique clean settled claims.\n"
            "Use this (not report) to check whether the M2 comparison gate is met.\n\n"
            "A claim is clean if it has: session_id, agent_id (not unknown-agent),\n"
            "model_version (may be 'unknown'), task_type, attribution_confidence,\n"
            "and identity_source."
        ),
    )
    status_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    status_parser.set_defaults(command="status")

    proof_debt_parser = subparsers.add_parser(
        "proof-debt",
        help="Summarize local claims/receipts that still need stronger evidence.",
        description=(
            "Lists local claims and receipts that still need stronger evidence: "
            "unsettled/contradicted claims, review-required receipts, and evidence "
            "quality / test-integrity / evidence-coverage warnings. Advisory and "
            "local-only — it scores evidence quality, not code correctness."
        ),
    )
    proof_debt_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    proof_debt_parser.add_argument("--memory-dir")
    proof_debt_parser.set_defaults(command="proof-debt")

    failures_parser = subparsers.add_parser(
        "failures",
        help="List CONTRADICTED claims with failure witnesses.",
        description=(
            "Shows only claims whose outcome was CONTRADICTED (exit code nonzero).\n"
            "VALIDATED claims are excluded.\n"
            "Each failure includes the command, exit code, agent, model, task_type,\n"
            "and any captured stdout/stderr excerpt."
        ),
    )
    failures_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    failures_parser.add_argument(
        "--failure-origin", dest="filter_failure_origin",
        help="Filter by failure_origin (e.g. organic_real, synthetic).",
    )
    failures_parser.add_argument(
        "--verification-scope", dest="filter_verification_scope",
        help="Filter by verification_scope (e.g. package, full_suite).",
    )
    failures_parser.add_argument(
        "--repair-loop-id", dest="filter_repair_loop_id",
        help="Filter by repair_loop_id.",
    )
    failures_parser.add_argument(
        "--repair-phase", dest="filter_repair_phase",
        help="Filter by repair_phase.",
    )
    failures_parser.set_defaults(command="failures")

    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify the local integrity chain for claim records.",        description=(
            "Checks the integrity chain in .chimera-memory/integrity.jsonl.\n"
            "Legacy records without chain entries are reported as LEGACY_UNSIGNED\n"
            "and are not treated as corruption — they predate this feature.\n"
            "New records covered by the chain are fully verified."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    verify_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    verify_parser.set_defaults(command="verify")

    export_parser = subparsers.add_parser(
        "export",
        help="Export settled evidence events as engine-ready JSONL.",
        description=(
            "Converts settled Chimera Memory claims into neutral JSONL evidence events.\n"
            "No network calls. Does not mutate the store.\n\n"
            "Outputs one JSON object per line to stdout or to --output file."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    export_parser.add_argument(
        "--output", metavar="PATH",
        help="Write JSONL to this file path instead of stdout",
    )
    export_parser.add_argument(
        "--failures-only", action="store_true",
        help="Export only CONTRADICTED (failed) claims",
    )
    export_parser.add_argument(
        "--clean-only", action="store_true",
        help="Export only fully attributed clean claims (D0 rules) — engine-safe",
    )
    export_parser.add_argument(
        "--session-id", metavar="SESSION_ID",
        help="Export only claims linked to this session",
    )
    export_parser.set_defaults(command="export")

    reliability_parser = subparsers.add_parser(
        "reliability",
        help=(
            "Show read-only raw ledger reliability summary by agent/model/task. "
            "Reports validation rates from settled clean claims. "
            "Does not rank models, route work, or make autonomy decisions."
        ),
    )
    reliability_parser.add_argument(
        "--json", action="store_true",
        help="Emit machine-readable JSON summary",
    )
    reliability_parser.add_argument(
        "--failure-origin", dest="rel_failure_origin",
        help="Filter by failure_origin (e.g. organic_real)",
    )
    reliability_parser.add_argument(
        "--verification-scope", dest="rel_verification_scope",
        help="Filter by verification_scope (e.g. package)",
    )
    reliability_parser.add_argument(
        "--repair-phase", dest="rel_repair_phase",
        help="Filter by repair_phase",
    )
    reliability_parser.add_argument(
        "--repair-loop-id", dest="rel_repair_loop_id",
        help="Filter by repair_loop_id",
    )
    reliability_parser.add_argument(
        "--organic-only", dest="rel_organic_only", action="store_true",
        help="Shorthand for --failure-origin organic_real",
    )
    reliability_parser.set_defaults(command="reliability")

    wrap_parser = subparsers.add_parser(
        "wrap",
        help="Run a command and record its VALIDATED/CONTRADICTED outcome as a claim.",
        description=(
            "Wraps a verification command and records the result as a sealed claim.\n\n"
            "Exit code 0  → VALIDATED\n"
            "Exit code >0 → CONTRADICTED (failure witness captured)\n\n"
            "Session metadata (agent, model, harness, attribution) is inherited\n"
            "from the active session unless explicitly overridden via flags.\n\n"
            "For generic (non-pytest) commands, use -- before the command:\n"
            "  chimera-memory wrap --task-type lint -- uv run ruff check .\n"
            "  chimera-memory wrap --task-type type -- uv run mypy src/\n\n"
            "For pytest commands, -- is not required:\n"
            "  chimera-memory wrap --task-type test pytest tests/ -q"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    wrap_parser.add_argument(
        "--agent", dest="agent_id",
        help="Override agent label (e.g. kiro, claude-code). Inherits from session.",
    )
    wrap_parser.add_argument(
        "--model", dest="model_version",
        help="Model override. Use 'unknown' if genuinely unknown. Inherits from session.",
    )
    wrap_parser.add_argument(
        "--task-type", dest="task_type",
        help="Work label: test, lint, type, docs, implementation, refactor, bugfix, review, …",
    )
    wrap_parser.add_argument("--confidence", type=float, help="Override claim confidence (0.0–1.0)")
    # --- data-quality metadata flags (all optional) ---
    wrap_parser.add_argument(
        "--failure-origin", dest="failure_origin",
        help="Why this may fail: organic_real, synthetic, invocation_artifact, …",
    )
    wrap_parser.add_argument(
        "--verification-scope", dest="verification_scope",
        help="Scope: focused_file, package, workspace, full_suite, …",
    )
    wrap_parser.add_argument(
        "--scope-path", dest="scope_paths", action="append", metavar="PATH",
        help="Path(s) covered (repeatable).",
    )
    wrap_parser.add_argument("--scope-intent", dest="scope_intent",
                             help="Free-text description of what is being verified.")
    wrap_parser.add_argument("--repair-loop-id", dest="repair_loop_id",
                             help="Stable ID linking baseline→fix→verify claims.")
    wrap_parser.add_argument(
        "--repair-phase", dest="repair_phase",
        help="Phase: baseline, repair_attempt, same_scope_after_fix, regression_check, none",
    )
    wrap_parser.add_argument("--repair-of-claim-id", dest="repair_of_claim_id",
                             help="claim_id of the failing claim this repairs.")
    wrap_parser.add_argument("--baseline-claim-id", dest="baseline_claim_id",
                             help="claim_id of the baseline claim for this repair loop.")
    wrap_parser.add_argument("--residual-out-of-scope", dest="residual_out_of_scope",
                             help="Note any known failures outside the verified scope.")
    wrap_parser.add_argument(
        "wrapped", nargs=argparse.REMAINDER, help="Command (use -- to separate)",
    )
    wrap_parser.set_defaults(command="wrap")

    # ---- session subcommand ----
    session_parser = subparsers.add_parser("session", help="Manage work sessions")
    session_sub = session_parser.add_subparsers(dest="session_command")

    session_start = session_sub.add_parser(
        "start",
        help="Open a new session with attribution metadata.",
        description=(
            "Opens a new session. Wrapped claims inherit agent/model/harness from this session.\n\n"
            "Use --model unknown if the model is genuinely unknown (e.g. a planning chat).\n"
            "Do not invent a model name."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    session_start.add_argument("--branch", required=True, help="Git branch being worked on")
    session_start.add_argument("--task-label", required=True, help="Short description of work")
    session_start.add_argument(
        "--agent",
        help="Agent label (e.g. kiro, claude-code). Use a stable lowercase label.",
    )
    session_start.add_argument(
        "--model",
        help="Model version (e.g. claude-sonnet-4.6, gpt-4o). Use 'unknown' if genuinely unknown.",
    )
    session_start.add_argument(
        "--harness-id",
        help="Tool surface (e.g. kiro-cli, claude-code-cli, planning-chat, manual-terminal).",
    )
    session_start.add_argument("--memory-dir", help="Override .chimera-memory/ directory path")
    session_start.set_defaults(command="session", session_command="start")

    session_end = session_sub.add_parser(
        "end",
        help="Close the active session and emit a receipt.",
        description="Closes the open session and emits a text or JSON receipt.",
    )
    session_end.add_argument(
        "--final-status",
        type=lambda s: s.upper(),
        choices=["PASSED", "FAILED", "MIXED", "INTERRUPTED", "UNKNOWN"],
        help="Final outcome: PASSED, FAILED, MIXED, INTERRUPTED, or UNKNOWN. Alias: --status",
    )
    session_end.add_argument(
        "--status",
        type=lambda s: s.upper(),
        choices=["PASSED", "FAILED", "MIXED", "INTERRUPTED", "UNKNOWN"],
        help="Alias for --final-status",
    )
    session_end.add_argument("--memory-dir", help="Override .chimera-memory/ directory path")
    session_end.add_argument("--json", action="store_true", help="Emit receipt as JSON")
    session_end.set_defaults(command="session", session_command="end")

    session_list = session_sub.add_parser("list", help="List closed sessions")
    session_list.add_argument("--memory-dir")
    session_list.set_defaults(command="session", session_command="list")

    session_current = session_sub.add_parser("current", help="Show the currently open session")
    session_current.add_argument("--memory-dir")
    session_current.set_defaults(command="session", session_command="current")

    # ---- receipt subcommand ----
    receipt_parser = subparsers.add_parser(
        "receipt",
        help="Show a session receipt in text, JSON, or markdown.",
        description=(
            "Displays a session receipt showing agent, git state, commands observed,\n"
            "outcome, and drift signal.\n\n"
            "--markdown produces a GitHub-renderable receipt suitable for PR comments."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    receipt_sub = receipt_parser.add_subparsers(dest="receipt_command")

    receipt_show = receipt_sub.add_parser("show", help="Show receipt for a specific session ID")
    receipt_show.add_argument("session_id", help="Session ID to show receipt for")
    receipt_show.add_argument("--memory-dir")
    receipt_show.add_argument("--json", action="store_true", help="Emit as JSON")
    receipt_show.add_argument("--markdown", action="store_true", help="Emit as GitHub markdown")
    receipt_show.add_argument("--format", dest="receipt_format",
                              choices=["text", "json", "markdown", "github-summary"],
                              help="Output format")
    receipt_show.add_argument("--output", dest="receipt_output", metavar="PATH",
                              help="Write receipt to file instead of stdout")
    receipt_show.set_defaults(command="receipt")

    receipt_latest = receipt_sub.add_parser("latest", help="Show receipt for most recent session")
    receipt_latest.add_argument("--memory-dir")
    receipt_latest.add_argument("--json", action="store_true", help="Emit as JSON")
    receipt_latest.add_argument("--markdown", action="store_true", help="Emit as GitHub markdown")
    receipt_latest.add_argument("--format", dest="receipt_format",
                                choices=["text", "json", "markdown", "github-summary"],
                                help="Output format")
    receipt_latest.add_argument("--output", dest="receipt_output", metavar="PATH",
                                help="Write receipt to file instead of stdout")
    receipt_latest.set_defaults(command="receipt")

    receipt_bundle = receipt_sub.add_parser(
        "bundle",
        help="Write a receipt artifact bundle (receipt.md, receipt.json,"
        " status.json) to a directory.",
    )
    receipt_bundle.add_argument("--output-dir", dest="bundle_output_dir", required=True,
                                metavar="DIR", help="Directory to write bundle files into")
    receipt_bundle.add_argument("--memory-dir")
    receipt_bundle.add_argument(
        "--include-preflight", dest="bundle_include_preflight", action="store_true",
        help="Include preflight advisory files (preflight.md, preflight.json).",
    )
    receipt_bundle.add_argument(
        "--from-git", dest="bundle_from_git", action="store_true",
        help="Infer preflight scope from git working-tree changes.",
    )
    receipt_bundle.add_argument(
        "--scope-path", dest="bundle_scope_paths", action="append", metavar="PATH",
        help="Explicit scope paths for preflight (repeatable).",
    )
    receipt_bundle.set_defaults(command="receipt")

    repair_loops_parser = subparsers.add_parser(
        "repair-loops",
        help="Show repair loop claim groups (explicit metadata only, no inference).",
    )
    repair_loops_parser.add_argument("--json", action="store_true")
    repair_loops_parser.set_defaults(command="repair-loops")

    errata_parser = subparsers.add_parser(
        "errata",
        help="Record a correction to a claim's failure_origin without mutating history.",
    )
    errata_sub = errata_parser.add_subparsers(dest="errata_command")
    errata_add = errata_sub.add_parser(
        "add",
        help="Correct a claim's failure_origin for DQ readiness calculations.",
    )
    errata_add.add_argument("claim_id", help="Claim ID to correct")
    errata_add.add_argument(
        "--failure-origin", dest="corrected_failure_origin", required=True,
        help="Corrected failure_origin value",
    )
    errata_add.add_argument("--reason", required=True, help="Why this correction is needed")
    errata_add.add_argument("--note", default="", help="Optional additional note")
    errata_add.set_defaults(command="errata")

    errata_list = errata_sub.add_parser("list", help="List all errata records.")
    errata_list.add_argument("--json", action="store_true")
    errata_list.set_defaults(command="errata")

    evidence_parser = subparsers.add_parser(
        "evidence",
        help="Evidence bundle export and dry-run import for cross-agent exchange.",
    )
    evidence_sub = evidence_parser.add_subparsers(dest="evidence_command")

    ev_bundle = evidence_sub.add_parser(
        "bundle",
        help="Export clean evidence as a portable bundle.",
    )
    ev_bundle.add_argument("--output-dir", dest="ev_output_dir", required=True, metavar="DIR")
    ev_bundle.add_argument("--memory-dir")
    ev_bundle.set_defaults(command="evidence")

    ev_import = evidence_sub.add_parser(
        "import",
        help="Inspect an evidence bundle (dry-run only — no writes).",
    )
    ev_import.add_argument("bundle_dir", metavar="BUNDLE_DIR")
    ev_import.add_argument("--dry-run", dest="ev_dry_run", action="store_true", default=True,
                           help="Dry-run (no writes). This is always true in this version.")
    ev_import.add_argument("--json", action="store_true")
    ev_import.add_argument("--memory-dir")
    ev_import.set_defaults(command="evidence")

    preflight_parser = subparsers.add_parser(
        "preflight",
        help="Read-only advisory: relevant failures, repair loops, recommended checks.",
    )
    preflight_parser.add_argument(
        "--scope-path", dest="preflight_scopes", action="append", metavar="PATH",
        help="Scope path to filter evidence (repeatable).",
    )
    preflight_parser.add_argument(
        "--from-git", dest="preflight_from_git", action="store_true",
        help="Infer scope from git working-tree changes (staged + unstaged tracked files).",
    )
    preflight_parser.add_argument(
        "--include-untracked", dest="preflight_include_untracked", action="store_true",
        help="Include untracked (??) files when using --from-git.",
    )
    preflight_parser.add_argument("--task-type", dest="preflight_task_type")
    preflight_parser.add_argument("--agent", dest="preflight_agent")
    preflight_parser.add_argument("--model", dest="preflight_model")
    preflight_parser.add_argument("--failure-origin", dest="preflight_failure_origin")
    preflight_parser.add_argument("--verification-scope", dest="preflight_vs")
    preflight_parser.add_argument("--limit", dest="preflight_limit", type=int, default=10)
    preflight_parser.add_argument("--json", action="store_true")
    preflight_parser.set_defaults(command="preflight")

    m2b_parser = subparsers.add_parser(
        "m2b-readiness",
        help="Read-only M2B evidence readiness gate (not drift scoring).",
    )
    m2b_parser.add_argument("--json", action="store_true")
    m2b_parser.add_argument(
        "--dq-only", dest="m2b_dq_only", action="store_true",
        help="Evaluate only DQ-labeled claims (excludes legacy unknowns).",
    )
    m2b_parser.add_argument(
        "--all-ledger", dest="m2b_all_ledger", action="store_true",
        help="Evaluate all clean claims including legacy unlabeled.",
    )
    m2b_parser.add_argument(
        "--explain", dest="m2b_explain", action="store_true",
        help="Show exactly what evidence is missing and how to build it honestly.",
    )
    m2b_parser.set_defaults(command="m2b-readiness")

    doctor_parser = subparsers.add_parser("doctor", help="Check local chimera-memory health")
    doctor_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    doctor_parser.set_defaults(command="doctor")

    dq_parser = subparsers.add_parser("dq-summary", help="Read-only DQ classification summary")
    dq_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    dq_parser.set_defaults(command="dq-summary")

    # ---- agent-guide subcommand ----
    agent_guide_parser = subparsers.add_parser(
        "agent-guide",
        help="Print the session/wrap/repair-loop protocol for a named agent",
    )
    agent_guide_parser.add_argument(
        "--agent",
        dest="guide_agent",
        default="generic",
        choices=["generic", "kiro", "codex"],
        help="Agent to tailor the guide for (default: generic)",
    )
    agent_guide_parser.set_defaults(command="agent-guide")

    # ---- template subcommand ----
    template_parser = subparsers.add_parser(
        "template",
        help="Generate copy-paste command templates",
    )
    template_sub = template_parser.add_subparsers(dest="template_command")
    tmpl_dogfood = template_sub.add_parser(
        "dogfood",
        help="Generate a dogfood session template for a scope path",
    )
    tmpl_dogfood.add_argument(
        "--scope-path",
        dest="template_scope_path",
        required=True,
        help="Package/directory scope to target",
    )
    tmpl_dogfood.set_defaults(command="template")

    # ── bundle inspect ─────────────────────────────────────────────
    bundle_parser = subparsers.add_parser(
        "bundle", help="Read-only bundle inspection"
    )
    bundle_sub = bundle_parser.add_subparsers(dest="bundle_command")
    bundle_inspect = bundle_sub.add_parser(
        "inspect",
        help="Inspect a receipt or evidence bundle for safety before sharing/importing",
    )
    bundle_inspect.add_argument(
        "bundle_path", help="Path to the bundle directory to inspect"
    )
    bundle_inspect.add_argument("--json", dest="json", action="store_true")
    bundle_inspect.set_defaults(command="bundle")

    bundle_diff = bundle_sub.add_parser(
        "diff",
        help="Compare two bundles (read-only, no import, no writes)",
    )
    bundle_diff.add_argument("old_bundle", help="Path to the old/baseline bundle")
    bundle_diff.add_argument("new_bundle", help="Path to the new/current bundle")
    bundle_diff.add_argument("--json", dest="json", action="store_true")
    bundle_diff.set_defaults(command="bundle")

    # ── checks ─────────────────────────────────────────────────────
    checks_parser = subparsers.add_parser(
        "checks", help="Project check suites — define and run verification recipes"
    )
    checks_sub = checks_parser.add_subparsers(dest="checks_command")
    checks_init = checks_sub.add_parser(
        "init", help="Create a starter chimera-memory.checks.toml"
    )
    checks_init.add_argument(
        "--preset", default="python", help="Preset template (default: python)"
    )
    checks_init.set_defaults(command="checks")

    checks_run = checks_sub.add_parser(
        "run", help="Run checks from chimera-memory.checks.toml"
    )
    checks_run.add_argument(
        "--config", default="chimera-memory.checks.toml",
        help="Config file path (default: chimera-memory.checks.toml)",
    )
    checks_run.add_argument(
        "--bundle", action="store_true", help="Create receipt bundle after run"
    )
    checks_run.add_argument(
        "--output-dir", dest="checks_output_dir",
        help="Output directory for bundle (default: ./chimera-run)",
    )
    checks_run.set_defaults(command="checks")

    # ── claim (claim-locked evidence) ──────────────────────────────
    claim_parser = subparsers.add_parser(
        "claim",
        help="Claim-locked coding — seal a scope-bound claim before edits, "
        "then settle it against pre-committed checks.",
        description=(
            "A claim records intent, a declared scope path, a pre-committed\n"
            "falsifier, and optional must-not-break checks BEFORE editing.\n"
            "Settlement runs only those sealed checks — never a substitute.\n\n"
            "This produces settled evidence, not proof of correctness."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    claim_sub = claim_parser.add_subparsers(dest="claim_command")

    claim_lock = claim_sub.add_parser(
        "lock", help="Seal a claim before editing (LOCKED)."
    )
    claim_lock.add_argument(
        "--from-file", dest="claim_from_file", metavar="PATH",
        help="Load the claim from a claim.toml file (preferred).",
    )
    claim_lock.add_argument("--intent", dest="claim_intent", help="What you intend to do.")
    claim_lock.add_argument(
        "--scope-path", dest="claim_scope_path",
        help="Declared scope path the claim covers.",
    )
    claim_lock.add_argument(
        "--predicted-outcome", dest="claim_predicted", default="all pass",
        help="Predicted outcome (default: 'all pass').",
    )
    claim_lock.add_argument(
        "--falsifier", dest="claim_falsifiers", action="append", metavar="CMD",
        help="Pre-committed falsifier command, quoted (repeatable). "
        "Parsed safely into a list; shell metacharacters are rejected.",
    )
    claim_lock.add_argument(
        "--must-not-break", dest="claim_must_not_break", action="append", metavar="CMD",
        help="Must-not-break command, quoted (repeatable).",
    )
    claim_lock.add_argument("--memory-dir")
    claim_lock.add_argument("--json", action="store_true", help="Emit the record as JSON")
    claim_lock.add_argument(
        "--auto", dest="claim_auto", action="store_true",
        help="Build claim spec from env vars / flags instead of a claim.toml file. "
        "Sources: CHIMERA_INTENT, CHIMERA_SCOPE_PATH, CHIMERA_FALSIFIERS_JSON, "
        "CHIMERA_MUST_NOT_BREAK_JSON, CHIMERA_PREDICTED_OUTCOME.",
    )
    claim_lock.add_argument(
        "--dry-run", dest="claim_dry_run", action="store_true",
        help="With --auto: validate and print the generated spec without locking.",
    )
    claim_lock.add_argument(
        "--save-spec", dest="claim_save_spec", metavar="PATH",
        help="With --auto: also write the generated TOML spec to this file.",
    )
    claim_lock.add_argument(
        "--falsifiers-json", dest="claim_falsifiers_json", metavar="JSON",
        help="With --auto: JSON array of command arrays for falsifiers, "
        "e.g. '[[\"uv\",\"run\",\"pytest\",\"tests/\"]]'.",
    )
    claim_lock.add_argument(
        "--must-not-break-json", dest="claim_mnb_json", metavar="JSON",
        help="With --auto: JSON array of command arrays for must-not-break checks.",
    )
    claim_lock.add_argument(
        "--from-checks", dest="claim_from_checks", action="store_true",
        help="With --auto: use chimera-memory.checks.toml as falsifier source "
        "when CHIMERA_FALSIFIERS_JSON is not set.",
    )
    claim_lock.set_defaults(command="claim", claim_command="lock")

    claim_list = claim_sub.add_parser("list", help="List locked/settled claims.")
    claim_list.add_argument("--memory-dir")
    claim_list.add_argument("--json", action="store_true")
    claim_list.set_defaults(command="claim", claim_command="list")

    claim_show = claim_sub.add_parser("show", help="Show one claim by id.")
    claim_show.add_argument("claim_id", help="Claim id (clm_...)")
    claim_show.add_argument("--memory-dir")
    claim_show.add_argument("--json", action="store_true")
    claim_show.set_defaults(command="claim", claim_command="show")

    claim_settle = claim_sub.add_parser(
        "settle", help="Settle a claim against its sealed checks only."
    )
    claim_settle.add_argument("claim_id", help="Claim id (clm_...)")
    claim_settle.add_argument("--memory-dir")
    claim_settle.add_argument("--json", action="store_true")
    claim_settle.set_defaults(command="claim", claim_command="settle")

    claim_report = claim_sub.add_parser(
        "report", help="Render a single-claim evidence report."
    )
    claim_report.add_argument("claim_id", help="Claim id (clm_...)")
    claim_report.add_argument("--memory-dir")
    claim_report.add_argument("--json", action="store_true")
    claim_report.set_defaults(command="claim", claim_command="report")

    claim_validate = claim_sub.add_parser(
        "validate",
        help="Dry-run validate a claim.toml without locking or writing anything.",
        description=(
            "Parses and validates a claim file. Reports hard errors and warnings.\n"
            "Does not create a claim record or write to .chimera-memory/.\n\n"
            "Exit 0: no hard errors (warnings are informational only).\n"
            "Exit 1: hard errors that would prevent locking."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    claim_validate.add_argument(
        "--from-file", dest="claim_from_file", required=True, metavar="PATH",
        help="Path to claim.toml to validate.",
    )
    claim_validate.add_argument(
        "--json", action="store_true", help="Emit result as JSON."
    )
    claim_validate.set_defaults(command="claim", claim_command="validate")

    # ── xray (Merge X-Ray / PR_EVIDENCE.md) ────────────────────────
    xray_parser = subparsers.add_parser(
        "xray",
        help="Generate a Merge X-Ray (PR_EVIDENCE.md) from claims + git diff.",
    )
    xray_sub = xray_parser.add_subparsers(dest="xray_command")
    xray_generate = xray_sub.add_parser(
        "generate", help="Generate the PR evidence report for the current changes."
    )
    xray_generate.add_argument(
        "--base", dest="xray_base",
        help="Base ref to diff from (e.g. main). Default: working-tree vs HEAD.",
    )
    xray_generate.add_argument(
        "--head", dest="xray_head",
        help="Head ref (default: HEAD when --base is given).",
    )
    xray_generate.add_argument(
        "--output", dest="xray_output", metavar="PATH",
        help="Write Markdown report to this file (e.g. PR_EVIDENCE.md).",
    )
    xray_generate.add_argument("--memory-dir")
    xray_generate.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON instead of Markdown"
    )
    xray_generate.add_argument(
        "--format", dest="xray_format", choices=["markdown", "pr-comment"],
        default="markdown",
        help=(
            "Output format for stdout: 'markdown' (default, full report) or "
            "'pr-comment' (concise summary for a PR comment). --output always "
            "writes the full Markdown report regardless of --format."
        ),
    )
    # Gate policy choices come from the single source of truth in xray, so the
    # CLI can never drift from EVIDENCE_GATE_POLICIES (BIGREL-4A).
    from chimera_memory.xray import EVIDENCE_GATE_POLICIES

    xray_generate.add_argument(
        "--fail-on", dest="xray_fail_on",
        choices=list(EVIDENCE_GATE_POLICIES),
        default="never",
        help=(
            "Opt-in evidence gate: exit nonzero when the policy is not met. "
            "Default 'never' (advisory only — never fails). Enforces evidence "
            "policy, not code correctness."
        ),
    )
    xray_generate.set_defaults(command="xray", xray_command="generate")

    # ── mcp serve ──────────────────────────────────────────────────
    mcp_parser = subparsers.add_parser(
        "mcp",
        help="Local MCP tool server for coding agents.",
    )
    mcp_sub = mcp_parser.add_subparsers(dest="mcp_command")
    mcp_serve = mcp_sub.add_parser(
        "serve",
        help="Start a local stdio MCP server exposing Chimera tools.",
        description=(
            "Starts a local stdio MCP server (JSON-RPC 2.0 over stdin/stdout).\n\n"
            "Read-only tools are enabled by default (validate, show, list).\n"
            "Local-write tools require --allow-write (lock, xray generate).\n"
            "Execute tools require --allow-execute (claim settle).\n\n"
            "No network. No cloud. All data stays local.\n\n"
            "Configure in your MCP client:\n"
            '  {"command": "chimera-memory", "args": ["mcp", "serve", "--allow-write"]}'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mcp_serve.add_argument(
        "--allow-write", dest="mcp_allow_write", action="store_true",
        help="Enable local-write tools: claim lock --auto, xray generate.",
    )
    mcp_serve.add_argument(
        "--allow-execute", dest="mcp_allow_execute", action="store_true",
        help=(
            "Enable execute tools: claim settle. "
            "WARNING: this allows running local project commands from sealed claims."
        ),
    )
    mcp_serve.set_defaults(command="mcp", mcp_command="serve")

    # ── hooks (Claude Code hook installer) ─────────────────────────
    hooks_parser = subparsers.add_parser(
        "hooks",
        help="Install or manage Claude Code hooks for automatic claim-locked evidence.",
    )
    hooks_sub = hooks_parser.add_subparsers(dest="hooks_command")

    hooks_install = hooks_sub.add_parser(
        "install",
        help="Install Chimera hook scripts and patch .claude/settings.json.",
        description=(
            "Writes two hook scripts into .claude/hooks/ and registers them\n"
            "in .claude/settings.json:\n\n"
            "  UserPromptSubmit — injects a one-time reminder about claim auto-lock\n"
            "  Stop             — settles the open claim and generates PR_EVIDENCE.md\n\n"
            "After installation, a Claude Code session will automatically:\n"
            "  1. Remind you to set CHIMERA_INTENT before coding\n"
            "  2. Settle the open claim when Claude finishes a turn\n"
            "  3. Generate PR_EVIDENCE.md from git diff\n\n"
            "All behavior is local. No network. No cloud."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    hooks_install.add_argument(
        "--dry-run", dest="hooks_dry_run", action="store_true",
        help="Show what would be installed without writing files.",
    )
    hooks_install.add_argument(
        "--force", action="store_true",
        help="Overwrite existing hook scripts and settings entries.",
    )
    hooks_install.add_argument("--json", action="store_true", help="Emit result as JSON.")
    hooks_install.set_defaults(command="hooks", hooks_command="install")

    hooks_uninstall = hooks_sub.add_parser(
        "uninstall", help="Remove Chimera hook scripts from .claude/."
    )
    hooks_uninstall.add_argument("--json", action="store_true")
    hooks_uninstall.set_defaults(command="hooks", hooks_command="uninstall")

    hooks_status = hooks_sub.add_parser(
        "status", help="Show current Chimera hook installation status."
    )
    hooks_status.add_argument("--json", action="store_true")
    hooks_status.set_defaults(command="hooks", hooks_command="status")

    hooks_init = hooks_sub.add_parser(
        "init",
        help="Create a starter .chimera/hooks.toml if one does not exist.",
    )
    hooks_init.add_argument(
        "--force", action="store_true",
        help="Overwrite existing .chimera/hooks.toml.",
    )
    hooks_init.set_defaults(command="hooks", hooks_command="init")

    hooks_prompt_submit = hooks_sub.add_parser(
        "prompt-submit",
        help="Handle a UserPromptSubmit event: derive intent and attempt auto-lock.",
        description=(
            "Reads a Claude UserPromptSubmit hook payload from stdin.\n"
            "Derives intent from the prompt text, then attempts to auto-lock\n"
            "a claim if falsifier inputs are configured.\n\n"
            "Outputs Claude context injection text to stdout.\n"
            "Diagnostic messages go to stderr only.\n\n"
            "Never blocks (always exits 0).\n\n"
            "Called automatically by the UserPromptSubmit hook script.\n"
            "Can also be tested manually:\n"
            "  echo '{\"prompt\": \"fix xray bug\"}' | chimera-memory hooks prompt-submit"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    hooks_prompt_submit.add_argument(
        "--dry-run", dest="prompt_dry_run", action="store_true",
        help="Validate and show generated spec without locking.",
    )
    hooks_prompt_submit.add_argument(
        "--json", action="store_true",
        help="Emit result as JSON (for debugging; not for hook stdout).",
    )
    hooks_prompt_submit.set_defaults(command="hooks", hooks_command="prompt-submit")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        parsed = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1

    if parsed.command is None:
        parser.print_help()
        return 0
    if parsed.command == "init":
        if not (Path.cwd() / ".git").exists():
            print("Chimera Memory expects a git repository.")
            print("Run `git init` first, or run this command from an existing repo.")
            return 1
        store = MemoryStore.from_paths()
        store.initialize()
        print(store.memory_dir)
        _ensure_gitignore(Path.cwd())
        print("\nNext steps:")
        print("  chimera-memory wrap --scope-path . "
              "--failure-origin organic_real "
              "--verification-scope package -- <your-command>")
        print("  chimera-memory verify")
        print("  chimera-memory doctor")
        print("\nRun 'chimera-memory quickstart' for a full guided example.")
        return 0
    if parsed.command == "quickstart":
        return _quickstart(parsed)
    if parsed.command == "demo":
        return _demo(parsed)
    if parsed.command == "wrap":
        return _wrap_pytest(parsed)
    if parsed.command == "status":
        return _status(parsed)
    if parsed.command == "proof-debt":
        return _proof_debt(parsed)
    if parsed.command == "failures":
        return _failures(parsed)
    if parsed.command == "verify":
        return _verify(parsed)
    if parsed.command == "export":
        return _export(parsed)
    if parsed.command == "reliability":
        return _reliability(parsed)
    if parsed.command == "report":
        report = export_report()
        print(json.dumps(report, sort_keys=True) if parsed.json else _plain_report(report))
        return 0
    if parsed.command == "drift":
        result = detect_drift(by=parsed.by, min_claims=parsed.min_claims)
        print(json.dumps(result, sort_keys=True) if parsed.json else _plain_drift(result))
        return 0
    if parsed.command == "session":
        return _handle_session(parsed)
    if parsed.command == "receipt":
        return _handle_receipt(parsed)
    if parsed.command == "repair-loops":
        return _repair_loops(parsed)
    if parsed.command == "errata":
        return _errata(parsed)
    if parsed.command == "evidence":
        return _evidence(parsed)
    if parsed.command == "preflight":
        return _preflight(parsed)
    if parsed.command == "m2b-readiness":
        return _m2b_readiness(parsed)
    if parsed.command == "doctor":
        return _doctor(parsed)
    if parsed.command == "dq-summary":
        return _dq_summary(parsed)
    if parsed.command == "agent-guide":
        return _agent_guide(parsed)
    if parsed.command == "template":
        return _template(parsed)
    if parsed.command == "bundle":
        return _bundle(parsed)
    if parsed.command == "checks":
        return _checks(parsed)

    if parsed.command == "claim":
        return _claim(parsed)
    if parsed.command == "xray":
        return _xray(parsed)

    if parsed.command == "mcp":
        return _mcp(parsed)

    if parsed.command == "hooks":
        return _hooks(parsed)

    if parsed.command in ("record", "settle"):
        print(
            f"'{parsed.command}' is an internal subcommand not part of the public API. "
            "Use 'chimera-memory wrap' to record verification outcomes.",
            file=__import__("sys").stderr,
        )
        return 2

    print(f"{parsed.command}: not implemented yet")
    return 2


def _evidence(parsed: argparse.Namespace) -> int:
    """Handle evidence bundle / evidence import subcommands."""
    from chimera_memory.evidence import (
        build_evidence_bundle,
        dry_run_import,
        format_dry_run_text,
    )

    sub = getattr(parsed, "evidence_command", None)
    root = _memory_root(parsed)
    store = MemoryStore.from_paths(root=root)

    if sub == "bundle":
        out_dir = Path(parsed.ev_output_dir)
        build_evidence_bundle(store, out_dir)
        return 0

    if sub == "import":
        bundle_dir = Path(parsed.bundle_dir)
        if not bundle_dir.exists():
            print(f"error: bundle directory '{bundle_dir}' not found",
                  file=__import__("sys").stderr)
            return 1
        result = dry_run_import(store, bundle_dir)
        if parsed.json:
            print(json.dumps(result, sort_keys=True))
        else:
            print(format_dry_run_text(result))
        return 0 if not result.get("errors") else 1

    print(f"evidence: unknown subcommand '{sub}'", file=__import__("sys").stderr)
    return 2


def _preflight(parsed: argparse.Namespace) -> int:
    from chimera_memory.data_quality import (
        validate_failure_origin,
        validate_verification_scope,
    )
    from chimera_memory.preflight import build_preflight, format_preflight_text

    # Validate enum filters
    fo = getattr(parsed, "preflight_failure_origin", None)
    vs = getattr(parsed, "preflight_vs", None)
    try:
        if fo:
            validate_failure_origin(fo)
        if vs:
            validate_verification_scope(vs)
    except ValueError as exc:
        print(f"error: {exc}", file=__import__("sys").stderr)
        return 2

    store = MemoryStore.from_paths(root=Path.cwd())
    report = build_preflight(
        store,
        scope_paths=getattr(parsed, "preflight_scopes", None) or [],
        from_git=getattr(parsed, "preflight_from_git", False),
        include_untracked=getattr(parsed, "preflight_include_untracked", False),
        task_type=getattr(parsed, "preflight_task_type", None),
        agent_id=getattr(parsed, "preflight_agent", None),
        model_version=getattr(parsed, "preflight_model", None),
        failure_origin=fo,
        verification_scope=vs,
        limit=getattr(parsed, "preflight_limit", 10),
    )
    if parsed.json:
        print(json.dumps(report.to_dict(), sort_keys=True))
    else:
        print(format_preflight_text(report))
    return 0


def _errata(parsed: argparse.Namespace) -> int:
    """Handle errata add/list subcommands."""
    from chimera_memory.errata import add_errata, load_errata

    sub = getattr(parsed, "errata_command", None)
    mem_dir = MemoryStore.from_paths(root=Path.cwd()).memory_dir

    if sub == "add":
        # Resolve short claim_id prefix to full UUID if needed
        claim_id = parsed.claim_id
        if len(claim_id) < 32:
            store = MemoryStore.from_paths(root=Path.cwd())
            # Use unique claim_ids (deduped)
            seen: set[str] = set()
            matches: list[str] = []
            for c in store.read_claims():
                if c.claim_id not in seen and c.claim_id.startswith(claim_id):
                    seen.add(c.claim_id)
                    matches.append(c.claim_id)
            if len(matches) == 1:
                claim_id = matches[0]
            elif len(matches) == 0:
                print(f"error: no claim found with prefix '{claim_id}'",
                      file=__import__("sys").stderr)
                return 1
            else:
                print(f"error: ambiguous prefix '{claim_id}' matches {len(matches)} claims",
                      file=__import__("sys").stderr)
                return 1
        add_errata(
            mem_dir,
            claim_id=claim_id,
            corrected_failure_origin=parsed.corrected_failure_origin,
            reason=parsed.reason,
            note=getattr(parsed, "note", ""),
        )
        print(
            f"Errata recorded: claim {claim_id[:8]} "
            f"→ failure_origin={parsed.corrected_failure_origin}"
        )
        print("Note: original claim record is unchanged; errata applies to DQ readiness only.")
        return 0

    if sub == "list":
        errata = load_errata(mem_dir)
        if parsed.json:
            print(json.dumps(list(errata.values()), sort_keys=True))
        else:
            if not errata:
                print("No errata records.")
            else:
                print(f"{len(errata)} errata record(s):")
                for rec in errata.values():
                    cid = rec['claim_id'][:8]
                    fo = rec['corrected_failure_origin']
                    reason = rec['reason']
                    print(f"  {cid} → {fo}: {reason}")
        return 0

    print(f"errata: unknown subcommand '{sub}'", file=__import__("sys").stderr)
    return 2


def _analyze_repair_loops(store: MemoryStore) -> dict[str, Any]:
    """Classify all repair loops into open, complete, and malformed.

    Uses all settled claims (not just clean) for broader coverage.
    Classification:
      complete  = has CONTRADICTED baseline/repair_attempt + later VALIDATED SSAF
      open      = has CONTRADICTED baseline/repair_attempt but no VALIDATED SSAF
      malformed = has VALIDATED SSAF but no CONTRADICTED baseline/repair_attempt
    regression_check does NOT count as fixed_same_scope / does not close a loop.
    """
    from chimera_memory.data_quality import K_REPAIR_LOOP_ID, K_REPAIR_PHASE, K_SCOPE_PATHS
    from chimera_memory.query import latest_claims_from_records
    from chimera_memory_types.knowledge import ClaimStatus

    raw = store.read_claims()
    settled = [c for c in latest_claims_from_records(raw) if c.claim_status is not None]

    # Group settled claims by repair_loop_id
    groups: dict[str, list[Any]] = {}
    for c in settled:
        m = c.metadata or {}
        rl = m.get(K_REPAIR_LOOP_ID)
        if rl:
            groups.setdefault(str(rl), []).append(c)

    open_loops: list[dict[str, Any]] = []
    complete_loops: list[dict[str, Any]] = []
    malformed_loops: list[dict[str, Any]] = []

    for loop_id, claims in sorted(groups.items()):
        # Collect phase/status data
        baseline_contradicted = 0
        ssaf_validated = 0
        regression_count = 0
        scope_paths: list[str] = []
        baseline_commands: list[str] = []

        for c in claims:
            m = c.metadata or {}
            ph = str(m.get(K_REPAIR_PHASE) or "none")
            sp = m.get(K_SCOPE_PATHS)
            if sp and isinstance(sp, list) and not scope_paths:
                scope_paths = [str(s) for s in sp]

            if ph in ("baseline", "repair_attempt") and c.claim_status == ClaimStatus.CONTRADICTED:
                baseline_contradicted += 1
                cmd = str(c.title or "").replace("will pass", "").strip()
                if len(baseline_commands) < 3 and cmd:
                    baseline_commands.append(cmd)
            elif ph == "same_scope_after_fix" and c.claim_status == ClaimStatus.VALIDATED:
                ssaf_validated += 1
            elif ph == "regression_check":
                regression_count += 1

        scope_str = scope_paths[0] if scope_paths else "<your-scope>"
        # Build next_action template
        cmd_hint = baseline_commands[0] if baseline_commands else "<same check that failed>"
        next_action = (
            f"chimera-memory wrap \\\n"
            f"    --failure-origin organic_real \\\n"
            f"    --scope-path {scope_str} \\\n"
            f"    --verification-scope package \\\n"
            f"    --repair-loop-id {loop_id} \\\n"
            f"    --repair-phase same_scope_after_fix \\\n"
            f"    -- {cmd_hint}"
        )

        base = {
            "repair_loop_id": loop_id,
            "scope_paths": scope_paths,
            "baseline_count": baseline_contradicted,
            "same_scope_after_fix_count": ssaf_validated,
            "regression_check_count": regression_count,
            "baseline_commands": baseline_commands,
        }

        if ssaf_validated > 0 and baseline_contradicted == 0:
            malformed_loops.append({
                **base,
                "status": "malformed",
                "missing_phase": "baseline",
                "reason": "same_scope_after_fix exists but no CONTRADICTED baseline",
                "next_action": None,
            })
        elif baseline_contradicted > 0 and ssaf_validated > 0:
            complete_loops.append({
                **base,
                "status": "complete",
                "missing_phase": None,
                "next_action": None,
            })
        elif baseline_contradicted > 0:
            open_loops.append({
                **base,
                "status": "open",
                "missing_phase": "same_scope_after_fix",
                "next_action": next_action,
            })
        elif ssaf_validated == 0 and baseline_contradicted == 0 and regression_count == 0:
            # Loop exists but has no recognizable phase claims — malformed
            malformed_loops.append({
                **base,
                "status": "malformed",
                "missing_phase": "baseline",
                "reason": "no CONTRADICTED baseline or VALIDATED same_scope_after_fix",
                "next_action": None,
            })
        # else: regression_check-only loop (clean DQ session, no real bug) — skip

    next_actions = [
        f"Complete repair loop {lp['repair_loop_id']}"
        + (f" (scope: {lp['scope_paths'][0]})" if lp['scope_paths'] else "")
        + " with --repair-phase same_scope_after_fix.\n"
        + "  Run: chimera-memory repair-loops for the exact wrap command template."
        for lp in open_loops
    ]

    return {
        "open_loops": open_loops,
        "complete_loops": complete_loops,
        "malformed_loops": malformed_loops,
        "next_actions": next_actions,
    }


def _repair_loops(parsed: argparse.Namespace) -> int:
    """Show repair loop status: open, complete, malformed."""
    store = MemoryStore.from_paths(root=Path.cwd())
    data = _analyze_repair_loops(store)
    open_loops = data["open_loops"]
    complete_loops = data["complete_loops"]
    malformed_loops = data["malformed_loops"]
    next_actions = data["next_actions"]

    if parsed.json:
        payload = {
            "schema_version": 1,
            "open_loops": [
                {k: v for k, v in lp.items() if k != "baseline_commands"}
                for lp in open_loops
            ],
            "complete_loops": [
                {k: v for k, v in lp.items() if k != "baseline_commands"}
                for lp in complete_loops
            ],
            "malformed_loops": [
                {k: v for k, v in lp.items() if k != "baseline_commands"}
                for lp in malformed_loops
            ],
            "next_actions": next_actions,
        }
        print(json.dumps(payload, sort_keys=True))
        return 0

    if not open_loops and not complete_loops and not malformed_loops:
        print(
            "No repair loops found.\n"
            "Tag claims with --repair-loop-id and --repair-phase when running:\n"
            "  chimera-memory wrap --repair-loop-id my-fix --repair-phase baseline -- pytest ..."
        )
        return 0

    print("Chimera Memory Repair Loops\n")

    print(f"Open ({len(open_loops)}):")
    if open_loops:
        for lp in open_loops:
            scope = lp["scope_paths"][0] if lp["scope_paths"] else "<unknown>"
            print(f"  {lp['repair_loop_id']}")
            print(f"    scope:    {scope}")
            print(f"    baseline: {lp['baseline_count']} CONTRADICTED claim(s)")
            print("    SSAF:     missing")
            if lp.get("next_action"):
                print("    to close:")
                for line in str(lp["next_action"]).splitlines():
                    print(f"      {line}")
    else:
        print("  (none)")

    print(f"\nComplete ({len(complete_loops)}):")
    if complete_loops:
        for lp in complete_loops:
            print(f"  {lp['repair_loop_id']}")
            print(f"    baseline: {lp['baseline_count']} \u2192 SSAF: "
                  f"{lp['same_scope_after_fix_count']} \u2192 fixed_same_scope \u2713")
    else:
        print("  (none)")

    print(f"\nMalformed ({len(malformed_loops)}):")
    if malformed_loops:
        for lp in malformed_loops:
            print(f"  {lp['repair_loop_id']}")
            print(f"    reason: {lp.get('reason', 'unknown')}")
    else:
        print("  (none)")

    print(
        "\nNote:\n"
        "  regression_check does NOT produce fixed_same_scope.\n"
        "  Only same_scope_after_fix closes a repair loop."
    )
    return 0


def _m2b_readiness(parsed: argparse.Namespace) -> int:
    from chimera_memory.m2b_readiness import compute_m2b_readiness, format_readiness_text

    dq_only = getattr(parsed, "m2b_dq_only", False)
    all_ledger = getattr(parsed, "m2b_all_ledger", False)
    explain = getattr(parsed, "m2b_explain", False)
    if dq_only and all_ledger:
        import sys as _sys
        print("error: --dq-only and --all-ledger are mutually exclusive", file=_sys.stderr)
        return 2

    mode = "dq_cohort" if dq_only else "all_ledger" if all_ledger else "default"
    store = MemoryStore.from_paths(root=Path.cwd())
    report = compute_m2b_readiness(store, mode=mode)

    if parsed.json:
        d = report.to_dict()
        if explain:
            t = report.thresholds
            cs = report.dq_cohort_summary or report.readiness_evaluation_summary
            of_current = cs.get("organic_real_failed", 0)
            cg_current = cs.get("comparable_groups", 0)
            of_threshold = t.get("organic_failures_min", 5)
            cg_threshold = t.get("comparable_groups_min", 2)
            total_or = cs.get("organic_real", 0)
            d["explain"] = {
                "organic_real_failed_current": of_current,
                "organic_real_failed_threshold": of_threshold,
                "organic_real_failed_remaining": max(0, of_threshold - of_current),
                "comparable_groups_current": cg_current,
                "comparable_groups_threshold": cg_threshold,
                "comparable_groups_remaining": max(0, cg_threshold - cg_current),
                "total_organic_real_claims": total_or,
                "advice": [
                    "Use chimera-memory on real scoped work.",
                    "Record real failures honestly as organic_real.",
                    "Use same_scope_after_fix only after fixing a real defect.",
                    "Do not manufacture failures.",
                ],
            }
        print(json.dumps(d, sort_keys=True))
        return 0

    print(format_readiness_text(report))
    if explain:
        t = report.thresholds
        cs = report.dq_cohort_summary or report.readiness_evaluation_summary
        of_current = cs.get("organic_real_failed", 0)
        cg_current = cs.get("comparable_groups", 0)
        of_threshold = t.get("organic_failures_min", 5)
        cg_threshold = t.get("comparable_groups_min", 2)
        total_or = cs.get("organic_real", 0)
        print("Why readiness is blocked:\n")
        print("  organic_real_failed:")
        print(f"    current:   {of_current}")
        print(f"    required:  {of_threshold}")
        print(f"    remaining: {max(0, of_threshold - of_current)}")
        print("\n  comparable_groups:")
        print(f"    current:   {cg_current}")
        print(f"    required:  {cg_threshold}")
        print(f"    remaining: {max(0, cg_threshold - cg_current)}")
        print(f"\n  total organic_real claims: {total_or}")
        print(
            "\nHow to build qualifying evidence honestly:\n"
            "\n  - Use chimera-memory on real scoped work."
            "\n  - Wrap real validation commands with --scope-path and --failure-origin."
            "\n  - If a real command fails due to a real code/test/type/lint defect,"
            "\n    record it as --failure-origin organic_real."
            "\n  - Fix the defect and rerun with --repair-phase same_scope_after_fix."
            "\n  - Do not manufacture failures."
            "\n  - Do not weaken thresholds."
            "\n  - M2B readiness is a quality gate, not a deadline."
        )
    return 0


def _status(parsed: argparse.Namespace) -> int:
    status = build_dogfood_status(root=Path.cwd())
    if parsed.json:
        print(json.dumps(status, sort_keys=True))
        return 0
    prog = status["progress"]
    exc = status["excluded"]
    seg = status["segments"]
    cg = status["comparison_gate"]
    lines = [
        "Chimera Memory Status",
        "",
        f"Raw records:             {status['raw_records']}",
        f"Unique claims:           {status['unique_claims']}",
        f"Settled unique claims:   {status['settled_unique_claims']}",
        f"Clean unique claims:     {status['clean_unique_claims']}",
        f"Progress:                {prog['current']} / {prog['target']}",
        "",
        "Excluded:",
        f"  missing session_id:           {exc['missing_session_id']}",
        f"  agent_id unknown-agent:       {exc['unknown_agent']}",
        f"  model_version null:           {exc['model_version_null']}",
        f"  missing task_type:            {exc['missing_task_type']}",
        f"  missing attribution_conf:     {exc['missing_attribution_confidence']}",
        f"  missing identity_source:      {exc['missing_identity_source']}",
        f"  unsettled:                    {exc['unsettled']}",
        "",
        "Segments (clean claims):",
    ]
    for field, counts in seg.items():
        lines.append(f"  {field}:")
        for k, v in sorted(counts.items(), key=lambda x: -x[1]):
            lines.append(f"    {k}: {v}")
    lines += [
        "",
        "Gate:",
        f"  volume >= {prog['target']}: {'yes' if prog['met'] else 'no'}",
        "  comparison dimensions (>=5 each):",
    ]
    for dim, vals in cg.items():
        if vals:
            parts = ", ".join(f"{k}={v}" for k, v in sorted(vals.items()))
            lines.append(f"    {dim}: {parts}")
        else:
            lines.append(f"    {dim}: (none >= 5)")
    lines += [
        f"  useful pattern: {status['reason']}",
        f"  M2 ready: {'yes' if status['m2_ready'] else 'no'}",
        f"  M2B readiness: {status.get('m2b_readiness_level', 'unknown')} "
        f"({status.get('m2b_readiness_evaluation_mode', 'unknown')})",
    ]
    integ = status.get("integrity")
    if integ:
        lines += [
            "",
            "Integrity:",
            f"  Status: {integ['status']}",
            f"  Chained records: {integ['chained_records']}",
            f"  Broken records: {integ['broken_records']}",
            f"  Unsigned gaps: {integ['unsigned_gaps']}",
        ]
    print("\n".join(lines))
    return 0


def _failures(parsed: argparse.Namespace) -> int:
    from chimera_memory.errata import effective_failure_origin, load_errata
    from chimera_memory.query import build_claim_read_model

    store = MemoryStore.from_paths(root=Path.cwd())
    failures = build_claim_read_model(store).failures
    errata_map = load_errata(store.memory_dir)

    # Apply data-quality filters — failure_origin uses effective (errata-corrected) value
    fo_filter = getattr(parsed, "filter_failure_origin", None)
    vs_filter = getattr(parsed, "filter_verification_scope", None)
    if fo_filter:
        failures = [c for c in failures if effective_failure_origin(c, errata_map) == fo_filter]
    if vs_filter:
        failures = [c for c in failures if c.metadata.get(K_VERIFICATION_SCOPE) == vs_filter]
    rl_filter = getattr(parsed, "filter_repair_loop_id", None)
    if rl_filter:
        failures = [c for c in failures if c.metadata.get(K_REPAIR_LOOP_ID) == rl_filter]
    rp_filter = getattr(parsed, "filter_repair_phase", None)
    if rp_filter:
        failures = [c for c in failures if c.metadata.get(K_REPAIR_PHASE) == rp_filter]

    def _claim_to_dict(c) -> dict[str, Any]:
        from chimera_memory.adapters.pytest_ci import _ANSI_RE

        m = c.metadata or {}
        evt_meta: dict[str, Any] = {}
        if c.settlement and c.settlement.events:
            evt_meta = c.settlement.events[-1].metadata or {}
        wrapped = evt_meta.get("wrapped_args") or []
        d: dict[str, Any] = {
            "claim_id": c.claim_id,
            "session_id": m.get("session_id"),
            "agent_id": m.get("agent_id"),
            "model_version": m.get("model_version"),
            "harness_id": m.get("harness_id"),
            "task_type": m.get("task_type"),
            "command": _redact(" ".join(str(a) for a in wrapped)) if wrapped else c.title,
            "status": c.claim_status.value,
            "exit_code": evt_meta.get("exit_code"),
            "stdout_excerpt": _ANSI_RE.sub("", str(evt_meta.get("stdout_excerpt", ""))),
            "stderr_excerpt": _ANSI_RE.sub("", str(evt_meta.get("stderr_excerpt", ""))),
        }
        # Add data-quality fields if present; show effective failure_origin
        for _k in (K_FAILURE_ORIGIN, K_VERIFICATION_SCOPE, K_SCOPE_PATHS,
                   K_REPAIR_LOOP_ID, K_REPAIR_PHASE):
            if _k in m:
                d[_k] = m[_k]
        # Errata: show effective classification if corrected
        eff_fo = effective_failure_origin(c, errata_map)
        if eff_fo != m.get(K_FAILURE_ORIGIN):
            d["effective_failure_origin"] = eff_fo
            d["errata_applied"] = True
        return d

    if parsed.json:
        payload = {"count": len(failures), "failures": [_claim_to_dict(c) for c in failures]}
        print(json.dumps(payload, sort_keys=True))
        return 0

    if not failures:
        print(
            "No contradicted claims found. "
            "All wrapped commands passed, or no commands have been wrapped yet."
        )
        return 0

    print(f"Chimera Memory Failures\n\n{len(failures)} failure(s) found\n")
    for i, c in enumerate(failures, 1):
        d = _claim_to_dict(c)
        print(f"- [{i}] claim_id: {d['claim_id']}")
        print(f"      agent:    {d['agent_id']}")
        print(f"      model:    {d['model_version']}")
        print(f"      harness:  {d['harness_id']}")
        print(f"      task:     {d['task_type']}")
        print(f"      command:  {d['command']}")
        print(f"      exit_code:{d['exit_code']}")
        print(f"      session:  {d['session_id']}")
        if d["stderr_excerpt"]:
            print(f"      stderr:   {d['stderr_excerpt'].strip()[:200]}")
        if d["stdout_excerpt"]:
            print(f"      stdout:   {d['stdout_excerpt'].strip()[:200]}")
    return 0


def _verify(parsed: argparse.Namespace) -> int:
    from chimera_memory.integrity import verify_integrity

    report = verify_integrity(Path.cwd() / ".chimera-memory")
    if parsed.json:
        print(json.dumps(report.to_dict(), sort_keys=True))
    else:
        print("Chimera Memory Integrity\n")
        print(f"Status:          {report.status}")
        print(f"Claims:          {report.claims_total}")
        print(f"Legacy unsigned: {report.legacy_unsigned}")
        print(f"Chained records: {report.chained_records}")
        print(f"Broken records:  {report.broken_records}")
        print(f"Unsigned gaps:   {report.unsigned_gaps}")
        if report.errors:
            print("\nErrors:")
            for err in report.errors:
                ln = f"line {err.line_number}" if err.line_number is not None else "entry"
                print(f"  - {ln} [{err.kind}]: {err.message}")
    return 0 if report.status in ("OK", "LEGACY_UNSIGNED") else 1


def _export(parsed: argparse.Namespace) -> int:
    from chimera_memory.export import build_engine_events, format_events_jsonl

    store = MemoryStore.from_paths(root=Path.cwd())
    failures_only = getattr(parsed, "failures_only", False)
    clean_only = getattr(parsed, "clean_only", False)
    session_id = getattr(parsed, "session_id", None)
    events = build_engine_events(
        store,
        failures_only=failures_only,
        clean_only=clean_only,
        session_id=session_id,
    )
    jsonl = format_events_jsonl(events)

    output_path = getattr(parsed, "output", None)
    if output_path:
        Path(output_path).write_text(jsonl + "\n" if jsonl else "", encoding="utf-8")
        print(f"Exported {len(events)} event(s) to {output_path}")
    else:
        if jsonl:
            print(jsonl)
    return 0


def _reliability(parsed: argparse.Namespace) -> int:
    from chimera_memory.data_quality import (
        validate_failure_origin,
        validate_repair_phase,
        validate_verification_scope,
    )
    from chimera_memory.reliability import build_reliability_summary, format_reliability_text

    # Resolve --organic-only shorthand
    fo = getattr(parsed, "rel_failure_origin", None)
    if getattr(parsed, "rel_organic_only", False):
        fo = "organic_real"

    # Validate enum filters
    filters: dict[str, str] = {}
    try:
        if fo:
            filters["failure_origin"] = validate_failure_origin(fo)
        vs = getattr(parsed, "rel_verification_scope", None)
        if vs:
            filters["verification_scope"] = validate_verification_scope(vs)
        rp = getattr(parsed, "rel_repair_phase", None)
        if rp:
            filters["repair_phase"] = validate_repair_phase(rp)
        rl = getattr(parsed, "rel_repair_loop_id", None)
        if rl:
            filters["repair_loop_id"] = rl
    except ValueError as exc:
        print(f"error: {exc}", file=__import__("sys").stderr)
        return 2

    store = MemoryStore.from_paths(root=Path.cwd())
    summary = build_reliability_summary(store, filters=filters or None)
    if parsed.json:
        print(json.dumps(summary.to_dict(), sort_keys=True))
    else:
        print(format_reliability_text(summary))
    return 0


def _resolve_wrap_attribution(
    *,
    active_session: dict[str, Any] | None,
    explicit_agent: str | None,
    explicit_model: str | None,
) -> dict[str, Any]:
    """Resolve attribution for a wrapped claim.

    Priority: explicit CLI flags > CHIMERA_* env > active session > legacy defaults.
    Unknown stays unknown.
    """
    env_agent = os.environ.get("CHIMERA_AGENT")
    env_model = os.environ.get("CHIMERA_MODEL")
    session = active_session or {}

    agent_id = explicit_agent or env_agent or session.get("agent_app") or "unknown-agent"
    model_version = explicit_model or env_model or session.get("model")

    resolved: dict[str, Any] = {
        "agent_id": agent_id,
        "model_version": model_version,
    }
    if active_session is not None:
        resolved["harness_id"] = session.get("harness_id")
        resolved["attribution_confidence"] = session.get("attribution_confidence")
        resolved["identity_source"] = session.get("identity_source")
    return resolved


def _wrap_pytest(parsed: argparse.Namespace) -> int:
    command_args = list(parsed.wrapped)
    # Strip leading '--' separator if present (allows: wrap --task-type lint -- ruff check .)
    if command_args and command_args[0] == "--":
        command_args = command_args[1:]

    task_type = parsed.task_type or os.environ.get("CHIMERA_TASK_TYPE") or "test"
    claim_time = datetime.now(UTC)
    git_evidence, git_metadata = capture_git_evidence(root=Path.cwd(), claim_time=claim_time)

    extra_metadata: dict[str, object] = {"git": git_metadata}
    _store = MemoryStore.from_paths(root=Path.cwd())
    _current = _store.current_session()

    # No-write mode: run command but skip all ledger writes
    _no_write = bool(os.environ.get("CHIMERA_DQ_NO_WRITE", ""))
    if not _no_write and _current is None:
        import sys as _sys
        print(
            "Warning: no active session. Run:\n"
            "  chimera-memory session start --branch <branch> --task-label <label>"
            " --agent <agent> --model <model> --harness-id <id>",
            file=_sys.stderr,
        )

    attribution = _resolve_wrap_attribution(
        active_session=_current,
        explicit_agent=parsed.agent_id,
        explicit_model=parsed.model_version,
    )
    agent_id = attribution["agent_id"]
    model_version = attribution["model_version"]

    if _current is not None:
        extra_metadata["session_id"] = _current["session_id"]
        for key in ("harness_id", "attribution_confidence", "identity_source"):
            value = attribution.get(key)
            if value is not None:
                extra_metadata[key] = value

    cmd_display = " ".join(command_args) if command_args else "(empty)"
    is_pytest = command_args and command_args[0] == "pytest"

    # --- data-quality metadata: validate and inject if provided ---
    try:
        if getattr(parsed, "failure_origin", None):
            extra_metadata[K_FAILURE_ORIGIN] = validate_failure_origin(parsed.failure_origin)
        if getattr(parsed, "verification_scope", None):
            extra_metadata[K_VERIFICATION_SCOPE] = validate_verification_scope(
                parsed.verification_scope
            )
        if getattr(parsed, "scope_paths", None):
            extra_metadata[K_SCOPE_PATHS] = list(parsed.scope_paths)
        for attr, key in (
            ("scope_intent", K_SCOPE_INTENT),
            ("repair_loop_id", K_REPAIR_LOOP_ID),
            ("repair_of_claim_id", K_REPAIR_OF_CLAIM_ID),
            ("baseline_claim_id", K_BASELINE_CLAIM_ID),
            ("residual_out_of_scope", K_RESIDUAL_OUT_OF_SCOPE),
        ):
            val = getattr(parsed, attr, None)
            if val:
                extra_metadata[key] = val
        if getattr(parsed, "repair_phase", None):
            extra_metadata[K_REPAIR_PHASE] = validate_repair_phase(parsed.repair_phase)
    except ValueError as exc:
        print(f"error: {exc}", file=__import__("sys").stderr)
        return 2

    # --- targeted warnings (non-fatal, stderr only) ---
    import sys as _warn_sys
    if not getattr(parsed, "scope_paths", None):
        print(
            "[chimera-memory] warning: --scope-path not set; "
            "preflight intelligence will not anchor this claim.",
            file=_warn_sys.stderr,
        )
    if not getattr(parsed, "failure_origin", None):
        print(
            "[chimera-memory] warning: failure_origin is missing or unknown; "
            "DQ cohort outputs may exclude this claim.",
            file=_warn_sys.stderr,
        )
    if getattr(parsed, "repair_phase", None) and not getattr(parsed, "repair_loop_id", None):
        print(
            "[chimera-memory] warning: --repair-phase set but --repair-loop-id is missing; "
            "repair-loop lessons will not be generated.",
            file=_warn_sys.stderr,
        )

    claim_id = record_claim(
        title=f"{cmd_display} will pass",
        summary=f"Wrapped command is expected to exit 0: {cmd_display}",
        predicted=True,
        evidence=[
            {
                "ref_type": EvidenceRefType.EXTERNAL,
                "ref_id": f"cmd:{claim_time.isoformat()}",
                "available_at": claim_time,
            }
        ]
        + git_evidence,
        claim_time=claim_time,
        confidence=parsed.confidence,
        agent_id=agent_id,
        model_version=model_version,
        task_type=task_type,
        extra_metadata=extra_metadata,
    ) if not _no_write else "no-write-00000000-0000-0000-0000-000000000000"
    result = run_pytest(command_args) if is_pytest else run_command(command_args)
    observed_at = datetime.now(UTC)
    if not _no_write:
        settle_claim(
            claim_id,
            result.observed,
            observed_at,
            event_metadata={
                "exit_code": result.exit_code,
                "command": result.command,
                "wrapped_args": command_args,
                "duration_seconds": result.duration_seconds,
                "stdout_excerpt": _redact(result.stdout_excerpt),
                "stderr_excerpt": _redact(result.stderr_excerpt),
            },
        )
        export_report()  # noqa: F841  # kept for side-effects
    outcome = "VALIDATED" if result.observed else "CONTRADICTED"
    cmd_display = " ".join(str(a) for a in command_args[:3])
    if len(command_args) > 3:
        cmd_display += " …"
    witness = ""
    if not result.observed and result.stderr_excerpt:
        witness = f" witness={result.stderr_excerpt.strip()[:80]!r}"
    elif not result.observed and result.stdout_excerpt:
        witness = f" witness={result.stdout_excerpt.strip()[:80]!r}"
    print(
        f"{outcome} claim_id={claim_id[:8]} exit_code={result.exit_code}"
        f" command={cmd_display!r}{witness}"
    )
    if _no_write:
        print("[chimera-memory] CHIMERA_DQ_NO_WRITE set — claim not recorded")
    return result.exit_code


def _plain_report(report: dict[str, object]) -> str:
    lines = ["Reliability report"]
    groups = report.get("groups", [])
    if isinstance(groups, list):
        for group in groups:
            lines.append(json.dumps(group, sort_keys=True))
    lines.append("")
    lines.append(
        "Note: This report includes all claim groups, including pre-attribution records. "
        "For dogfood gate progress and clean-claim counts, use: chimera-memory status"
    )
    return "\n".join(lines)


def _plain_drift(result: dict[str, object]) -> str:
    lines = ["Drift advisory"]
    groups = result.get("groups", [])
    if isinstance(groups, list):
        for group in groups:
            if isinstance(group, dict):
                lines.append(
                    f"{group.get('group')}: {group.get('status')} "
                    f"shift={group.get('score_shift')} {group.get('message')}"
                )
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# session subcommand handlers
# -----------------------------------------------------------------------------


def _handle_session(parsed: argparse.Namespace) -> int:
    sub = parsed.session_command
    try:
        if sub == "start":
            return _session_start(parsed)
        if sub == "end":
            return _session_end(parsed)
        if sub == "list":
            return _session_list(parsed)
        if sub == "current":
            return _session_current(parsed)
    except RuntimeError as exc:
        print(f"error: {exc}", file=__import__("sys").stderr)
        return 1
    print(f"session: unknown subcommand '{sub}'", file=__import__("sys").stderr)
    return 2


def _memory_root(parsed: argparse.Namespace) -> Path:
    """Resolve the memory root from --memory-dir (or cwd fallback)."""
    md = getattr(parsed, "memory_dir", None)
    return Path(md).resolve() if md else Path.cwd()


def _session_start(parsed: argparse.Namespace) -> int:
    root = _memory_root(parsed)
    sid = start_session(
        repo_path=root,
        branch=parsed.branch,
        task_label=parsed.task_label,
        agent_app=parsed.agent,
        model=parsed.model,
        harness_id=getattr(parsed, "harness_id", None),
    )
    print(sid)
    return 0


def _session_end(parsed: argparse.Namespace) -> int:
    root = _memory_root(parsed)
    # --status is an alias for --final-status; --final-status takes precedence
    raw_status = parsed.final_status or getattr(parsed, "status", None)
    final = FinalStatus(raw_status.lower()) if raw_status else None
    sid = end_session(repo_path=root, final_status=final)
    store = MemoryStore.from_paths(root=root)
    session_dict = store.get_session(sid)
    if session_dict is None:
        print(f"error: session {sid} not found", file=__import__("sys").stderr)
        return 1
    receipt = build_receipt(session_dict, root=root)
    if parsed.json:
        print(format_receipt_json(receipt), end="")
    else:
        print(format_receipt_text(receipt), end="")
    return 0


def _session_list(parsed: argparse.Namespace) -> int:
    root = _memory_root(parsed)
    store = MemoryStore.from_paths(root=root)
    closed = store.list_sessions()
    if not closed:
        print("No closed sessions.")
        return 0
    print(f"{'SESSION_ID':<40} {'TASK':<40} {'STATUS':<10} {'ENDED'}")
    for s_dict in closed:
        s = Session.from_dict(s_dict)
        ended = (s.ended_at or "")[:19]
        status = s.final_status.value if s.final_status else "unknown"
        task = s.task_label[:38] + ".." if len(s.task_label) > 40 else s.task_label
        print(f"{s.session_id:<40} {task:<40} {status:<10} {ended}")
    return 0


def _session_current(parsed: argparse.Namespace) -> int:
    root = _memory_root(parsed)
    store = MemoryStore.from_paths(root=root)
    current = store.current_session()
    if current is None:
        print("No open session.")
        return 0
    s = Session.from_dict(current)
    print(f"open session: {s.session_id}")
    print(f"  task:   {s.task_label}")
    print(f"  agent:  {s.agent_app}")
    print(f"  model:  {s.model}")
    print(f"  branch: {s.branch}")
    print(f"  start:  {s.started_at}")
    return 0


# -----------------------------------------------------------------------------
# receipt subcommand handlers
# -----------------------------------------------------------------------------


def _handle_receipt(parsed: argparse.Namespace) -> int:
    sub = getattr(parsed, "receipt_command", None)
    if sub == "show":
        return _receipt_show(parsed)
    if sub == "latest":
        return _receipt_latest(parsed)
    if sub == "bundle":
        return _receipt_bundle(parsed)
    print(f"receipt: unknown subcommand '{sub}'", file=__import__("sys").stderr)
    return 2


def _receipt_latest(parsed: argparse.Namespace) -> int:
    root = _memory_root(parsed)
    store = MemoryStore.from_paths(root=root)
    closed = store.list_sessions()
    if not closed:
        print(
            "No closed sessions found.\n"
            "Start one with:\n"
            "  chimera-memory session start --branch <branch> --task-label <task> --agent <name>\\n"
            "  chimera-memory wrap -- <verification-command>\n"
            "  chimera-memory session end --status PASSED",
            file=__import__("sys").stderr,
        )
        return 1
    session_dict = closed[0]
    receipt = build_receipt(session_dict, root=root)
    return _emit_receipt(receipt, parsed)


def _emit_receipt(receipt: dict, parsed: argparse.Namespace) -> int:
    """Render receipt to stdout or --output file in text/json/markdown/github-summary format."""
    from chimera_memory.receipt import (
        format_receipt_github_summary,
        format_receipt_json,
        format_receipt_text,
    )

    fmt = getattr(parsed, "receipt_format", None)
    use_json = parsed.json or fmt == "json"
    use_md = getattr(parsed, "markdown", False) or fmt == "markdown"
    use_github = fmt == "github-summary"
    if use_json:
        content = format_receipt_json(receipt)
    elif use_md:
        content = format_receipt_markdown(receipt)
    elif use_github:
        content = format_receipt_github_summary(receipt)
    else:
        content = format_receipt_text(receipt)
    output_path = getattr(parsed, "receipt_output", None)
    if output_path:
        import os
        tmp = output_path + ".tmp"
        Path(tmp).write_text(content, encoding="utf-8")
        os.replace(tmp, output_path)
    else:
        print(content, end="")
    return 0


def _receipt_bundle(parsed: argparse.Namespace) -> int:
    """Write receipt + status + reliability + verify + optional preflight into a directory."""
    from chimera_memory.integrity import verify_integrity
    from chimera_memory.receipt import format_receipt_github_summary, format_receipt_json
    from chimera_memory.reliability import build_reliability_summary

    root = _memory_root(parsed)
    store = MemoryStore.from_paths(root=root)
    closed = store.list_sessions()
    if not closed:
        print("No closed sessions to bundle.", file=__import__("sys").stderr)
        return 1

    out_dir = Path(parsed.bundle_output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    receipt = build_receipt(closed[0], root=root)

    def _write(name: str, content: str) -> None:
        tmp = out_dir / f".{name}.tmp"
        tmp.write_text(content, encoding="utf-8")
        __import__("os").replace(tmp, out_dir / name)

    # Optional preflight section
    preflight_report = None
    if getattr(parsed, "bundle_include_preflight", False):
        try:
            from chimera_memory.preflight import (
                build_preflight,
                format_preflight_markdown,
                infer_scopes_from_git,
            )
            scope_paths = list(getattr(parsed, "bundle_scope_paths", None) or [])
            if getattr(parsed, "bundle_from_git", False):
                scope_paths = list(dict.fromkeys(scope_paths + infer_scopes_from_git(root)[1]))
            preflight_report = build_preflight(store, scope_paths=scope_paths)
            _write("preflight.json", json.dumps(preflight_report.to_dict(), sort_keys=True))
            _write("preflight.md", format_preflight_markdown(preflight_report))
        except Exception as exc:
            _write("preflight.json", json.dumps({"error": str(exc)}, sort_keys=True))

    _write("receipt.md", format_receipt_markdown(receipt))
    _write("receipt.json", format_receipt_json(receipt))
    _write("github-summary.md",
           format_receipt_github_summary(receipt, preflight_report=preflight_report))

    from chimera_memory.ledger import build_dogfood_status
    try:
        _write("status.json", json.dumps(build_dogfood_status(root=root), sort_keys=True))
    except Exception:
        pass
    try:
        _write("reliability.json", json.dumps(build_reliability_summary(store).to_dict(),
                                              sort_keys=True))
    except Exception:
        pass
    try:
        from chimera_memory.query import build_claim_read_model
        failures_data = [{"claim_id": c.claim_id, "status": c.claim_status.value,
                          "title": c.title} for c in build_claim_read_model(store).failures]
        _write("failures.json", json.dumps({"failures": failures_data}, sort_keys=True))
    except Exception:
        pass
    try:
        _write("verify.json", json.dumps(verify_integrity(store.memory_dir).to_dict(),
                                         sort_keys=True))
    except Exception:
        pass

    files = sorted(p.name for p in out_dir.iterdir() if not p.name.startswith("."))

    # Generate README explaining bundle contents
    readme_lines = [
        "# Chimera Memory Receipt Bundle",
        "",
        "Session receipt and verification artifacts for sharing or CI upload.",
        "",
        "## Contents",
        "",
    ]
    file_descriptions: dict[str, str] = {
        "README.md": "This file — explains bundle contents and safety",
        "receipt.md": "Human-readable session receipt",
        "receipt.json": "Machine-readable session receipt",
        "github-summary.md": "GitHub-flavored markdown summary for PR comments or CI",
        "status.json": "Dogfood reliability status snapshot",
        "reliability.json": "Reliability segment summary",
        "failures.json": "List of CONTRADICTED claims (failures) in this session",
        "verify.json": "Integrity verification result",
        "preflight.md": "Preflight advisory in markdown",
        "preflight.json": "Preflight advisory in JSON",
    }
    for f in files:
        desc = file_descriptions.get(f, "Additional artifact")
        readme_lines.append(f"- `{f}` — {desc}")
    readme_lines += [
        "",
        "## Safety",
        "",
        "- This bundle does NOT contain raw `.chimera-memory/` ledger files.",
        "- Command arguments and witness output are redacted.",
        "- No tokens, API keys, or private file paths should appear.",
        "- If you find a private path or secret in this bundle, please report it.",
        "",
        "## Not included",
        "",
        "- `claims.jsonl` / `sessions.jsonl` / `integrity.jsonl` (raw ledger)",
        "- `index.sqlite` / `append_state.json` (derived caches)",
        "- `.chimera-memory/` directory",
        "",
        "## Note",
        "",
        "This is a local receipt — not hosted/cloud. Data stays on your machine",
        "unless you explicitly share this bundle.",
    ]
    _write("README.md", "\n".join(readme_lines) + "\n")

    files = sorted(p.name for p in out_dir.iterdir() if not p.name.startswith("."))
    print(f"Bundle written to {out_dir}/ ({len(files)} files): {', '.join(files)}")
    return 0

def _receipt_show(parsed: argparse.Namespace) -> int:
    root = _memory_root(parsed)
    store = MemoryStore.from_paths(root=root)
    session_dict = store.get_session(parsed.session_id)
    if session_dict is None:
        print(f"error: session {parsed.session_id} not found", file=__import__("sys").stderr)
        return 1
    receipt = build_receipt(session_dict, root=root)
    return _emit_receipt(receipt, parsed)


_KNOWN_FAILURE_ORIGINS = (
    "organic_real",
    "controlled_real",
    "invocation_artifact",
    "test_first_contract",
    "synthetic",
)

_REPAIR_PHASES = (
    "baseline",
    "repair_attempt",
    "same_scope_after_fix",
    "regression_check",
    "none",
)


def _agent_guide(parsed: argparse.Namespace) -> int:
    agent = getattr(parsed, "guide_agent", "generic")
    harness_note = ""
    if agent == "kiro":
        harness_note = "\n  Kiro harness flag: --harness-id kiro-cli  (use --agent kiro)"
    elif agent == "codex":
        harness_note = "\n  Codex harness flag: --harness-id codex-cli  (use --agent codex)"

    guide = f"""\
CHIMERA MEMORY — AGENT PROTOCOL ({agent})
══════════════════════════════════════════════════════════

CLASSIFICATION RULES — failure_origin
──────────────────────────────────────
Use EXACTLY ONE of these values per wrap:

  organic_real        Real failure encountered while doing actual work.
                      USE THIS for genuine bugs, type errors, test failures
                      you hit organically during a task.

  controlled_real     Real failure in a controlled/fixture run.
                      Use when you deliberately trigger a known-bad state.

  invocation_artifact Flaky environment failure: network timeout, disk error,
                      missing env var, CI resource contention.
                      NOT the code's fault.

  test_first_contract Tests written BEFORE the implementation (TDD red phase).
                      NOT organic_real — expected to fail by design.

  synthetic           Fabricated or scaffolded scenario.
                      NOT organic_real — you made it up.

RULE: never label test_first_contract or synthetic as organic_real.
      Doing so corrupts M2B readiness and blocks the project.

SESSION PROTOCOL — exact sequence
──────────────────────────────────
1. Run preflight first (advisory; always safe):

     chimera-memory preflight --scope-path <your-scope>

2. Start session:

     chimera-memory session start \\
       --branch <branch> \\
       --task-label "<short description>" \\
       --agent <agent> \\
       --model <model>{harness_note}

3. Wrap each verification command:

     chimera-memory wrap \\
       --failure-origin organic_real \\
       --scope-path <your-scope> \\
       --verification-scope package \\
       -- <command>

   --scope-path is REQUIRED for preflight intelligence to anchor the claim.
   --failure-origin is REQUIRED for DQ cohort outputs.

4. End session:

     chimera-memory session end --status PASSED   # or FAILED

5. Verify integrity:

     chimera-memory verify

6. Bundle receipt (always run this at end of task):

     chimera-memory receipt bundle \\
       --output-dir ./receipts \\
       --include-preflight \\
       --scope-path <your-scope>

REPAIR-LOOP PHASES — exact semantics
─────────────────────────────────────
baseline:
  the real failing run (should be CONTRADICTED)

repair_attempt:
  optional intermediate attempts during repair

same_scope_after_fix:
  rerun the SAME check on the SAME scope after the fix
  → this is what closes the repair loop as fixed_same_scope
  → CRITICAL: must be same command, same scope, after actual code fix

regression_check:
  broader or later validation
  → produces later_regression_validated
  → does NOT close the loop as fixed_same_scope
  → does NOT substitute for same_scope_after_fix

none:
  not part of a repair loop

CRITICAL RULE: regression_check does NOT close a repair loop.
               Only same_scope_after_fix closes a repair loop.

CRITICAL RULE: Do not manufacture baseline failures to satisfy M2B.
               Only use repair_loop_id when a real organic_real failure occurs.

When you hit a real organic_real failure and fix it:

Step 1 — baseline (first failing run):
  chimera-memory wrap \\
    --failure-origin organic_real \\
    --scope-path <scope> \\
    --repair-loop-id <stable-slug>  # e.g. fix-preflight-scope-2026-06 \\
    --repair-phase baseline \\
    -- <command>

Step 2 — fix the code.

Step 3 — same_scope_after_fix (rerun SAME command SAME scope after fix):
  chimera-memory wrap \\
    --failure-origin organic_real \\
    --scope-path <scope> \\
    --repair-loop-id <same-slug> \\
    --repair-phase same_scope_after_fix \\
    -- <same command>

  → This produces repair_status: fixed_same_scope in preflight intelligence.

Step 4 — regression_check (broader later validation, optional):
  chimera-memory wrap \\
    --failure-origin organic_real \\
    --scope-path <scope> \\
    --repair-loop-id <same-slug> \\
    --repair-phase regression_check \\
    -- <broader command>

  → This produces repair_status: later_regression_validated.

NOTE: regression_check does NOT produce fixed_same_scope.
      Only same_scope_after_fix produces fixed_same_scope.

M2B READINESS NOTE
──────────────────
M2B BLOCKED in a fresh ledger is EXPECTED. Do not reclassify tests or
fabricate failures to unblock it. It unblocks when organic_real failures
accumulate honestly (target: 5 organic_real_failed claims).
"""
    print(guide)
    return 0


def _template(parsed: argparse.Namespace) -> int:
    sub = getattr(parsed, "template_command", None)
    if sub != "dogfood":
        print(
            "template: specify a subcommand. Available: dogfood",
            file=__import__("sys").stderr,
        )
        return 1
    scope = parsed.template_scope_path

    # Determine checks based on known scopes; fall back to placeholders
    known_memory = scope.rstrip("/") in (
        "packages/chimera-memory",
        "./packages/chimera-memory",
    )
    known_types = scope.rstrip("/") in (
        "packages/chimera-memory-types",
        "./packages/chimera-memory-types",
    )

    if known_memory:
        checks = [
            f'pytest {scope}/tests -m "not slow" --tb=short -q',
            f"mypy {scope}/src",
            f"ruff check {scope}/src {scope}/tests",
        ]
    elif known_types:
        checks = [
            f"mypy {scope}/src",
            f"ruff check {scope}/src",
        ]
    else:
        checks = [
            "# EDIT: replace with your test command, e.g. pytest <scope>/tests -q",
            "# EDIT: replace with your type-check command, e.g. mypy <scope>/src",
            "# EDIT: replace with your lint command, e.g. ruff check <scope>/src",
        ]

    wrap_lines = "\n\n".join(
        f"chimera-memory wrap \\\n"
        f"  --failure-origin organic_real \\\n"
        f"  --scope-path {scope} \\\n"
        f"  --verification-scope package \\\n"
        f"  -- {cmd}"
        for cmd in checks
    )

    template = f"""\
# ── CHIMERA MEMORY DOGFOOD SESSION TEMPLATE ──────────────────────────
# Scope: {scope}
# Edit placeholders (<...>) before running.
# ─────────────────────────────────────────────────────────────────────

# 1. Preflight advisory (always run first)
chimera-memory preflight --scope-path {scope}

# 2. Start session
chimera-memory session start \\
  --branch <your-branch> \\
  --task-label "<short description of this task>" \\
  --agent <agent> \\
  --model <model> \\
  --harness-id <harness>

# 3. Wrap verification commands
{wrap_lines}

# 4. End session
chimera-memory session end --status PASSED

# 5. Verify integrity
chimera-memory verify

# 6. Bundle receipt
chimera-memory receipt bundle \\
  --output-dir ./receipts \\
  --include-preflight \\
  --scope-path {scope}

# ── REAL BUG REPAIR-LOOP PATTERN ──────────────────────────────────────
# Use only when a real command fails due to a real code/test/type/lint defect.
# Do NOT use repair_loop_id for normal passing validation.
#
# Step 1 — baseline (the real failing run):
# chimera-memory wrap \\
#   --failure-origin organic_real \\
#   --scope-path {scope} \\
#   --verification-scope package \\
#   --repair-loop-id fix-<slug>-<date> \\
#   --repair-phase baseline \\
#   -- <failing check>
#
# Step 2 — fix the code.
#
# Step 3 — same_scope_after_fix (SAME check, SAME scope, after fix):
# chimera-memory wrap \\
#   --failure-origin organic_real \\
#   --scope-path {scope} \\
#   --verification-scope package \\
#   --repair-loop-id fix-<slug>-<date> \\
#   --repair-phase same_scope_after_fix \\
#   -- <same failing check>
#
# NOTE: regression_check does NOT close the loop.
#       Only same_scope_after_fix produces fixed_same_scope.
# ──────────────────────────────────────────────────────────────────────
"""
    print(template)
    return 0


def _bundle(parsed: argparse.Namespace) -> int:
    """Handle bundle inspect/diff subcommands."""
    cmd = getattr(parsed, "bundle_command", None)
    if cmd == "inspect":
        return _bundle_inspect(parsed)
    if cmd == "diff":
        return _bundle_diff(parsed)
    print("Usage: chimera-memory bundle {inspect,diff} ...")
    return 2


def _bundle_inspect(parsed: argparse.Namespace) -> int:
    """Read-only inspection of a receipt or evidence bundle."""
    import re

    bundle_path = Path(parsed.bundle_path).resolve()
    if not bundle_path.is_dir():
        print(f"Error: {parsed.bundle_path} is not a directory", file=__import__("sys").stderr)
        return 1

    files = sorted(
        p.name for p in bundle_path.iterdir()
        if p.is_file() and not p.name.startswith(".")
    )

    # Detect bundle type
    if "receipt.json" in files or "receipt.md" in files:
        bundle_type = "receipt"
    elif "manifest.json" in files and "events.jsonl" in files:
        bundle_type = "evidence"
    else:
        bundle_type = "unknown"

    # Expected files
    RECEIPT_EXPECTED = {"README.md", "receipt.json", "receipt.md", "verify.json"}
    EVIDENCE_EXPECTED = {"README.md", "manifest.json", "events.jsonl"}
    expected = RECEIPT_EXPECTED if bundle_type == "receipt" else (
        EVIDENCE_EXPECTED if bundle_type == "evidence" else set()
    )
    missing = sorted(expected - set(files))

    # Sensitive files that should NOT be in a shared bundle
    SENSITIVE_NAMES = {"claims.jsonl", "sessions.jsonl", "integrity.jsonl",
                       "index.sqlite", "append_state.json"}
    sensitive_found = sorted(SENSITIVE_NAMES & set(files))

    # Check for .chimera-memory directory
    has_chimera_dir = any(
        p.is_dir() and p.name == ".chimera-memory" for p in bundle_path.iterdir()
    )

    # Scan text files for private paths and token patterns (cap at 1MB per file)
    TOKEN_PATTERNS = [
        r"pypi-[A-Za-z0-9]",
        r"ghp_[A-Za-z0-9]{10,}",
        r"github_pat_[A-Za-z0-9_]{20,}",
        r"sk-[A-Za-z0-9]{20,}",
        r"-----BEGIN PRIVATE KEY",
    ]
    PRIVATE_PATH_PATTERNS = [r"/Users/[a-zA-Z]", r"C:\\Users\\", r"/home/[a-zA-Z]"]
    token_hits: list[str] = []
    private_path_hits: list[str] = []
    MAX_SCAN_SIZE = 1_048_576  # 1MB

    for fname in files:
        fp = bundle_path / fname
        if fp.stat().st_size > MAX_SCAN_SIZE:
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for pat in TOKEN_PATTERNS:
            if re.search(pat, text):
                token_hits.append(fname)
                break
        for pat in PRIVATE_PATH_PATTERNS:
            if re.search(pat, text):
                private_path_hits.append(fname)
                break

    # Determine status
    readme_present = "README.md" in files
    manifest_present = "manifest.json" in files

    if sensitive_found or has_chimera_dir:
        status = "CRITICAL"
    elif token_hits or private_path_hits:
        status = "WARNING"
    elif bundle_type == "unknown":
        status = "UNKNOWN"
    else:
        status = "OK"

    # Build notes/next_actions
    notes: list[str] = []
    next_actions: list[str] = []
    if sensitive_found:
        notes.append(f"Raw ledger files found: {', '.join(sensitive_found)}")
        next_actions.append("Remove raw ledger files before sharing.")
    if has_chimera_dir:
        notes.append(".chimera-memory/ directory found inside bundle")
        next_actions.append("Remove .chimera-memory/ directory before sharing.")
    if token_hits:
        notes.append(f"Token-like strings in: {', '.join(token_hits)}")
        next_actions.append("Review and redact token-like content before sharing.")
    if private_path_hits:
        notes.append(f"Private paths in: {', '.join(private_path_hits)}")
        next_actions.append("Review and redact private paths before sharing.")
    if not notes:
        notes.append("No safety issues detected.")
        next_actions.append("Safe to review/share if contents are expected.")

    result = {
        "schema_version": 1,
        "path": str(bundle_path),
        "bundle_type": bundle_type,
        "status": status,
        "file_count": len(files),
        "present_files": files,
        "missing_expected_files": missing,
        "unexpected_sensitive_files": sensitive_found,
        "raw_ledger_files_found": bool(sensitive_found) or has_chimera_dir,
        "token_like_hits": token_hits,
        "private_path_hits": private_path_hits,
        "readme_present": readme_present,
        "manifest_present": manifest_present,
        "notes": notes,
        "next_actions": next_actions,
    }

    if parsed.json:
        print(json.dumps(result, sort_keys=True))
        return 0

    # Text output
    print(f"Bundle inspection: {parsed.bundle_path}")
    print(f"Type:   {bundle_type}")
    print(f"Status: {status}")
    print(f"Files:  {len(files)}")
    print()
    if missing:
        print(f"Missing expected: {', '.join(missing)}")
    if sensitive_found:
        print(f"⚠ Sensitive files: {', '.join(sensitive_found)}")
    if has_chimera_dir:
        print("⚠ .chimera-memory/ directory found")
    if token_hits:
        print(f"⚠ Token-like strings in: {', '.join(token_hits)}")
    if private_path_hits:
        print(f"⚠ Private paths in: {', '.join(private_path_hits)}")
    print()
    print(f"README:   {'yes' if readme_present else 'missing'}")
    print(f"Manifest: {'yes' if manifest_present else 'N/A'}")
    print()
    for action in next_actions:
        print(f"→ {action}")
    return 0


def _bundle_diff(parsed: argparse.Namespace) -> int:
    """Read-only comparison of two receipt or evidence bundles."""
    old_path = Path(parsed.old_bundle).resolve()
    new_path = Path(parsed.new_bundle).resolve()

    for p, label in [(old_path, "old"), (new_path, "new")]:
        if not p.is_dir():
            print(
                f"Error: {label} bundle path is not a directory: {p}",
                file=__import__("sys").stderr,
            )
            return 1

    def _files(d: Path) -> set[str]:
        return {
            p.name for p in d.iterdir()
            if p.is_file() and not p.name.startswith(".")
        }

    def _type(files: set[str]) -> str:
        if "receipt.json" in files or "receipt.md" in files:
            return "receipt"
        if "manifest.json" in files and "events.jsonl" in files:
            return "evidence"
        return "unknown"

    def _read_json(d: Path, name: str) -> dict | None:
        f = d / name
        if f.exists() and f.stat().st_size < 1_048_576:
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                pass
        return None

    old_files = _files(old_path)
    new_files = _files(new_path)
    old_type = _type(old_files)
    new_type = _type(new_files)

    # Compatibility
    if old_type == "unknown" or new_type == "unknown":
        status = "UNKNOWN"
        compatible = False
    elif old_type != new_type:
        status = "INCOMPATIBLE"
        compatible = False
    else:
        status = "OK"
        compatible = True

    # File delta
    added = sorted(new_files - old_files)
    removed = sorted(old_files - new_files)
    common = sorted(old_files & new_files)

    # Extract counts
    def _count(d: Path, btype: str) -> dict:
        counts: dict[str, int | str | None] = {}
        if btype == "receipt":
            status_data = _read_json(d, "status.json")
            if status_data:
                counts["claim_count"] = status_data.get(
                    "settled_unique_claims",
                    status_data.get("unique_claims"),
                )
                counts["failure_count"] = len(
                    (_read_json(d, "failures.json") or {}).get("failures", [])
                )
            verify_data = _read_json(d, "verify.json")
            if verify_data:
                counts["integrity_status"] = verify_data.get("status")
                counts["broken_records"] = verify_data.get("broken_records")
        elif btype == "evidence":
            manifest = _read_json(d, "manifest.json")
            if manifest:
                counts["claim_count"] = manifest.get("claim_count")
                counts["event_count"] = manifest.get("event_count")
        return counts

    old_counts = _count(old_path, old_type) if compatible else {}
    new_counts = _count(new_path, new_type) if compatible else {}

    # Compute deltas
    def _delta(key: str) -> int | None:
        o = old_counts.get(key)
        n = new_counts.get(key)
        if isinstance(o, int) and isinstance(n, int):
            return n - o
        return None

    claim_delta = _delta("claim_count")
    failure_delta = _delta("failure_count")
    event_delta = _delta("event_count")

    old_integrity = old_counts.get("integrity_status")
    new_integrity = new_counts.get("integrity_status")
    integrity_change = (
        f"{old_integrity} → {new_integrity}"
        if old_integrity and new_integrity and old_integrity != new_integrity
        else None
    )

    # Warnings
    warnings: list[str] = []
    notes: list[str] = []
    if not compatible:
        warnings.append(
            f"Bundle types differ: old={old_type}, new={new_type}"
        )
    if failure_delta and failure_delta > 0:
        warnings.append(f"Failures increased by {failure_delta}")
    if integrity_change:
        warnings.append(f"Integrity status changed: {integrity_change}")

    next_actions: list[str] = []
    if not compatible:
        next_actions.append("Compare bundles of the same type.")
    elif warnings:
        next_actions.append("Review warnings before sharing.")
    else:
        next_actions.append("Bundles are comparable. Safe to review delta.")

    result = {
        "schema_version": 1,
        "old_path": str(old_path),
        "new_path": str(new_path),
        "old_bundle_type": old_type,
        "new_bundle_type": new_type,
        "status": status,
        "compatible": compatible,
        "file_delta": {
            "added": added,
            "removed": removed,
            "common": common,
        },
        "claim_count_delta": claim_delta,
        "failure_count_delta": failure_delta,
        "evidence_event_count_delta": event_delta,
        "integrity_status_change": integrity_change,
        "notes": notes,
        "warnings": warnings,
        "next_actions": next_actions,
    }

    if parsed.json:
        print(json.dumps(result, sort_keys=True))
        return 0

    # Text output
    print("Bundle diff:")
    print(f"  old: {parsed.old_bundle} ({old_type})")
    print(f"  new: {parsed.new_bundle} ({new_type})")
    print(f"  status: {status}")
    print()
    if added:
        print(f"  files added:   {', '.join(added)}")
    if removed:
        print(f"  files removed: {', '.join(removed)}")
    print(f"  files common:  {len(common)}")
    print()
    if claim_delta is not None:
        print(f"  claim count:   {'+' if claim_delta >= 0 else ''}{claim_delta}")
    if failure_delta is not None:
        print(f"  failure count: {'+' if failure_delta >= 0 else ''}{failure_delta}")
    if event_delta is not None:
        print(f"  event count:   {'+' if event_delta >= 0 else ''}{event_delta}")
    if integrity_change:
        print(f"  integrity:     {integrity_change}")
    print()
    for w in warnings:
        print(f"  ⚠ {w}")
    for action in next_actions:
        print(f"  → {action}")
    return 0


def _quickstart(parsed: argparse.Namespace) -> int:
    """Print a guided first-run example. No writes."""
    print("""\
Chimera Memory — First 10 Minutes

1. Initialize the local ledger:

   chimera-memory init

2. Wrap a verification command:

   chimera-memory wrap \\
     --scope-path . \\
     --failure-origin organic_real \\
     --verification-scope package \\
     -- pytest tests/ -q

3. Check ledger integrity:

   chimera-memory verify

4. View your session receipt:

   chimera-memory doctor

5. Create a portable receipt bundle:

   chimera-memory receipt bundle \\
     --output-dir ./receipt \\
     --include-preflight \\
     --scope-path .

6. Inspect the bundle before sharing:

   chimera-memory bundle inspect ./receipt

7. Compare two bundles (optional):

   chimera-memory bundle diff ./old-receipt ./new-receipt

Notes:
  - All data stays on your machine.
  - M2B scoring, model ranking, and routing are not built.
  - Run 'chimera-memory doctor' for a health check at any point.
  - Run 'chimera-memory agent-guide --agent generic' for agent protocol.\
""")
    return 0


def _demo(parsed: argparse.Namespace) -> int:
    """Run a safe local demo of the full Chimera Memory value loop."""
    import os
    import sys
    import tempfile

    output_dir = getattr(parsed, "demo_output_dir", None)
    if output_dir:
        root = Path(output_dir).resolve()
        if root.exists() and any(root.iterdir()):
            print(
                f"Error: output directory is not empty: {root}",
                file=sys.stderr,
            )
            return 1
        root.mkdir(parents=True, exist_ok=True)
    else:
        root = Path(tempfile.mkdtemp(prefix="chimera-demo-"))

    workspace = root / "workspace"
    receipt_dir = root / "receipt"
    workspace.mkdir(parents=True, exist_ok=True)

    # Save and switch cwd
    orig_cwd = Path.cwd()
    os.chdir(workspace)

    try:
        print("Chimera Memory Demo")
        print("=" * 40)
        print()

        # 1. Init
        print("1. Initializing demo ledger...")
        main(["init"])
        print("   ✓ Ledger created")

        # 2. Session
        print("2. Starting demo session...")
        main(["session", "start", "--branch", "demo",
              "--task-label", "demo", "--agent", "demo",
              "--model", "demo", "--harness-id", "demo"])
        print("   ✓ Session started")

        # 3. Wrap
        print("3. Wrapping a verification command...")
        main(["wrap", "--scope-path", ".",
              "--failure-origin", "organic_real",
              "--verification-scope", "package",
              "--", sys.executable, "-c",
              "print('hello chimera-memory')"])
        print("   ✓ Command wrapped")

        # 4. Session end
        print("4. Ending session...")
        main(["session", "end", "--status", "PASSED"])
        print("   ✓ Session closed")

        # 5. Verify
        print("5. Verifying integrity...")
        main(["verify"])
        print("   ✓ Integrity OK")

        # 6. Receipt bundle
        print("6. Creating receipt bundle...")
        main(["receipt", "bundle", "--output-dir", str(receipt_dir),
              "--include-preflight", "--scope-path", "."])
        print(f"   ✓ Receipt bundle at {receipt_dir}/")

        # 7. Bundle inspect
        print("7. Inspecting receipt bundle...")
        main(["bundle", "inspect", str(receipt_dir)])
        print("   ✓ Bundle inspection complete")

    finally:
        os.chdir(orig_cwd)

    print()
    print("=" * 40)
    print("Demo complete!")
    print()
    print(f"  Workspace: {workspace}")
    print(f"  Receipt:   {receipt_dir}")
    print()
    print("Try next:")
    print(f"  chimera-memory bundle inspect {receipt_dir}")
    print("  chimera-memory quickstart")
    print()
    print("To use in your own project:")
    print("  cd <your-project>")
    print("  chimera-memory init")
    print("  chimera-memory wrap --scope-path . "
          "--failure-origin organic_real "
          "--verification-scope package -- <your-test-command>")
    return 0


_CHECKS_PRESET_PYTHON = """\
# chimera-memory.checks.toml — Project verification recipe
# Run with: chimera-memory checks run

schema_version = 1
scope_path = "."
verification_scope = "package"
failure_origin = "organic_real"

[[checks]]
name = "python-version"
command = ["python", "--version"]

# [[checks]]
# name = "pytest"
# command = ["pytest", "tests/", "-q"]

# [[checks]]
# name = "mypy"
# command = ["mypy", "src/"]

# [[checks]]
# name = "ruff"
# command = ["ruff", "check", "src/"]
"""


def _write_generated_toml(spec: Any, path: Path) -> None:
    """Write a generated claim spec to a TOML file for review."""
    lines = [
        f'intent = {spec.intent!r}',
        f'scope_path = {spec.scope_path!r}',
        f'predicted_outcome = {spec.predicted_outcome!r}',
    ]
    for cmd in spec.falsifiers:
        lines += ["", "[[falsifiers]]", f"command = {cmd!r}"]
    for cmd in spec.must_not_break:
        lines += ["", "[[must_not_break]]", f"command = {cmd!r}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved generated spec to {path}")


def _claim(parsed: argparse.Namespace) -> int:
    """Handle claim lock/list/show/settle/report subcommands."""
    import sys

    from chimera_memory.claim_lock import (
        ClaimError,
        ClaimSpec,
        load_spec_from_toml,
        lock_claim,
        safe_command_from_string,
        settle_claim,
    )

    sub = getattr(parsed, "claim_command", None)
    root = Path.cwd()
    memory_dir = getattr(parsed, "memory_dir", None)
    store = (
        MemoryStore.from_paths(memory_dir=memory_dir)
        if memory_dir
        else MemoryStore.from_paths(root=root)
    )
    if not store.memory_dir.exists():
        store.initialize()

    if sub == "validate":
        from chimera_memory.claim_lock import validate_claim_spec

        try:
            spec = _build_claim_spec(parsed, safe_command_from_string, ClaimSpec,
                                     load_spec_from_toml)
        except ClaimError as exc:
            if parsed.json:
                print(json.dumps({"valid": False, "errors": [str(exc)], "warnings": []},
                                 indent=2))
            else:
                print(f"error: {exc}", file=sys.stderr)
            return 1
        result = validate_claim_spec(spec, root=root)
        if parsed.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            if result["errors"]:
                for e in result["errors"]:
                    print(f"error: {e}", file=sys.stderr)
            if result["warnings"]:
                for w in result["warnings"]:
                    print(f"warning: {w}")
            if result["valid"]:
                if not result["warnings"]:
                    print("claim.toml is valid with no warnings.")
                else:
                    print(
                        f"claim.toml is valid with {len(result['warnings'])} warning(s). "
                        "Warnings do not block locking."
                    )
        return 0 if result["valid"] else 1

    if sub == "lock":
        try:
            if getattr(parsed, "claim_auto", False):
                from chimera_memory.claim_lock import build_claim_spec_from_auto_inputs
                spec, extra_meta = build_claim_spec_from_auto_inputs(
                    intent=getattr(parsed, "claim_intent", None),
                    scope_path=getattr(parsed, "claim_scope_path", None),
                    falsifiers_json=getattr(parsed, "claim_falsifiers_json", None),
                    must_not_break_json=getattr(parsed, "claim_mnb_json", None),
                    predicted_outcome=getattr(parsed, "claim_predicted", None),
                    store=store,
                    root=root,
                    from_checks=getattr(parsed, "claim_from_checks", False),
                )
                # Run validation; hard errors refuse; warnings accumulate.
                from chimera_memory.claim_lock import validate_claim_spec
                validation = validate_claim_spec(spec, root=root)
                if not validation["valid"]:
                    for e in validation["errors"]:
                        print(f"error: {e}", file=sys.stderr)
                    return 1
                extra_warnings = extra_meta.get("extra_warnings", [])
                all_warnings = validation["warnings"] + extra_warnings

                if getattr(parsed, "claim_dry_run", False):
                    # Dry-run: validate + show, no lock.
                    out: dict[str, Any] = {
                        "claim_id": None,
                        "status": "DRY_RUN",
                        "auto_lock": True,
                        "dry_run": True,
                        "generated_spec": extra_meta["generated_spec"],
                        "validation": {
                            "valid": validation["valid"],
                            "errors": validation["errors"],
                            "warnings": all_warnings,
                        },
                    }
                    if parsed.json:
                        print(json.dumps(out, indent=2, sort_keys=True))
                    else:
                        print("Dry-run — claim NOT locked.")
                        print(f"  intent:    {spec.intent}")
                        print(f"  scope:     {spec.scope_path}")
                        for w in all_warnings:
                            print(f"  warning:   {w}")
                    return 0

                # Save generated spec if requested.
                save_spec_path = getattr(parsed, "claim_save_spec", None)
                if save_spec_path:
                    _write_generated_toml(spec, Path(save_spec_path))

                record = lock_claim(store, spec, root=root)
                if parsed.json:
                    out_json: dict[str, Any] = {
                        "claim_id": record["claim_id"],
                        "status": record["settlement"]["status"],
                        "auto_lock": True,
                        "generated_spec": extra_meta["generated_spec"],
                        "validation": {
                            "errors": [],
                            "warnings": record["quality"]["warnings"],
                        },
                        "attribution": record["attribution"],
                    }
                    print(json.dumps(out_json, indent=2, sort_keys=True))
                else:
                    print(f"Locked claim {record['claim_id']}")
                    print(f"  intent:  {record['intent']}")
                    print(f"  scope:   {record['scope_path']}")
                    print(f"  quality: {record['quality']['claim_quality']}")
                    for w in record["quality"]["warnings"]:
                        print(f"  warning: {w}")
                    print(f"\nNext: chimera-memory claim settle {record['claim_id']}")
                return 0

            spec = _build_claim_spec(parsed, safe_command_from_string, ClaimSpec,
                                     load_spec_from_toml)
            record = lock_claim(store, spec, root=root)
        except ClaimError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if parsed.json:
            print(json.dumps(record, indent=2, sort_keys=True))
        else:
            print(f"Locked claim {record['claim_id']}")
            print(f"  intent:  {record['intent']}")
            print(f"  scope:   {record['scope_path']}")
            print(f"  quality: {record['quality']['claim_quality']}")
            warnings = record["quality"]["warnings"]
            if warnings:
                for w in warnings:
                    print(f"  warning: {w}")
            print(f"\nNext: chimera-memory claim settle {record['claim_id']}")
        return 0

    if sub == "list":
        claims = store.latest_claim_locks()
        if parsed.json:
            print(json.dumps(claims, indent=2, sort_keys=True))
            return 0
        if not claims:
            print("No claims locked yet. Run: chimera-memory claim lock --from-file claim.toml")
            return 0
        for c in claims:
            status = c.get("settlement", {}).get("status", "LOCKED")
            print(f"{c['claim_id']}  {status:<12}  {c.get('intent', '')}")
        return 0

    if sub in ("show", "report"):
        claim_id = parsed.claim_id
        found = store.latest_claim_lock(claim_id)
        if found is None:
            print(f"error: no claim with id {claim_id!r}", file=sys.stderr)
            return 1
        if parsed.json:
            print(json.dumps(found, indent=2, sort_keys=True))
        else:
            print(_format_claim_text(found))
        return 0

    if sub == "settle":
        try:
            record = settle_claim(store, parsed.claim_id, root=root)
        except ClaimError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        status = record["settlement"]["status"]
        if parsed.json:
            print(json.dumps(record, indent=2, sort_keys=True))
        else:
            print(_format_claim_text(record))
        # CONTRADICTED settles cleanly but signals a failed check via exit code.
        return 0 if status != "CONTRADICTED" else 1

    print("Usage: chimera-memory claim {lock,list,show,settle,report}", file=sys.stderr)
    return 2


def _build_claim_spec(parsed, safe_command_from_string, ClaimSpec, load_spec_from_toml):
    """Build a ClaimSpec from --from-file or flag-based inputs."""
    from chimera_memory.claim_lock import ClaimError, _normalize_scope

    from_file = getattr(parsed, "claim_from_file", None)
    if from_file:
        return load_spec_from_toml(Path(from_file))

    intent = getattr(parsed, "claim_intent", None)
    scope_path = getattr(parsed, "claim_scope_path", None)
    if not intent or not scope_path:
        raise ClaimError(
            "provide --from-file, or both --intent and --scope-path"
        )
    falsifiers = [
        safe_command_from_string(s) for s in (getattr(parsed, "claim_falsifiers", None) or [])
    ]
    must_not_break = [
        safe_command_from_string(s)
        for s in (getattr(parsed, "claim_must_not_break", None) or [])
    ]
    return ClaimSpec(
        intent=intent.strip(),
        scope_path=_normalize_scope(scope_path),
        predicted_outcome=getattr(parsed, "claim_predicted", "all pass"),
        falsifiers=falsifiers,
        must_not_break=must_not_break,
    )


def _format_claim_text(record: dict[str, Any]) -> str:
    lines = [
        f"Claim {record['claim_id']}",
        f"  intent:    {record.get('intent', '')}",
        f"  scope:     {record.get('scope_path', '')}",
        f"  predicted: {record.get('predicted_outcome', '')}",
        f"  status:    {record.get('settlement', {}).get('status', 'LOCKED')}",
    ]
    quality = record.get("quality", {})
    lines.append(f"  quality:   {quality.get('claim_quality', 'unknown')}")
    if quality.get("warnings"):
        lines.append(f"  warnings:  {', '.join(quality['warnings'])}")
    falsifiers = record.get("falsifiers", [])
    if falsifiers:
        lines.append("  falsifiers:")
        for e in falsifiers:
            lines.append(f"    - {' '.join(e.get('command', []))}")
    must = record.get("must_not_break", [])
    if must:
        lines.append("  must-not-break:")
        for e in must:
            lines.append(f"    - {' '.join(e.get('command', []))}")
    settlement = record.get("settlement", {})
    if settlement.get("settled_at"):
        changed = settlement.get("changed_files", [])
        drift = settlement.get("scope_drift_files", [])
        lines.append(f"  settled_at: {settlement['settled_at']}")
        lines.append(f"  changed_files: {len(changed)}")
        if drift:
            lines.append(f"  scope_drift_files: {', '.join(drift)}")
        for cr in settlement.get("commands", []):
            cmd = " ".join(cr.get("command", []))
            lines.append(f"    [{cr.get('outcome')}] {cmd}")
    lines.append("")
    lines.append("Note: this is settled evidence, not proof of correctness.")
    return "\n".join(lines)


def _apply_evidence_gate(result: dict, fail_on: str) -> int:
    """Evaluate the opt-in evidence gate after the receipt is produced.

    Gate messages go to stderr so stdout (e.g. the pr-comment) stays clean.
    Returns 0 when the policy passes or is 'never', and 2 when the policy is not
    met. The gate enforces evidence policy, not code correctness.
    """
    import sys as _sys

    from chimera_memory.xray import evaluate_evidence_gate

    if fail_on == "never":
        print("Chimera Memory evidence gate disabled: fail-on=never.", file=_sys.stderr)
        return 0
    gate = evaluate_evidence_gate(result, fail_on=fail_on)
    if gate.passed:
        print(f"Chimera Memory evidence gate passed: policy '{fail_on}'.", file=_sys.stderr)
        return 0
    print(
        f"Chimera Memory evidence gate failed: policy '{fail_on}' was not met.",
        file=_sys.stderr,
    )
    print("This scores evidence quality, not code correctness.", file=_sys.stderr)
    print("See PR_EVIDENCE.md for details.", file=_sys.stderr)
    for reason in gate.reasons:
        print(f"  - {reason}", file=_sys.stderr)
    return 2


def _proof_debt(parsed: argparse.Namespace) -> int:
    """Handle proof-debt: summarize local evidence debt from the X-Ray result.

    Local-only and read-only. Built from existing X-Ray fields; adds no new
    detection and changes no verdict semantics.
    """
    from chimera_memory.proof_debt import compute_proof_debt, render_proof_debt_text
    from chimera_memory.xray import generate_xray

    root = Path.cwd()
    memory_dir = getattr(parsed, "memory_dir", None)
    store = (
        MemoryStore.from_paths(memory_dir=memory_dir)
        if memory_dir
        else MemoryStore.from_paths(root=root)
    )
    if not store.memory_dir.exists():
        store.initialize()

    result = generate_xray(store, root=root)
    debt = compute_proof_debt(result)
    if getattr(parsed, "json", False):
        print(json.dumps(debt, indent=2, sort_keys=True))
    else:
        print(render_proof_debt_text(debt))
    return 0


def _xray(parsed: argparse.Namespace) -> int:
    """Handle xray generate."""
    import sys

    from chimera_memory.xray import generate_xray, render_markdown, render_pr_comment

    sub = getattr(parsed, "xray_command", None)
    if sub != "generate":
        print("Usage: chimera-memory xray generate", file=sys.stderr)
        return 2

    root = Path.cwd()
    memory_dir = getattr(parsed, "memory_dir", None)
    store = (
        MemoryStore.from_paths(memory_dir=memory_dir)
        if memory_dir
        else MemoryStore.from_paths(root=root)
    )
    if not store.memory_dir.exists():
        store.initialize()

    result = generate_xray(
        store,
        root=root,
        base=getattr(parsed, "xray_base", None),
        head=getattr(parsed, "xray_head", None),
    )

    if parsed.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return _apply_evidence_gate(result, getattr(parsed, "xray_fail_on", "never"))

    markdown = render_markdown(result)
    output = getattr(parsed, "xray_output", None)
    if output:
        out_path = Path(output)
        out_path.write_text(markdown, encoding="utf-8")
        print(f"Wrote {out_path}")

    fmt = getattr(parsed, "xray_format", "markdown")
    if fmt == "pr-comment":
        print(render_pr_comment(result))
    elif output:
        # Full report already written to the file; echo the verdict to stdout.
        print(f"\n{result['verdict']}")
    else:
        print(markdown)
    return _apply_evidence_gate(result, getattr(parsed, "xray_fail_on", "never"))


def _hooks(parsed: argparse.Namespace) -> int:
    """Handle hooks install/uninstall/status."""
    import sys as _sys

    from chimera_memory.hooks import install_hooks, show_hooks_status, uninstall_hooks

    sub = getattr(parsed, "hooks_command", None)
    root = Path.cwd()

    if sub == "install":
        result = install_hooks(
            root,
            dry_run=getattr(parsed, "hooks_dry_run", False),
            force=getattr(parsed, "force", False),
        )
        if parsed.json:
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if result["dry_run"]:
            print("Dry-run — no files written.")
        for f in result["installed_files"]:
            print(f"  Created: {f}")
        for e in result["patched_settings_events"]:
            print(f"  Patched: {result['settings_path']} ({e})")
        for w in result["warnings"]:
            print(f"  warning: {w}")
        if result["installed_files"] or result["patched_settings_events"]:
            print("\nChimera hooks installed. Open Claude Code in this project.")
            print("Next: create .chimera/hooks.toml with falsifiers, then start a coding prompt.")
            print(
                "Optional: CHIMERA_INTENT and CHIMERA_FALSIFIERS_JSON can override config"
                " for advanced use."
            )
        else:
            print("Nothing to install (use --force to overwrite).")
        return 0

    if sub == "uninstall":
        result = uninstall_hooks(root)
        if parsed.json:
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        for f in result["removed_files"]:
            print(f"  Removed: {f}")
        print("Chimera hooks uninstalled.")
        return 0

    if sub == "status":
        result = show_hooks_status(root)
        if parsed.json:
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        status = "installed" if result["installed"] else "not fully installed"
        print(f"Chimera hooks: {status}")
        for name, present in result["scripts"].items():
            icon = "✓" if present else "✗"
            print(f"  {icon} .claude/hooks/{name}")
        for event, registered in result["settings_hooks"].items():
            icon = "✓" if registered else "✗"
            print(f"  {icon} .claude/settings.json ({event})")
        return 0

    if sub == "init":
        chimera_dir = root / ".chimera"
        hooks_toml = chimera_dir / "hooks.toml"
        if hooks_toml.exists() and not getattr(parsed, "force", False):
            print(f"{hooks_toml} already exists. Use --force to overwrite.")
            return 1
        chimera_dir.mkdir(exist_ok=True)
        _HOOKS_TOML_TEMPLATE = """\
[claude_hooks]
auto_lock = true
scope_path = "."

# Put the narrowest command that proves the task worked here.
# Python examples:
# falsifiers = [["uv", "run", "pytest", "tests/test_specific_area.py", "-q"]]
# falsifiers = [[".venv/bin/python", "-m", "pytest", "tests/test_specific_area.py", "-q"]]
#
# Node/TypeScript example:
# falsifiers = [["pnpm", "run", "build"]]
# falsifiers = [["npm", "test"]]

falsifiers = [
  ["python3", "-m", "pytest", "tests/test_specific_area.py", "-q"]
]

# Put broader checks that must keep passing here.
# Examples:
# must_not_break = [["uv", "run", "pytest", "-q"]]
# must_not_break = [["pnpm", "run", "build"], ["pnpm", "test"]]

must_not_break = [
  ["python3", "-m", "pytest", "-q"]
]
"""
        hooks_toml.write_text(_HOOKS_TOML_TEMPLATE, encoding="utf-8")
        print(f"Created {hooks_toml}")
        print("Edit the falsifiers and must_not_break commands for your project before use.")
        return 0

    if sub == "prompt-submit":
        import sys as _sys

        from chimera_memory.hooks import (
            attempt_prompt_auto_lock,
            extract_prompt_from_hook_input,
            format_prompt_submit_output,
        )

        raw_stdin = _sys.stdin.read()
        prompt_text = extract_prompt_from_hook_input(raw_stdin)
        dry_run = getattr(parsed, "prompt_dry_run", False)
        result_auto = attempt_prompt_auto_lock(prompt_text, root=root, dry_run=dry_run)

        if parsed.json:
            print(json.dumps(result_auto, indent=2, sort_keys=True))
        else:
            output = format_prompt_submit_output(result_auto)
            if output.strip():
                print(output)
        return 0  # never block Claude

    print("Usage: chimera-memory hooks {install,uninstall,status}", file=_sys.stderr)
    return 2


def _mcp(parsed: argparse.Namespace) -> int:
    """Handle mcp serve."""
    import sys as _sys

    sub = getattr(parsed, "mcp_command", None)
    if sub != "serve":
        print("Usage: chimera-memory mcp serve [--allow-write] [--allow-execute]",
              file=_sys.stderr)
        return 2

    from chimera_memory.mcp_server import ToolPermissions, serve_mcp

    perms = ToolPermissions(
        allow_write=getattr(parsed, "mcp_allow_write", False),
        allow_execute=getattr(parsed, "mcp_allow_execute", False),
    )
    serve_mcp(perms, root=Path.cwd())
    return 0


def _checks(parsed: argparse.Namespace) -> int:
    """Handle checks init/run subcommands."""
    cmd = getattr(parsed, "checks_command", None)
    if cmd == "init":
        return _checks_init(parsed)
    if cmd == "run":
        return _checks_run(parsed)
    print("Usage: chimera-memory checks {init,run}")
    return 2


def _checks_init(parsed: argparse.Namespace) -> int:
    """Create a starter chimera-memory.checks.toml."""
    import sys

    config_path = Path.cwd() / "chimera-memory.checks.toml"
    if config_path.exists():
        print(
            f"Error: {config_path} already exists. Remove it first.",
            file=sys.stderr,
        )
        return 1
    config_path.write_text(_CHECKS_PRESET_PYTHON, encoding="utf-8")
    print(f"Created {config_path.name}")
    print("\nNext: chimera-memory checks run")
    return 0


def _checks_run(parsed: argparse.Namespace) -> int:
    """Run checks from config and record through Chimera Memory."""
    import sys
    import tomllib

    config_path = Path(parsed.config).resolve()
    if not config_path.exists():
        print(
            f"Error: config not found: {config_path}\n"
            "Run: chimera-memory checks init",
            file=sys.stderr,
        )
        return 1

    with open(config_path, "rb") as f:
        config = tomllib.load(f)

    checks = config.get("checks", [])
    if not checks:
        print("Error: no [[checks]] defined in config.", file=sys.stderr)
        return 1

    scope_path = config.get("scope_path", ".")
    verification_scope = config.get("verification_scope", "package")
    failure_origin = config.get("failure_origin", "organic_real")

    # Validate commands are lists
    for i, check in enumerate(checks):
        cmd = check.get("command")
        if not isinstance(cmd, list) or not all(isinstance(s, str) for s in cmd):
            print(
                f"Error: checks[{i}].command must be a list of strings.",
                file=sys.stderr,
            )
            return 1

    print("Chimera Memory checks run")
    print(f"Config: {config_path.name}")
    print(f"Checks: {len(checks)}")
    print()

    # Init ledger if needed
    store = MemoryStore.from_paths()
    if not store.memory_dir.exists():
        store.initialize()
        _ensure_gitignore(Path.cwd())

    # Start session
    main(["session", "start", "--branch", "checks",
          "--task-label", f"checks run ({config_path.name})",
          "--agent", "checks", "--model", "local",
          "--harness-id", "chimera-checks"])

    all_passed = True
    check_results: list[dict[str, object]] = []
    for check in checks:
        name = check.get("name", "unnamed")
        cmd = check["command"]
        wrap_args = [
            "wrap",
            "--scope-path", scope_path,
            "--failure-origin", failure_origin,
            "--verification-scope", verification_scope,
            "--", *cmd,
        ]
        rc = main(wrap_args)
        check_status = "VALIDATED" if rc == 0 else "CONTRADICTED"
        check_results.append({
            "name": name,
            "command": cmd,
            "status": check_status,
            "exit_code": rc,
        })
        if rc == 0:
            print(f"  ✓ {name}")
        else:
            print(f"  ✗ {name}")
            all_passed = False
            break  # stop on first failure

    # End session
    status = "PASSED" if all_passed else "FAILED"
    main(["session", "end", "--status", status])

    # Verify
    main(["verify"])

    # Bundle if requested
    bundle_dir = None
    if getattr(parsed, "bundle", False):
        bundle_dir = Path(
            getattr(parsed, "checks_output_dir", None) or "./chimera-run"
        ).resolve()
        receipt_dir = bundle_dir / "receipt"
        main(["receipt", "bundle", "--output-dir", str(receipt_dir),
              "--include-preflight", "--scope-path", scope_path])

        # Generate reports
        report_data = {
            "schema_version": 1,
            "result": status,
            "config_path": config_path.name,
            "scope_path": scope_path,
            "verification_scope": verification_scope,
            "failure_origin": failure_origin,
            "checks": check_results,
            "receipt_path": "receipt",
            "verify_status": "OK",
            "next_actions": [
                f"chimera-memory bundle inspect {receipt_dir}",
            ],
        }
        (bundle_dir / "report.json").write_text(
            json.dumps(report_data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        # Markdown report
        md_lines = [
            "# Chimera Memory Check Run Report",
            "",
            f"**Result:** {status}",
            f"**Config:** {config_path.name}",
            f"**Scope:** {scope_path}",
            "",
            "## Checks",
            "",
            "| Name | Status | Exit |",
            "|------|--------|------|",
        ]
        for cr in check_results:
            icon = "✓" if cr["status"] == "VALIDATED" else "✗"
            md_lines.append(
                f"| {cr['name']} | {icon} {cr['status']} | {cr['exit_code']} |"
            )
        md_lines += [
            "",
            "## Next",
            "",
            f"- `chimera-memory bundle inspect {receipt_dir}`",
            "",
            "## Note",
            "",
            "M2B scoring, model ranking, and routing are not built.",
        ]
        (bundle_dir / "report.md").write_text(
            "\n".join(md_lines) + "\n", encoding="utf-8"
        )

    print()
    print(f"Result: {status}")
    if bundle_dir:
        print(f"Receipt: {bundle_dir / 'receipt'}")
        print(f"\nNext: chimera-memory bundle inspect {bundle_dir / 'receipt'}")

    return 0 if all_passed else 1
