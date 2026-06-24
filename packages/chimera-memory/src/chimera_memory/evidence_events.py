"""EvidenceEvent foundation (Stage 1): a read-only projection over the existing
canonical append-only JSONL ledger.

Doctrine (future direction, *not* built here): an ``EvidenceEvent`` is the
canonical atom, and ``SettledClaim`` / receipts / proof-debt / relapse / handoff
are projections over events. This module is the first, additive step only: it
introduces no new store and changes no existing record. It reads the current
``claims`` / ``outcomes`` / ``scores`` / ``sessions`` JSONL files and wraps each
record as an ``EvidenceEvent``.

Guarantees:
- Read-only: projection never writes, mutates, or creates ledger files.
- Additive: no existing record shape, file, or public behavior changes.
- Deterministic IDs: a given record always projects to the same ``event_id``,
  so projecting the same store twice yields identical events.

This is an internal architecture foundation, not a product surface. It makes no
correctness, safety, or merge-readiness claim about any code; it only wraps
records that already exist locally.

Projection mapping (literal, one event per stored record):
    claims.jsonl   record -> claim_opened
    outcomes.jsonl record -> claim_settled
    scores.jsonl   record -> score_observed
    sessions.jsonl event  -> session_observed

The ``command_observed`` and ``receipt_observed`` kinds are part of the event
vocabulary but have no dedicated JSONL source today (commands live inside
outcome/claim metadata; receipts are generated artifacts), so they are reserved
and not produced by this projection.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from chimera_memory.integrity import hash_line
from chimera_memory.storage import MemoryStore

SCHEMA_VERSION = 1


class EvidenceEventKind(StrEnum):
    CLAIM_OPENED = "claim_opened"
    CLAIM_SETTLED = "claim_settled"
    COMMAND_OBSERVED = "command_observed"
    SCORE_OBSERVED = "score_observed"
    SESSION_OBSERVED = "session_observed"
    RECEIPT_OBSERVED = "receipt_observed"


@dataclass(frozen=True)
class EvidenceEvent:
    """An additive, read-only wrapper around one existing ledger record."""

    schema_version: int
    event_id: str
    event_kind: EvidenceEventKind
    source: str            # source JSONL filename, e.g. "claims.jsonl"
    record_ref: str        # "{source}:{line_number}" (1-based)
    raw_record_type: str   # "claim" | "outcome" | "score" | "session_event"
    raw_record_hash: str   # sha256 of the canonical record line (integrity convention)
    timestamp: str | None = None
    claim_id: str | None = None
    session_id: str | None = None
    evidence_id: str | None = None   # natural sub-id when present (event_key / record_id)
    status: str | None = None
    exit_code: int | None = None
    summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_kind": str(self.event_kind),
            "source": self.source,
            "record_ref": self.record_ref,
            "raw_record_type": self.raw_record_type,
            "raw_record_hash": self.raw_record_hash,
            "timestamp": self.timestamp,
            "claim_id": self.claim_id,
            "session_id": self.session_id,
            "evidence_id": self.evidence_id,
            "status": self.status,
            "exit_code": self.exit_code,
            "summary": self.summary,
        }


def _record_hash(record: dict[str, Any]) -> str:
    # Match the integrity-chain convention: sha256 of json.dumps(payload, sort_keys=True).
    return hash_line(json.dumps(record, sort_keys=True))


def _event_id(
    *,
    event_kind: EvidenceEventKind,
    source: str,
    claim_id: str | None,
    session_id: str | None,
    timestamp: str | None,
    raw_record_hash: str,
) -> str:
    """Deterministic, content-addressed id over record type, ids, time, and hash.

    No randomness: the same stored record always yields the same event_id.
    """
    key = "\x1f".join(
        [
            str(SCHEMA_VERSION),
            str(event_kind),
            source,
            claim_id or "",
            session_id or "",
            timestamp or "",
            raw_record_hash,
        ]
    )
    return "ev_" + hashlib.sha256(key.encode("utf-8")).hexdigest()


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _as_int(value: Any) -> int | None:
    # bool is an int subclass; exclude it so exit_code stays a real integer.
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _build(
    *,
    event_kind: EvidenceEventKind,
    source: str,
    line_number: int,
    raw_record_type: str,
    record: dict[str, Any],
    timestamp: str | None,
    claim_id: str | None,
    session_id: str | None,
    evidence_id: str | None,
    status: str | None,
    exit_code: int | None,
    summary: str | None,
) -> EvidenceEvent:
    raw_record_hash = _record_hash(record)
    return EvidenceEvent(
        schema_version=SCHEMA_VERSION,
        event_id=_event_id(
            event_kind=event_kind,
            source=source,
            claim_id=claim_id,
            session_id=session_id,
            timestamp=timestamp,
            raw_record_hash=raw_record_hash,
        ),
        event_kind=event_kind,
        source=source,
        record_ref=f"{source}:{line_number}",
        raw_record_type=raw_record_type,
        raw_record_hash=raw_record_hash,
        timestamp=timestamp,
        claim_id=claim_id,
        session_id=session_id,
        evidence_id=evidence_id,
        status=status,
        exit_code=exit_code,
        summary=summary,
    )


def project_claim(record: dict[str, Any], line_number: int) -> EvidenceEvent:
    metadata = _as_dict(record.get("metadata"))
    return _build(
        event_kind=EvidenceEventKind.CLAIM_OPENED,
        source="claims.jsonl",
        line_number=line_number,
        raw_record_type="claim",
        record=record,
        timestamp=_as_str(record.get("updated_at")) or _as_str(record.get("created_at")),
        claim_id=_as_str(record.get("claim_id")),
        session_id=_as_str(metadata.get("session_id")),
        evidence_id=None,
        status=_as_str(record.get("claim_status")),
        exit_code=None,
        summary=_as_str(record.get("title")) or _as_str(record.get("summary")),
    )


def project_outcome(record: dict[str, Any], line_number: int) -> EvidenceEvent:
    metadata = _as_dict(record.get("metadata"))
    return _build(
        event_kind=EvidenceEventKind.CLAIM_SETTLED,
        source="outcomes.jsonl",
        line_number=line_number,
        raw_record_type="outcome",
        record=record,
        timestamp=_as_str(record.get("observed_at")),
        claim_id=_as_str(record.get("claim_id")),
        session_id=None,
        evidence_id=_as_str(record.get("event_key")),
        status=None,
        exit_code=_as_int(metadata.get("exit_code")),
        summary=None,
    )


def project_score(record: dict[str, Any], line_number: int) -> EvidenceEvent:
    settlement = _as_dict(record.get("settlement"))
    return _build(
        event_kind=EvidenceEventKind.SCORE_OBSERVED,
        source="scores.jsonl",
        line_number=line_number,
        raw_record_type="score",
        record=record,
        timestamp=_as_str(record.get("created_at")),
        claim_id=_as_str(record.get("claim_id")),
        session_id=None,
        evidence_id=_as_str(record.get("record_id")),
        status=_as_str(settlement.get("status")),
        exit_code=None,
        summary=None,
    )


def project_session(record: dict[str, Any], line_number: int) -> EvidenceEvent:
    session = _as_dict(record.get("session"))
    return _build(
        event_kind=EvidenceEventKind.SESSION_OBSERVED,
        source="sessions.jsonl",
        line_number=line_number,
        raw_record_type="session_event",
        record=record,
        timestamp=_as_str(session.get("ended_at")) or _as_str(session.get("started_at")),
        claim_id=None,
        session_id=_as_str(session.get("session_id")),
        evidence_id=None,
        status=_as_str(session.get("final_status")),
        exit_code=None,
        summary=_as_str(session.get("task_label")),
    )


_Projector = Callable[[dict[str, Any], int], EvidenceEvent]
_PROJECTORS: list[tuple[str, _Projector]] = [
    ("claims.jsonl", project_claim),
    ("outcomes.jsonl", project_outcome),
    ("scores.jsonl", project_score),
    ("sessions.jsonl", project_session),
]


def project_evidence_events(store: MemoryStore) -> list[EvidenceEvent]:
    """Read-only projection of the existing JSONL ledger into EvidenceEvents.

    Records are read in file order (claims, outcomes, scores, sessions), each in
    append (line) order. No file is written, created, or modified.
    """
    events: list[EvidenceEvent] = []
    for name, projector in _PROJECTORS:
        for line_number, record in enumerate(store.read_jsonl(name), start=1):
            if isinstance(record, dict):
                events.append(projector(record, line_number))
    return events


def evidence_events_for_root(root: str | Path) -> list[EvidenceEvent]:
    """Convenience wrapper: project events for a repo root's ``.chimera-memory``."""
    return project_evidence_events(MemoryStore.from_paths(root=root))
