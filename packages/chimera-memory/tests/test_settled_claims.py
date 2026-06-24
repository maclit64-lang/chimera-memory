"""Stage 1B: SettledClaim projection tests.

Structured assertions only. These verify that EvidenceEvents fold into one
SettledClaim per claim_id (lifecycle re-emissions collapse), that outcomes and
scores attach by claim_id, that latest_status/ordering are deterministic, that
event lineage is preserved, and that the projection is read-only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chimera_memory.evidence_events import EvidenceEvent, EvidenceEventKind
from chimera_memory.settled_claims import (
    SCHEMA_VERSION,
    SettledClaim,
    fold_settled_claims,
    project_settled_claims,
    settled_claims_for_root,
)
from chimera_memory.storage import MemoryStore


def _ev(
    kind: EvidenceEventKind,
    *,
    event_id: str,
    claim_id: str | None = None,
    session_id: str | None = None,
    status: str | None = None,
    exit_code: int | None = None,
    timestamp: str | None = None,
    summary: str | None = None,
) -> EvidenceEvent:
    return EvidenceEvent(
        schema_version=1,
        event_id=event_id,
        event_kind=kind,
        source="test",
        record_ref="test:0",
        raw_record_type="test",
        raw_record_hash="h",
        timestamp=timestamp,
        claim_id=claim_id,
        session_id=session_id,
        evidence_id=None,
        status=status,
        exit_code=exit_code,
        summary=summary,
    )


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")


def _seed_store(root: Path) -> MemoryStore:
    mem = root / ".chimera-memory"
    _write_jsonl(mem / "claims.jsonl", [
        {"claim_id": "c1", "claim_status": "proposed", "title": "cmd will pass",
         "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
         "metadata": {"session_id": "s1"}},
        {"claim_id": "c1", "claim_status": "validated", "title": "cmd will pass",
         "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:05Z",
         "metadata": {"session_id": "s1"}},
    ])
    _write_jsonl(mem / "outcomes.jsonl", [
        {"claim_id": "c1", "event_key": "c1:k", "observed_at": "2026-01-01T00:00:05Z",
         "outcome": {"observed": True}, "metadata": {"exit_code": 0}},
    ])
    _write_jsonl(mem / "scores.jsonl", [
        {"record_id": "r1", "claim_id": "c1", "created_at": "2026-01-01T00:00:06Z",
         "settlement": {"status": "validated"}},
    ])
    _write_jsonl(mem / "sessions.jsonl", [
        {"event": "start", "session": {"session_id": "s1", "started_at": "2026-01-01T00:00:00Z",
                                       "ended_at": None, "final_status": None}},
        {"event": "end", "session": {"session_id": "s1", "started_at": "2026-01-01T00:00:00Z",
                                     "ended_at": "2026-01-01T00:00:07Z", "final_status": "passed"}},
    ])
    return MemoryStore.from_paths(root=root)


def test_lifecycle_records_fold_into_one_settled_claim() -> None:
    events = [
        _ev(EvidenceEventKind.CLAIM_OPENED, event_id="o1", claim_id="c1",
            status="proposed", timestamp="2026-01-01T00:00:00Z"),
        _ev(EvidenceEventKind.CLAIM_OPENED, event_id="o2", claim_id="c1",
            status="validated", timestamp="2026-01-01T00:00:05Z"),
    ]
    claims = fold_settled_claims(events)
    assert len(claims) == 1
    assert claims[0].claim_id == "c1"
    assert claims[0].opened_event_ids == ("o1", "o2")  # both lifecycle lines preserved
    assert claims[0].event_count == 2
    assert claims[0].has_claim_record is True


def test_outcome_and_score_attach_to_claim_id() -> None:
    events = [
        _ev(EvidenceEventKind.CLAIM_OPENED, event_id="o1", claim_id="c1", status="proposed"),
        _ev(EvidenceEventKind.CLAIM_SETTLED, event_id="s1", claim_id="c1", exit_code=0),
        _ev(EvidenceEventKind.SCORE_OBSERVED, event_id="sc1", claim_id="c1", status="validated"),
    ]
    [claim] = fold_settled_claims(events)
    assert claim.settlement_event_ids == ("s1",)
    assert claim.score_event_ids == ("sc1",)
    assert claim.has_settlement_record is True
    assert claim.has_score_record is True
    assert claim.latest_exit_code == 0


def test_latest_status_is_deterministic_by_timestamp_not_list_order() -> None:
    # The later-timestamp status wins regardless of position in the list.
    events = [
        _ev(EvidenceEventKind.CLAIM_OPENED, event_id="late", claim_id="c1",
            status="validated", timestamp="2026-01-01T00:00:09Z"),
        _ev(EvidenceEventKind.CLAIM_OPENED, event_id="early", claim_id="c1",
            status="proposed", timestamp="2026-01-01T00:00:01Z"),
    ]
    [claim] = fold_settled_claims(events)
    assert claim.latest_status == "validated"


def test_event_lineage_is_preserved_in_order() -> None:
    events = [
        _ev(EvidenceEventKind.CLAIM_OPENED, event_id="a", claim_id="c1"),
        _ev(EvidenceEventKind.CLAIM_SETTLED, event_id="b", claim_id="c1"),
        _ev(EvidenceEventKind.SCORE_OBSERVED, event_id="c", claim_id="c1"),
    ]
    [claim] = fold_settled_claims(events)
    assert claim.event_ids == ("a", "b", "c")
    assert claim.event_count == 3


def test_two_claims_keep_first_appearance_order_and_are_deterministic() -> None:
    events = [
        _ev(EvidenceEventKind.CLAIM_OPENED, event_id="x1", claim_id="cB"),
        _ev(EvidenceEventKind.CLAIM_OPENED, event_id="y1", claim_id="cA"),
        _ev(EvidenceEventKind.CLAIM_SETTLED, event_id="x2", claim_id="cB"),
    ]
    first = [c.claim_id for c in fold_settled_claims(events)]
    second = [c.claim_id for c in fold_settled_claims(events)]
    assert first == ["cB", "cA"]  # by first appearance, not sorted
    assert first == second


def test_session_events_link_by_session_id_but_stay_separate() -> None:
    events = [
        _ev(EvidenceEventKind.CLAIM_OPENED, event_id="o1", claim_id="c1", session_id="s1"),
        _ev(EvidenceEventKind.SESSION_OBSERVED, event_id="se1", session_id="s1"),
        _ev(EvidenceEventKind.SESSION_OBSERVED, event_id="se2", session_id="s1"),
        _ev(EvidenceEventKind.SESSION_OBSERVED, event_id="other", session_id="s2"),
    ]
    [claim] = fold_settled_claims(events)
    assert claim.session_event_ids == ("se1", "se2")  # only matching session, deduped/ordered
    assert claim.event_ids == ("o1",)  # sessions are NOT part of claim-owned lineage
    assert claim.event_count == 1


def test_missing_fields_do_not_crash() -> None:
    events = [_ev(EvidenceEventKind.CLAIM_OPENED, event_id="o1", claim_id="c1")]
    [claim] = fold_settled_claims(events)
    assert claim.latest_status is None
    assert claim.latest_exit_code is None
    assert claim.first_timestamp is None
    assert claim.last_timestamp is None
    assert claim.summary is None
    assert claim.session_event_ids == ()


def test_empty_store_returns_empty_projection(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    assert project_settled_claims(store) == []
    assert fold_settled_claims([]) == []


def test_projection_over_store_folds_and_is_read_only(tmp_path: Path) -> None:
    store = _seed_store(tmp_path)
    mem = tmp_path / ".chimera-memory"
    before = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    claims = project_settled_claims(store)
    after = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    assert before == after  # read-only: no ledger file changed/created
    assert len(claims) == 1
    claim = claims[0]
    assert claim.claim_id == "c1"
    assert len(claim.opened_event_ids) == 2          # lifecycle folded, lineage kept
    assert len(claim.settlement_event_ids) == 1
    assert len(claim.score_event_ids) == 1
    assert len(claim.session_event_ids) == 2          # linked via session_id s1
    assert claim.latest_status == "validated"
    assert claim.latest_exit_code == 0
    assert claim.first_timestamp == "2026-01-01T00:00:00Z"
    assert claim.last_timestamp == "2026-01-01T00:00:06Z"


def test_schema_is_additive_and_stable(tmp_path: Path) -> None:
    store = _seed_store(tmp_path)
    [claim] = project_settled_claims(store)
    assert isinstance(claim, SettledClaim)
    assert claim.schema_version == SCHEMA_VERSION == 1
    assert set(claim.to_dict()) == {
        "schema_version", "claim_id", "latest_status", "event_count",
        "opened_event_ids", "settlement_event_ids", "score_event_ids",
        "session_event_ids", "event_ids", "first_timestamp", "last_timestamp",
        "latest_exit_code", "summary", "has_claim_record",
        "has_settlement_record", "has_score_record",
    }


def test_settled_claims_for_root_matches_store_projection(tmp_path: Path) -> None:
    _seed_store(tmp_path)
    via_root = [c.to_dict() for c in settled_claims_for_root(tmp_path)]
    via_store = [c.to_dict() for c in project_settled_claims(MemoryStore.from_paths(root=tmp_path))]
    assert via_root == via_store
