"""Stage 1: EvidenceEvent projection foundation tests.

Structured assertions only — no prose snapshots. These verify the projection is
additive, deterministic, and read-only over the existing JSONL ledger, and that
projected record hashes line up with the canonical integrity convention.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chimera_memory.evidence_events import (
    SCHEMA_VERSION,
    EvidenceEvent,
    EvidenceEventKind,
    evidence_events_for_root,
    project_evidence_events,
)
from chimera_memory.storage import MemoryStore
from chimera_memory_types.knowledge import Claim, ClaimType, EvidenceBundle


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")


def _seed_legacy_store(root: Path) -> MemoryStore:
    """Write realistic raw records mirroring the canonical shapes (no models)."""
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
        {"claim_id": "c1", "event_key": "c1:2026-01-01T00:00:05Z:true",
         "observed_at": "2026-01-01T00:00:05Z", "outcome": {"observed": True},
         "metadata": {"exit_code": 0}},
    ])
    _write_jsonl(mem / "scores.jsonl", [
        {"record_id": "r1", "claim_id": "c1", "created_at": "2026-01-01T00:00:05Z",
         "settlement": {"status": "validated", "proper_score": 0.0}},
    ])
    _write_jsonl(mem / "sessions.jsonl", [
        {"event": "start", "session": {
            "session_id": "s1", "started_at": "2026-01-01T00:00:00Z",
            "ended_at": None, "final_status": None, "task_label": "demo"}},
        {"event": "end", "session": {
            "session_id": "s1", "started_at": "2026-01-01T00:00:00Z",
            "ended_at": "2026-01-01T00:00:06Z", "final_status": "passed",
            "task_label": "demo"}},
    ])
    return MemoryStore.from_paths(root=root)


def test_legacy_claim_record_projects_to_claim_opened(tmp_path: Path) -> None:
    store = _seed_legacy_store(tmp_path)
    claim_events = [e for e in project_evidence_events(store) if e.source == "claims.jsonl"]
    assert [e.event_kind for e in claim_events] == [
        EvidenceEventKind.CLAIM_OPENED, EvidenceEventKind.CLAIM_OPENED]
    assert claim_events[0].claim_id == "c1"
    assert claim_events[0].status == "proposed"
    assert claim_events[1].status == "validated"
    assert claim_events[0].session_id == "s1"
    assert claim_events[0].raw_record_type == "claim"
    assert claim_events[0].record_ref == "claims.jsonl:1"
    assert claim_events[0].summary == "cmd will pass"


def test_legacy_outcome_record_projects_to_claim_settled(tmp_path: Path) -> None:
    store = _seed_legacy_store(tmp_path)
    outcomes = [e for e in project_evidence_events(store) if e.source == "outcomes.jsonl"]
    assert len(outcomes) == 1
    assert outcomes[0].event_kind == EvidenceEventKind.CLAIM_SETTLED
    assert outcomes[0].claim_id == "c1"
    assert outcomes[0].exit_code == 0
    assert outcomes[0].evidence_id == "c1:2026-01-01T00:00:05Z:true"


def test_legacy_score_and_session_records_project(tmp_path: Path) -> None:
    store = _seed_legacy_store(tmp_path)
    events = project_evidence_events(store)
    scores = [e for e in events if e.source == "scores.jsonl"]
    sessions = [e for e in events if e.source == "sessions.jsonl"]
    assert len(scores) == 1
    assert scores[0].event_kind == EvidenceEventKind.SCORE_OBSERVED
    assert scores[0].status == "validated"
    assert scores[0].evidence_id == "r1"
    assert [e.event_kind for e in sessions] == [
        EvidenceEventKind.SESSION_OBSERVED, EvidenceEventKind.SESSION_OBSERVED]
    assert sessions[0].session_id == "s1"
    assert sessions[0].status is None  # start event has no final_status
    assert sessions[1].status == "passed"


def test_event_ids_are_deterministic_and_unique(tmp_path: Path) -> None:
    store = _seed_legacy_store(tmp_path)
    first = [e.event_id for e in project_evidence_events(store)]
    second = [e.event_id for e in project_evidence_events(store)]
    assert first == second  # projecting twice is stable
    assert len(first) == len(set(first))  # unique across the seeded records
    assert all(e.startswith("ev_") for e in first)


def test_missing_fields_become_none_not_invented(tmp_path: Path) -> None:
    _write_jsonl(tmp_path / ".chimera-memory" / "claims.jsonl", [{"claim_id": "c9"}])
    store = MemoryStore.from_paths(root=tmp_path)
    events = project_evidence_events(store)
    assert len(events) == 1
    event = events[0]
    assert event.claim_id == "c9"
    assert event.status is None
    assert event.summary is None
    assert event.timestamp is None
    assert event.session_id is None
    assert event.exit_code is None


def test_projection_is_read_only(tmp_path: Path) -> None:
    store = _seed_legacy_store(tmp_path)
    mem = tmp_path / ".chimera-memory"
    before = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    project_evidence_events(store)
    after = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    assert before == after  # no ledger file created, deleted, or modified


def test_raw_record_hash_matches_integrity_convention(tmp_path: Path) -> None:
    # Append a real claim via the canonical write path, then assert the projected
    # event's raw_record_hash equals the integrity-chain record_hash for that line.
    store = MemoryStore.from_paths(root=tmp_path)
    claim = Claim(
        claim_type=ClaimType.BACKTESTED_PREDICTION,
        title="t",
        summary="s",
        evidence=EvidenceBundle(),
        world_type="coding-agent",
    )
    store.append_claim(claim)
    claim_events = [e for e in project_evidence_events(store) if e.source == "claims.jsonl"]
    assert len(claim_events) == 1
    integrity = store.read_jsonl("integrity.jsonl")
    record_hashes = {e["line_number"]: e["record_hash"] for e in integrity}
    assert claim_events[0].raw_record_hash == record_hashes[1]
    assert claim_events[0].claim_id == claim.claim_id


def test_schema_is_additive_and_stable(tmp_path: Path) -> None:
    store = _seed_legacy_store(tmp_path)
    events = project_evidence_events(store)
    event = events[0]
    assert isinstance(event, EvidenceEvent)
    assert event.schema_version == SCHEMA_VERSION == 1
    assert set(event.to_dict()) == {
        "schema_version", "event_id", "event_kind", "source", "record_ref",
        "raw_record_type", "raw_record_hash", "timestamp", "claim_id",
        "session_id", "evidence_id", "status", "exit_code", "summary",
    }


def test_empty_store_projects_no_events(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    assert project_evidence_events(store) == []


def test_evidence_events_for_root_matches_store_projection(tmp_path: Path) -> None:
    _seed_legacy_store(tmp_path)
    via_root = [e.event_id for e in evidence_events_for_root(tmp_path)]
    via_store = [
        e.event_id
        for e in project_evidence_events(MemoryStore.from_paths(root=tmp_path))
    ]
    assert via_root == via_store
