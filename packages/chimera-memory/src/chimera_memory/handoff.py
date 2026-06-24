"""Ledger-derived handoff summary (Stage 2): the first practical read surface
over the projection stack.

Pipeline (reusing existing layers, no duplicated projection logic):

    ledger JSONL -> EvidenceEvent -> SettledClaim -> HandoffSummary

The handoff answers, for a human or the next agent: what claims exist, which
settled, what evidence is attached, what remains unresolved, and what to inspect
first. It is **advisory and local-only** — an evidence summary, never a
correctness, safety, merge, approval, or production-readiness signal, and not a
form of proof. It is strictly read-only.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chimera_memory.evidence_events import project_evidence_events
from chimera_memory.settled_claims import SettledClaim, fold_settled_claims
from chimera_memory.storage import MemoryStore

SCHEMA_VERSION = 1

ADVISORY = (
    "local evidence summary only; not a correctness, safety, merge, approval, "
    "or production-readiness signal"
)

# Reason codes for an unresolved claim, with inspection priority (lower first).
_REASON_PRIORITY = {
    "contradicted": 0,
    "no_settlement_record": 1,
    "unsettled_status": 2,
    "no_score_record": 3,
}
# Statuses that mean "settled cleanly enough to not flag on status alone".
_RESOLVED_STATUSES = frozenset({"validated", "supported", "settled"})


@dataclass(frozen=True)
class HandoffClaim:
    claim_id: str
    latest_status: str | None
    event_count: int
    has_claim_record: bool
    has_settlement_record: bool
    has_score_record: bool
    latest_exit_code: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "latest_status": self.latest_status,
            "event_count": self.event_count,
            "has_claim_record": self.has_claim_record,
            "has_settlement_record": self.has_settlement_record,
            "has_score_record": self.has_score_record,
            "latest_exit_code": self.latest_exit_code,
        }


@dataclass(frozen=True)
class HandoffOpenItem:
    claim_id: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"claim_id": self.claim_id, "reasons": list(self.reasons)}


@dataclass(frozen=True)
class HandoffTarget:
    claim_id: str
    reason: str  # the highest-priority reason to inspect this claim

    def to_dict(self) -> dict[str, Any]:
        return {"claim_id": self.claim_id, "reason": self.reason}


@dataclass(frozen=True)
class HandoffFilters:
    """The read-only filters applied to this handoff (echoed for transparency)."""

    session_id: str | None = None
    claim_id: str | None = None
    status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "claim_id": self.claim_id,
            "status": self.status,
        }


@dataclass(frozen=True)
class HandoffSummary:
    schema_version: int
    advisory: str
    filters: HandoffFilters
    event_count: int
    settled_claim_count: int
    claims: tuple[HandoffClaim, ...]
    open_or_unresolved: tuple[HandoffOpenItem, ...]
    next_inspection_targets: tuple[HandoffTarget, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "advisory": self.advisory,
            "filters": self.filters.to_dict(),
            "event_count": self.event_count,
            "settled_claim_count": self.settled_claim_count,
            "claims": [c.to_dict() for c in self.claims],
            "open_or_unresolved": [o.to_dict() for o in self.open_or_unresolved],
            "next_inspection_targets": [t.to_dict() for t in self.next_inspection_targets],
        }


def _reasons_for(claim: SettledClaim) -> tuple[str, ...]:
    """Derive unresolved-evidence reasons from existing SettledClaim fields only."""
    reasons: list[str] = []
    if claim.latest_status == "contradicted":
        reasons.append("contradicted")
    if not claim.has_settlement_record:
        reasons.append("no_settlement_record")
    if claim.latest_status is None or claim.latest_status not in _RESOLVED_STATUSES:
        if "contradicted" not in reasons:
            reasons.append("unsettled_status")
    if not claim.has_score_record:
        reasons.append("no_score_record")
    return tuple(reasons)


def build_handoff(
    store: MemoryStore,
    *,
    session_id: str | None = None,
    claim_id: str | None = None,
    status: str | None = None,
) -> HandoffSummary:
    """Build a HandoffSummary from the local ledger. Read-only.

    Reuses the projection stack (``project_evidence_events`` + ``fold_settled_claims``)
    rather than re-deriving anything; reads the ledger once.

    Optional read-only filters narrow the claim-centric view (claims,
    open/unresolved, next-inspection targets, settled_claim_count). They combine
    with AND. ``event_count`` stays the store-global total (each claim's own
    ``event_count`` already narrows with the filter). Filtering never mutates the
    store and invents no ownership: a session matches a claim only when one of
    the claim's own events carries that ``session_id``.
    """
    events = project_evidence_events(store)
    settled = fold_settled_claims(events)

    # claim_ids that have a claim-owned event in the requested session. Events
    # carry session_id on claim records (from metadata); this is the inferable
    # link, not a proof of ownership.
    session_claim_ids = {
        e.claim_id
        for e in events
        if session_id is not None and e.session_id == session_id and e.claim_id is not None
    }

    selected = [
        c
        for c in settled
        if (claim_id is None or c.claim_id == claim_id)
        and (status is None or c.latest_status == status)
        and (session_id is None or c.claim_id in session_claim_ids)
    ]

    claims = tuple(
        HandoffClaim(
            claim_id=c.claim_id,
            latest_status=c.latest_status,
            event_count=c.event_count,
            has_claim_record=c.has_claim_record,
            has_settlement_record=c.has_settlement_record,
            has_score_record=c.has_score_record,
            latest_exit_code=c.latest_exit_code,
        )
        for c in selected
    )

    open_items: list[HandoffOpenItem] = []
    for c in selected:
        reasons = _reasons_for(c)
        if reasons:
            open_items.append(HandoffOpenItem(claim_id=c.claim_id, reasons=reasons))

    def _top_reason(item: HandoffOpenItem) -> str:
        return min(item.reasons, key=lambda r: _REASON_PRIORITY.get(r, 99))

    targets = sorted(
        (HandoffTarget(claim_id=o.claim_id, reason=_top_reason(o)) for o in open_items),
        key=lambda t: (_REASON_PRIORITY.get(t.reason, 99), t.claim_id),
    )

    return HandoffSummary(
        schema_version=SCHEMA_VERSION,
        advisory=ADVISORY,
        filters=HandoffFilters(session_id=session_id, claim_id=claim_id, status=status),
        event_count=len(events),
        settled_claim_count=len(selected),
        claims=claims,
        open_or_unresolved=tuple(open_items),
        next_inspection_targets=tuple(targets),
    )


def handoff_for_root(
    root: str | Path,
    *,
    session_id: str | None = None,
    claim_id: str | None = None,
    status: str | None = None,
) -> HandoffSummary:
    """Convenience wrapper: build a handoff for a repo root's ``.chimera-memory``."""
    return build_handoff(
        MemoryStore.from_paths(root=root),
        session_id=session_id,
        claim_id=claim_id,
        status=status,
    )


def render_markdown(
    summary: HandoffSummary,
    *,
    store_label: str,
    generated_at: str,
) -> str:
    """Render the handoff as advisory markdown. Presentation only."""
    lines: list[str] = []
    lines.append("# Chimera Memory Handoff")
    lines.append("")
    lines.append(
        "Advisory only. This is a local evidence summary, not a correctness, "
        "safety, merge, approval, or production-readiness signal."
    )
    lines.append("")
    lines.append("## Store")
    lines.append(f"- store: {store_label}")
    lines.append(f"- generated_at: {generated_at}")
    lines.append(f"- event_count: {summary.event_count}")
    lines.append(f"- settled_claim_count: {summary.settled_claim_count}")
    _f = summary.filters
    _filter_label = (
        f"session_id={_f.session_id} claim_id={_f.claim_id} status={_f.status}"
        if (_f.session_id or _f.claim_id or _f.status)
        else "none"
    )
    lines.append(f"- filters: {_filter_label}")
    lines.append("")
    lines.append("## Claims")
    if summary.claims:
        for c in summary.claims:
            lines.append(
                f"- `{c.claim_id}` — status={c.latest_status} events={c.event_count} "
                f"claim_record={c.has_claim_record} "
                f"settlement_record={c.has_settlement_record} "
                f"score_record={c.has_score_record} "
                f"latest_exit_code={c.latest_exit_code}"
            )
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Open / unresolved evidence")
    if summary.open_or_unresolved:
        for o in summary.open_or_unresolved:
            lines.append(f"- `{o.claim_id}` — {', '.join(o.reasons)}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Next inspection targets")
    if summary.next_inspection_targets:
        for t in summary.next_inspection_targets:
            lines.append(f"- `{t.claim_id}` — {t.reason}")
    else:
        lines.append("- (none)")
    lines.append("")
    return "\n".join(lines)
