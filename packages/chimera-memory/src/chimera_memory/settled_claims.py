"""SettledClaim projection (Stage 1B): the first projection over EvidenceEvents.

Stage 1 produced one ``EvidenceEvent`` per stored ledger record. This module
folds those events into a claim-level view: all events sharing a ``claim_id``
collapse into a single ``SettledClaim``. In particular, the lifecycle
re-emissions of ``claims.jsonl`` (the same ``claim_id`` appended again as its
status advances proposed -> validated -> ...) fold into one projection rather
than counting as multiple claims.

Doctrine: ``EvidenceEvent`` is the canonical atom; ``SettledClaim`` is the first
projection over those atoms.

Guarantees (inherited from the event layer):
- Read-only: this reads events (which read the ledger) and never writes.
- Additive: no existing record, file, schema, or public behavior changes.
- Deterministic: same store -> identical SettledClaims, including ordering.

This makes no correctness, safety, or merge-readiness claim about any code. A
``latest_status`` of "validated" means a claim record/score said so — it is an
evidence-status fold, not a verdict.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chimera_memory.evidence_events import (
    EvidenceEvent,
    EvidenceEventKind,
    project_evidence_events,
)
from chimera_memory.storage import MemoryStore

SCHEMA_VERSION = 1

# Event kinds that carry a claim_id and therefore belong to a claim's lineage.
_CLAIM_OWNED_KINDS = (
    EvidenceEventKind.CLAIM_OPENED,
    EvidenceEventKind.CLAIM_SETTLED,
    EvidenceEventKind.SCORE_OBSERVED,
)


@dataclass(frozen=True)
class SettledClaim:
    """A claim-level fold of every EvidenceEvent sharing one ``claim_id``."""

    schema_version: int
    claim_id: str
    latest_status: str | None
    event_count: int
    opened_event_ids: tuple[str, ...]
    settlement_event_ids: tuple[str, ...]
    score_event_ids: tuple[str, ...]
    session_event_ids: tuple[str, ...]
    event_ids: tuple[str, ...]
    first_timestamp: str | None
    last_timestamp: str | None
    latest_exit_code: int | None
    summary: str | None
    has_claim_record: bool
    has_settlement_record: bool
    has_score_record: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "claim_id": self.claim_id,
            "latest_status": self.latest_status,
            "event_count": self.event_count,
            "opened_event_ids": list(self.opened_event_ids),
            "settlement_event_ids": list(self.settlement_event_ids),
            "score_event_ids": list(self.score_event_ids),
            "session_event_ids": list(self.session_event_ids),
            "event_ids": list(self.event_ids),
            "first_timestamp": self.first_timestamp,
            "last_timestamp": self.last_timestamp,
            "latest_exit_code": self.latest_exit_code,
            "summary": self.summary,
            "has_claim_record": self.has_claim_record,
            "has_settlement_record": self.has_settlement_record,
            "has_score_record": self.has_score_record,
        }


# An (order_index, event) pair; order_index is the event's position in the
# projection list and is the deterministic tiebreak for "latest".
_Indexed = tuple[int, EvidenceEvent]


def _latest(pairs: list[_Indexed]) -> EvidenceEvent | None:
    """The event with the greatest (timestamp, order_index). Deterministic."""
    if not pairs:
        return None
    return max(pairs, key=lambda p: (p[1].timestamp or "", p[0]))[1]


def _ids(pairs: list[_Indexed]) -> tuple[str, ...]:
    return tuple(event.event_id for _, event in pairs)


def _fold_one(claim_id: str, owned: list[_Indexed], sessions: list[_Indexed]) -> SettledClaim:
    opened = [p for p in owned if p[1].event_kind == EvidenceEventKind.CLAIM_OPENED]
    settled = [p for p in owned if p[1].event_kind == EvidenceEventKind.CLAIM_SETTLED]
    scores = [p for p in owned if p[1].event_kind == EvidenceEventKind.SCORE_OBSERVED]

    timestamps = sorted(p[1].timestamp for p in owned if p[1].timestamp)
    latest_status_event = _latest([p for p in owned if p[1].status is not None])
    latest_exit_event = _latest([p for p in owned if p[1].exit_code is not None])
    latest_opened = _latest([p for p in opened if p[1].summary is not None])

    return SettledClaim(
        schema_version=SCHEMA_VERSION,
        claim_id=claim_id,
        latest_status=latest_status_event.status if latest_status_event else None,
        event_count=len(owned),
        opened_event_ids=_ids(opened),
        settlement_event_ids=_ids(settled),
        score_event_ids=_ids(scores),
        session_event_ids=_ids(sorted(sessions, key=lambda p: p[0])),
        event_ids=_ids(owned),
        first_timestamp=timestamps[0] if timestamps else None,
        last_timestamp=timestamps[-1] if timestamps else None,
        latest_exit_code=latest_exit_event.exit_code if latest_exit_event else None,
        summary=latest_opened.summary if latest_opened else None,
        has_claim_record=bool(opened),
        has_settlement_record=bool(settled),
        has_score_record=bool(scores),
    )


def fold_settled_claims(events: list[EvidenceEvent]) -> list[SettledClaim]:
    """Fold EvidenceEvents into one SettledClaim per ``claim_id``.

    Claims appear in the order their first event is seen. Session events (which
    carry no ``claim_id``) are attached to a claim when their ``session_id``
    matches one seen on that claim's events — an inferable link, kept separate
    from the claim-owned ``event_ids`` lineage.
    """
    indexed: list[_Indexed] = list(enumerate(events))

    # Map session_id -> its session_observed events (for inferable linkage).
    sessions_by_sid: dict[str, list[_Indexed]] = {}
    for idx, event in indexed:
        if event.event_kind == EvidenceEventKind.SESSION_OBSERVED and event.session_id:
            sessions_by_sid.setdefault(event.session_id, []).append((idx, event))

    # Group claim-owned events by claim_id, preserving first-appearance order.
    owned_by_claim: dict[str, list[_Indexed]] = {}
    claim_order: list[str] = []
    for idx, event in indexed:
        if event.event_kind not in _CLAIM_OWNED_KINDS or not event.claim_id:
            continue
        if event.claim_id not in owned_by_claim:
            owned_by_claim[event.claim_id] = []
            claim_order.append(event.claim_id)
        owned_by_claim[event.claim_id].append((idx, event))

    settled: list[SettledClaim] = []
    for claim_id in claim_order:
        owned = owned_by_claim[claim_id]
        session_ids = sorted({p[1].session_id for p in owned if p[1].session_id})
        linked: list[_Indexed] = []
        seen: set[str] = set()
        for sid in session_ids:
            for pair in sessions_by_sid.get(sid, []):
                if pair[1].event_id not in seen:
                    seen.add(pair[1].event_id)
                    linked.append(pair)
        settled.append(_fold_one(claim_id, owned, linked))
    return settled


def project_settled_claims(store: MemoryStore) -> list[SettledClaim]:
    """Read-only projection of the ledger into claim-level SettledClaims."""
    return fold_settled_claims(project_evidence_events(store))


def settled_claims_for_root(root: str | Path) -> list[SettledClaim]:
    """Convenience wrapper: project SettledClaims for a repo root."""
    return project_settled_claims(MemoryStore.from_paths(root=root))
