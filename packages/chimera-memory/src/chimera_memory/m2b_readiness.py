"""Chimera Memory M2B Evidence Readiness Gate — v2 with DQ cohort model.

Separates all-ledger summary from DQ-cohort evaluation so legacy pre-DQ
claims do not make readiness mathematically impossible.

This module does NOT:
- compute M2B drift scores
- rank agents or models
- make routing or autonomy decisions
- imply statistical confidence

Thresholds are heuristics, not scientific proof.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from chimera_memory.storage import MemoryStore

SCHEMA_VERSION = 2

_THRESHOLDS = {
    "organic_claims_min": 25,      # total organic_real claims in evaluated cohort
    "organic_failures_min": 5,     # organic_real CONTRADICTED
    "comparable_groups_min": 2,    # groups with >= 10 organic_real claims
    "organic_per_group_min": 10,
    "repair_loops_min": 3,
    "unknown_pct_max": 20,         # only applied in all_ledger mode
    "dq_cohort_coverage_min": 80,  # % of cohort with both origin+scope labeled (dq mode)
}

_MODES = ("default", "dq_cohort", "all_ledger")


@dataclass
class GroupSummary:
    agent_id: str
    model_version: str | None
    task_type: str | None
    verification_scope: str | None
    total: int
    validated: int
    contradicted: int
    organic_real: int
    organic_real_failed: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "model_version": self.model_version,
            "task_type": self.task_type,
            "verification_scope": self.verification_scope,
            "total": self.total,
            "validated": self.validated,
            "contradicted": self.contradicted,
            "organic_real": self.organic_real,
            "organic_real_failed": self.organic_real_failed,
        }


@dataclass
class CohortSummary:
    total: int
    with_failure_origin: int
    with_verification_scope: int
    unknown_failure_origin: int
    unknown_verification_scope: int
    organic_real: int
    organic_real_failed: int
    synthetic: int
    invocation_artifact: int
    metadata_coverage_pct: float  # % with both origin+scope non-unknown

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "with_failure_origin": self.with_failure_origin,
            "with_verification_scope": self.with_verification_scope,
            "unknown_failure_origin": self.unknown_failure_origin,
            "unknown_verification_scope": self.unknown_verification_scope,
            "organic_real": self.organic_real,
            "organic_real_failed": self.organic_real_failed,
            "synthetic": self.synthetic,
            "invocation_artifact": self.invocation_artifact,
            "metadata_coverage_pct": round(self.metadata_coverage_pct, 1),
        }


@dataclass
class M2BReadinessReport:
    schema_version: int = SCHEMA_VERSION
    evaluation_mode: str = "default"
    m2b_ready: bool = False
    readiness_level: str = "blocked"   # blocked | weak | review_ready
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    thresholds: dict[str, Any] = field(default_factory=dict)
    all_ledger_summary: dict[str, Any] = field(default_factory=dict)
    dq_cohort_summary: dict[str, Any] = field(default_factory=dict)
    readiness_evaluation_summary: dict[str, Any] = field(default_factory=dict)
    effective_group_summaries: list[GroupSummary] = field(default_factory=list)
    repair_loop_summary: dict[str, Any] = field(default_factory=dict)
    notes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "evaluation_mode": self.evaluation_mode,
            "m2b_ready": self.m2b_ready,
            "readiness_level": self.readiness_level,
            "blockers": self.blockers,
            "warnings": self.warnings,
            "thresholds": self.thresholds,
            "all_ledger_summary": self.all_ledger_summary,
            "dq_cohort_summary": self.dq_cohort_summary,
            "readiness_evaluation_summary": self.readiness_evaluation_summary,
            "effective_group_summaries": [g.to_dict() for g in self.effective_group_summaries],
            "group_summaries_note": (
                "Effective (errata-corrected) groups only. "
                "Test fixtures and invocation_artifact groups are excluded from organic counts."
            ),
            "repair_loop_summary": self.repair_loop_summary,
            "notes": self.notes,
        }


def _is_dq_labeled(m: dict[str, Any], errata_origin: str | None = None) -> bool:
    """A claim is in the DQ cohort if it has any non-unknown DQ field."""
    fo = errata_origin if errata_origin is not None else m.get("failure_origin")
    vs = m.get("verification_scope")
    rl = m.get("repair_loop_id")
    return (
        (fo is not None and fo != "unknown")
        or (vs is not None and vs != "unknown")
        or bool(rl)
    )


def _cohort_summary(
    claims: list[Any],
    errata_map: dict[str, Any] | None = None,
) -> CohortSummary:
    from chimera_memory.errata import apply_errata
    from chimera_memory_types.knowledge import ClaimStatus

    _em = errata_map or {}
    _nu = (None, "unknown")
    total = len(claims)

    def _origin(c: Any) -> str | None:
        corrected = apply_errata(c, _em)
        return corrected if corrected is not None else (c.metadata or {}).get("failure_origin")

    with_fo = sum(1 for c in claims if _origin(c) not in _nu)
    with_vs = sum(1 for c in claims if (c.metadata or {}).get("verification_scope") not in _nu)
    both = sum(
        1 for c in claims
        if _origin(c) not in _nu
        and (c.metadata or {}).get("verification_scope") not in _nu
    )
    organic = [c for c in claims if _origin(c) == "organic_real"]
    return CohortSummary(
        total=total,
        with_failure_origin=with_fo,
        with_verification_scope=with_vs,
        unknown_failure_origin=total - with_fo,
        unknown_verification_scope=total - with_vs,
        organic_real=len(organic),
        organic_real_failed=sum(1 for c in organic if c.claim_status == ClaimStatus.CONTRADICTED),
        synthetic=sum(1 for c in claims if _origin(c) == "synthetic"),
        invocation_artifact=sum(1 for c in claims if _origin(c) == "invocation_artifact"),
        metadata_coverage_pct=(both / total * 100) if total else 0.0,
    )


def _group_summaries(
    claims: list[Any], errata_map: dict[str, Any] | None = None
) -> tuple[list[GroupSummary], int]:
    """Build effective group summaries (errata-corrected) and comparable group count.

    Only groups where effective failure_origin=organic_real are counted toward readiness.
    Groups driven entirely by test fixtures or invocation artifacts are excluded from
    comparable group counts even if their raw metadata shows organic_real.
    """
    from collections import defaultdict

    from chimera_memory.errata import effective_failure_origin
    from chimera_memory_types.knowledge import ClaimStatus

    errata = errata_map or {}
    groups: dict[tuple, list] = defaultdict(list)
    for c in claims:
        m = c.metadata or {}
        key = (
            str(m.get("agent_id") or "unknown"),
            str(m.get("model_version")) if m.get("model_version") else None,
            str(m.get("task_type")) if m.get("task_type") else None,
            str(m.get("verification_scope")) if m.get("verification_scope") else None,
        )
        groups[key].append(c)

    result: list[GroupSummary] = []
    for (agent_id, model_version, task_type, vs), gclaims in sorted(
        groups.items(), key=lambda kv: tuple(x or "" for x in kv[0])
    ):
        # Use effective (errata-corrected) failure_origin
        g_organic = [
            c for c in gclaims
            if effective_failure_origin(c, errata) == "organic_real"
        ]
        result.append(GroupSummary(
            agent_id=agent_id, model_version=model_version,
            task_type=task_type, verification_scope=vs,
            total=len(gclaims),
            validated=sum(1 for c in gclaims if c.claim_status == ClaimStatus.VALIDATED),
            contradicted=sum(1 for c in gclaims if c.claim_status == ClaimStatus.CONTRADICTED),
            organic_real=len(g_organic),
            organic_real_failed=sum(
                1 for c in g_organic if c.claim_status == ClaimStatus.CONTRADICTED
            ),
        ))

    comparable = sum(
        1 for g in result if g.organic_real >= _THRESHOLDS["organic_per_group_min"]
    )
    return result, comparable


def _repair_loop_summary(claims: list[Any]) -> tuple[dict[str, Any], int]:
    loops: dict[str, dict[str, int]] = {}
    for c in claims:
        m = c.metadata or {}
        rl = m.get("repair_loop_id")
        if rl:
            loops.setdefault(str(rl), {"baseline": 0, "same_scope_after_fix": 0, "other": 0})
            ph = str(m.get("repair_phase") or "other")
            bucket = ph if ph in ("baseline", "same_scope_after_fix") else "other"
            loops[str(rl)][bucket] += 1
    complete = sum(
        1 for lv in loops.values() if lv["baseline"] >= 1 and lv["same_scope_after_fix"] >= 1
    )
    return {
        "total_loops": len(loops),
        "complete_loops": complete,
        "loop_ids": sorted(loops.keys()),
    }, complete


def _evaluate_gates(
    cs: CohortSummary, comparable: int, complete_loops: int, *, dq_mode: bool
) -> tuple[list[str], list[str]]:
    """Return (blockers, warnings) for the evaluated cohort."""
    blockers: list[str] = []
    warnings: list[str] = []
    t = _THRESHOLDS

    if cs.total == 0:
        blockers.append("no claims in evaluated cohort")
        return blockers, warnings

    if dq_mode and cs.metadata_coverage_pct < t["dq_cohort_coverage_min"]:
        blockers.append(
            f"DQ-cohort coverage too low: {cs.metadata_coverage_pct:.0f}% < "
            f"{t['dq_cohort_coverage_min']}% "
            "(use both --failure-origin and --verification-scope)"
        )
    elif not dq_mode:
        unknown_pct = (
            (cs.unknown_failure_origin + cs.unknown_verification_scope)
            / (2 * cs.total) * 100
        )
        if unknown_pct > t["unknown_pct_max"]:
            blockers.append(
                f"metadata coverage too low: {100 - unknown_pct:.0f}% < "
                f"{100 - t['unknown_pct_max']}% "
                "(use --failure-origin and --verification-scope on wrap)"
            )

    if cs.organic_real < t["organic_claims_min"]:
        blockers.append(
            f"organic_real claims too few: {cs.organic_real} < {t['organic_claims_min']}"
        )
    if cs.organic_real_failed < t["organic_failures_min"]:
        blockers.append(
            f"organic_real failures too few: {cs.organic_real_failed} < {t['organic_failures_min']}"
        )
    if comparable < t["comparable_groups_min"]:
        blockers.append(
            f"comparable groups too few: {comparable} < {t['comparable_groups_min']} "
            f"(need >= {t['organic_per_group_min']} organic_real per group)"
        )
    if complete_loops < t["repair_loops_min"]:
        warnings.append(
            f"repair loops too few: {complete_loops} < {t['repair_loops_min']}"
        )
    if cs.invocation_artifact > 0:
        warnings.append(
            f"{cs.invocation_artifact} invocation_artifact failure(s) found in DQ cohort. "
            "Ensure shell quoting, paths, and tool invocations are correct before adding "
            "more organic_real evidence."
        )

    return blockers, warnings


def compute_m2b_readiness(
    store: MemoryStore,
    *,
    mode: str = "default",
    extra_clean_claims: list[Any] | None = None,
) -> M2BReadinessReport:
    """Compute a read-only M2B evidence readiness report.

    mode='default': evaluate DQ cohort if any DQ-labeled claims exist; else all-ledger.
    mode='dq_cohort': evaluate only DQ-labeled claims.
    mode='all_ledger': evaluate all clean claims (includes legacy unknowns).
    """
    from chimera_memory.errata import apply_errata, load_errata
    from chimera_memory.query import build_claim_read_model

    rm = build_claim_read_model(store)
    all_claims = list(rm.clean_claims)
    if extra_clean_claims:
        existing_ids = {c.claim_id for c in all_claims}
        all_claims = all_claims + [
            c for c in extra_clean_claims if c.claim_id not in existing_ids
        ]

    # Apply errata corrections to failure_origin (additive, non-destructive)
    errata_map = load_errata(store.memory_dir)
    errata_count = len(errata_map)

    def _effective_origin(c: Any) -> str | None:
        corrected = apply_errata(c, errata_map)
        if corrected is not None:
            return corrected
        return (c.metadata or {}).get("failure_origin")

    # Build cohorts
    dq_claims = [
        c for c in all_claims
        if _is_dq_labeled(
            c.metadata or {},
            errata_origin=apply_errata(c, errata_map),
        )
    ]
    legacy_count = len(all_claims) - len(dq_claims)

    all_cs = _cohort_summary(all_claims, errata_map)
    dq_cs = _cohort_summary(dq_claims, errata_map)

    # Determine evaluation cohort
    if mode == "all_ledger":
        eval_claims = all_claims
        eval_cs = all_cs
        actual_mode = "all_ledger"
        dq_mode = False
    elif mode == "dq_cohort" or (mode == "default" and dq_claims):
        eval_claims = dq_claims
        eval_cs = dq_cs
        actual_mode = "dq_cohort"
        dq_mode = True
    else:
        # default with no DQ claims → fall back to all_ledger
        eval_claims = all_claims
        eval_cs = all_cs
        actual_mode = "all_ledger"
        dq_mode = False

    group_sums, comparable = _group_summaries(eval_claims, errata_map=errata_map)
    rl_summary, complete_loops = _repair_loop_summary(eval_claims)
    blockers, warnings = _evaluate_gates(eval_cs, comparable, complete_loops, dq_mode=dq_mode)

    if blockers:
        level, ready = "blocked", False
    elif warnings:
        level, ready = "weak", False
    else:
        level, ready = "review_ready", True

    return M2BReadinessReport(
        evaluation_mode=actual_mode,
        m2b_ready=ready,
        readiness_level=level,
        blockers=blockers,
        warnings=warnings,
        thresholds=dict(_THRESHOLDS),
        all_ledger_summary={**all_cs.to_dict(), "total_clean_claims": len(all_claims)},
        dq_cohort_summary={
            **dq_cs.to_dict(),
            "legacy_unlabeled_claims": legacy_count,
            "comparable_groups": comparable,
            "legacy_excluded_from_dq": True,
            "legacy_exclusion_reason": (
                "Legacy claims predate DQ metadata and are not backfilled automatically. "
                "They remain visible in all_ledger_summary but are excluded from "
                "DQ-cohort readiness gates."
            ),
        },
        readiness_evaluation_summary={
            **eval_cs.to_dict(),
            "evaluated_claims": len(eval_claims),
            "comparable_groups": comparable,
        },
        effective_group_summaries=group_sums,
        repair_loop_summary=rl_summary,
        notes={
            "not_m2b": "This is a readiness gate, not M2B drift scoring.",
            "no_ranking": "No model ranking, routing, autonomy, or statistical confidence implied.",
            "cohort_note": (
                "Legacy unlabeled claims are excluded from DQ-cohort readiness "
                "but remain visible in all_ledger_summary."
            ),
            "thresholds_are_heuristics": "Gate thresholds are heuristics, not scientific proof.",
            "errata_applied": errata_count,
        },
    )


def format_readiness_text(report: M2BReadinessReport) -> str:
    lines = [
        "Chimera Memory M2B Readiness Gate",
        "",
        "This is a readiness gate, not M2B drift scoring.",
        "No model ranking, routing, autonomy, or statistical confidence implied.",
        "",
        f"Evaluation mode:  {report.evaluation_mode}",
        f"Readiness:        {report.readiness_level.upper()}",
        f"M2B ready:        {report.m2b_ready}",
        "",
    ]

    al = report.all_ledger_summary
    dq = report.dq_cohort_summary
    ev = report.readiness_evaluation_summary

    lines += [
        f"All clean claims:      {al.get('total_clean_claims', al.get('total', '?'))}",
        f"DQ-cohort claims:      {dq.get('total', '?')}",
        f"Legacy/unlabeled:      {dq.get('legacy_unlabeled_claims', '?')}",
        "",
        "Evaluated cohort:",
        f"  organic_real:        {ev.get('organic_real', '?')}",
        f"  organic_real_failed: {ev.get('organic_real_failed', '?')}",
        f"  comparable_groups:   {ev.get('comparable_groups', '?')}",
        f"  metadata_coverage:   {ev.get('metadata_coverage_pct', '?')}%",
        "",
    ]

    if report.evaluation_mode == "dq_cohort":
        lines.append(
            "Note: Legacy unlabeled claims are excluded from DQ-cohort readiness evaluation."
        )
        lines.append("")

    if report.blockers:
        lines.append("M2B NOT READY — blockers:")
        for b in report.blockers:
            lines.append(f"  - {b}")
    if report.warnings:
        lines.append("Warnings:")
        for w in report.warnings:
            lines.append(f"  - {w}")
    if not report.blockers and not report.warnings:
        lines.append("M2B MAY BE READY FOR DESIGN REVIEW, not automatic deployment.")

    rl = report.repair_loop_summary
    lines.append(f"\nRepair loops: {rl['total_loops']} total, {rl['complete_loops']} complete")
    return "\n".join(lines)
