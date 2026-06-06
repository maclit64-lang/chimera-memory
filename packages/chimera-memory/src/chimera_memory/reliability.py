"""Chimera Memory M2A: read-only raw ledger reliability summary.

Computes per-agent/model/task validation rates from settled clean claims.

Design constraints:
- read-only: does not write to store, GraphSource, substrate, or any external system
- raw rates only: failure-quality classification is NOT stored in claim metadata,
  so organic-only scoring is not possible; rates include all CONTRADICTED outcomes
- no ranking: does not claim any model is "best" or route work
- no autonomy: output is informational only

Usage:
    from chimera_memory.reliability import build_reliability_summary
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from chimera_memory_types.knowledge import ClaimStatus

if TYPE_CHECKING:
    from chimera_memory.storage import MemoryStore

_INSUFFICIENT_THRESHOLD = 5
_LOW_THRESHOLD = 25

_SYNTHETIC_MARKERS = ("python -c", "SystemExit")


# ---------------------------------------------------------------------------
# data classes
# ---------------------------------------------------------------------------


@dataclass
class ReliabilityGroup:
    agent_id: str
    model_version: str | None
    task_type: str | None
    total: int
    validated: int
    contradicted: int
    validation_rate: float
    failure_rate: float
    confidence: str  # INSUFFICIENT | LOW | MEDIUM
    possible_synthetic_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "model_version": self.model_version,
            "task_type": self.task_type,
            "total": self.total,
            "validated": self.validated,
            "contradicted": self.contradicted,
            "validation_rate": round(self.validation_rate, 4),
            "failure_rate": round(self.failure_rate, 4),
            "confidence": self.confidence,
            "possible_synthetic_count": self.possible_synthetic_count,
        }


@dataclass
class ReliabilitySummary:
    clean_claims: int
    groups_total: int
    failures_total: int
    by_agent_model_task: list[ReliabilityGroup] = field(default_factory=list)
    notes: dict[str, Any] = field(default_factory=dict)
    filters_applied: dict[str, str] = field(default_factory=dict)
    filtered_claim_count: int = 0
    unfiltered_claim_count: int = 0
    unknown_metadata_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "clean_claims": self.clean_claims,
            "groups_total": self.groups_total,
            "failures_total": self.failures_total,
            "by_agent_model_task": [g.to_dict() for g in self.by_agent_model_task],
            "notes": self.notes,
            "filters_applied": self.filters_applied,
            "filtered_claim_count": self.filtered_claim_count,
            "unfiltered_claim_count": self.unfiltered_claim_count,
            "unknown_metadata_count": self.unknown_metadata_count,
        }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _confidence(total: int) -> str:
    if total < _INSUFFICIENT_THRESHOLD:
        return "INSUFFICIENT"
    if total < _LOW_THRESHOLD:
        return "LOW"
    return "MEDIUM"


def _possible_synthetic(command: str | None) -> bool:
    if not command:
        return False
    return all(marker in command for marker in _SYNTHETIC_MARKERS)


def _get_command(claim: Any) -> str | None:
    sett = claim.settlement
    if not sett:
        return None
    events = sett.events or []
    if not events:
        return None
    emd = events[-1].metadata or {}
    args = emd.get("wrapped_args") or []
    return " ".join(str(a) for a in args) if args else None


# ---------------------------------------------------------------------------
# builder
# ---------------------------------------------------------------------------


def build_reliability_summary(
    store: MemoryStore,
    *,
    filters: dict[str, str] | None = None,
) -> ReliabilitySummary:
    """Build a read-only reliability summary from settled clean claims.

    Optional filters (all are exact-match against claim metadata):
      failure_origin, verification_scope, repair_phase, repair_loop_id

    Legacy claims without the filtered field count towards unknown_metadata_count
    and are excluded from the filtered result.
    """
    from chimera_memory.errata import effective_failure_origin, load_errata
    from chimera_memory.query import build_claim_read_model

    rm = build_claim_read_model(store)
    all_clean = rm.clean_claims
    unfiltered_count = len(all_clean)

    # Load errata for classification corrections
    errata_map = load_errata(store.memory_dir)
    errata_count = len(errata_map)

    # Apply filters — use effective metadata (errata-corrected) for failure_origin
    filters = filters or {}
    unknown_count = 0
    clean = all_clean
    if filters:
        filtered = []
        for c in all_clean:
            m = c.metadata or {}
            keep = True
            for fkey, val in filters.items():
                if fkey == "failure_origin":
                    claim_val = effective_failure_origin(c, errata_map)
                else:
                    claim_val = m.get(fkey)
                if claim_val is None:
                    unknown_count += 1
                    keep = False
                    break
                if claim_val != val:
                    keep = False
                    break
            if keep:
                filtered.append(c)
        clean = filtered

    # Group by (agent_id, model_version, task_type)
    groups: dict[tuple[str, str | None, str | None], list[Any]] = {}
    for c in clean:
        m = c.metadata or {}
        key = (
            str(m.get("agent_id") or "unknown"),
            str(m.get("model_version")) if m.get("model_version") is not None else None,
            str(m.get("task_type")) if m.get("task_type") else None,
        )
        groups.setdefault(key, []).append(c)

    result: list[ReliabilityGroup] = []
    for (agent_id, model_version, task_type), claims in sorted(groups.items()):
        validated = sum(1 for c in claims if c.claim_status == ClaimStatus.VALIDATED)
        contradicted = sum(1 for c in claims if c.claim_status == ClaimStatus.CONTRADICTED)
        total = len(claims)
        possible_synth = sum(1 for c in claims if _possible_synthetic(_get_command(c)))
        result.append(ReliabilityGroup(
            agent_id=agent_id,
            model_version=model_version,
            task_type=task_type,
            total=total,
            validated=validated,
            contradicted=contradicted,
            validation_rate=validated / total if total > 0 else 0.0,
            failure_rate=contradicted / total if total > 0 else 0.0,
            confidence=_confidence(total),
            possible_synthetic_count=possible_synth,
        ))

    failures_total = sum(g.contradicted for g in result)

    filtered_notes: dict[str, Any] = {
        "read_only": True,
        "no_routing": True,
        "no_autonomy": True,
        "no_model_ranking": True,
    }
    if filters:
        filtered_notes["filtered"] = True
        filtered_notes["caveat"] = (
            "Filtered reliability is descriptive only. "
            "It is not statistical proof, routing authority, or M2B drift."
        )
        if errata_count:
            filtered_notes["errata_applied_count"] = errata_count
            filtered_notes["errata_note"] = (
                f"{errata_count} claim(s) had failure_origin corrections applied via errata."
            )
    else:
        filtered_notes["classification_quality"] = (
            "raw ledger rates; failure-quality classification now available via "
            "--failure-origin / --organic-only filters"
        )
        if errata_count:
            filtered_notes["errata_applied_count"] = errata_count

    return ReliabilitySummary(
        clean_claims=len(clean),
        groups_total=len(result),
        failures_total=failures_total,
        by_agent_model_task=result,
        notes=filtered_notes,
        filters_applied=filters,
        filtered_claim_count=len(clean),
        unfiltered_claim_count=unfiltered_count,
        unknown_metadata_count=unknown_count,
    )


# ---------------------------------------------------------------------------
# text formatter
# ---------------------------------------------------------------------------


def format_reliability_text(summary: ReliabilitySummary) -> str:
    lines = [
        "Chimera Memory Reliability",
        "",
        "Read-only: yes",
    ]
    if summary.filters_applied:
        lines.append(f"Filters:       {summary.filters_applied}")
        lines.append(
            f"Claims:        {summary.filtered_claim_count} of "
            f"{summary.unfiltered_claim_count} (unknown metadata excluded: "
            f"{summary.unknown_metadata_count})"
        )
        lines.append(
            "Caveat:        Filtered reliability is descriptive only. "
            "Not statistical proof, routing authority, or M2B drift."
        )
    else:
        lines.append("Mode: raw ledger rates")
        lines.append("Warning: use --failure-origin or --organic-only to filter organic failures")
        lines.append("Warning: do not use this as model ranking or routing authority")
    lines += [
        "Note: [INSUFFICIENT/LOW/MEDIUM] labels = sample-size tier, not statistical confidence",
        "",
        f"Clean claims:  {summary.clean_claims}",
        f"Groups:        {summary.groups_total}",
        f"Failures:      {summary.failures_total}",
        "",
        "By agent / model / task:",
    ]

    current_agent_model: tuple[str, str | None] | None = None
    for g in summary.by_agent_model_task:
        am = (g.agent_id, g.model_version)
        if am != current_agent_model:
            lines.append(f"  {g.agent_id} / {g.model_version or 'unknown'}")
            current_agent_model = am
        task_label = g.task_type or "(all)"
        synth_note = (
            f" [~{g.possible_synthetic_count} possible synthetic]"
            if g.possible_synthetic_count else ""
        )
        lines.append(
            f"    {task_label:<20}"
            f"  n={g.total:<4}"
            f"  validated={g.validated:<4}"
            f"  contradicted={g.contradicted:<4}"
            f"  rate={g.validation_rate:.1%}"
            f"  [{g.confidence}]"
            f"{synth_note}"
        )

    return "\n".join(lines)
