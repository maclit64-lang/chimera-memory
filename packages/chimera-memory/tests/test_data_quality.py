"""Tests for data-quality metadata foundations."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from chimera_memory_types.finding import EvidenceRef, EvidenceRefType

from chimera_memory.data_quality import (
    K_FAILURE_ORIGIN,
    K_REPAIR_LOOP_ID,
    K_REPAIR_OF_CLAIM_ID,
    K_REPAIR_PHASE,
    K_VERIFICATION_SCOPE,
    FailureOrigin,
    RepairPhase,
    VerificationScope,
    dq_summary,
    validate_failure_origin,
    validate_repair_phase,
    validate_verification_scope,
)
from chimera_memory.export import build_engine_events
from chimera_memory.ledger import record_claim, settle_claim
from chimera_memory.storage import MemoryStore

# ---------------------------------------------------------------------------
# Enum validation
# ---------------------------------------------------------------------------


def test_validate_failure_origin_accepts_all_values() -> None:
    for v in FailureOrigin:
        assert validate_failure_origin(v.value) == v.value


def test_validate_failure_origin_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="Invalid --failure-origin"):
        validate_failure_origin("not_a_real_origin")


def test_validate_verification_scope_accepts_all_values() -> None:
    for v in VerificationScope:
        assert validate_verification_scope(v.value) == v.value


def test_validate_verification_scope_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="Invalid --verification-scope"):
        validate_verification_scope("super_scope")


def test_validate_repair_phase_accepts_all_values() -> None:
    for v in RepairPhase:
        assert validate_repair_phase(v.value) == v.value


def test_validate_repair_phase_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="Invalid --repair-phase"):
        validate_repair_phase("invalid_phase")


# ---------------------------------------------------------------------------
# Storage: DQ fields in claims.jsonl
# ---------------------------------------------------------------------------


def _ev() -> EvidenceRef:
    return EvidenceRef(
        ref_type=EvidenceRefType.EXTERNAL, ref_id="r",
        available_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _record_with_dq(root: Path, **dq_kwargs) -> str:
    t0 = datetime(2026, 1, 1, 12, tzinfo=UTC)
    extra = {K_FAILURE_ORIGIN: "organic_real", K_VERIFICATION_SCOPE: "package"}
    extra.update(dq_kwargs)
    return record_claim(
        title="dq test", summary="s", predicted=True,
        evidence=[_ev()], root=root, claim_time=t0,
        agent_id="a", task_type="test",
        extra_metadata=extra,
    )


def test_failure_origin_stored_in_claim(tmp_path: Path) -> None:
    cid = _record_with_dq(tmp_path)
    store = MemoryStore(tmp_path / ".chimera-memory")
    claim = store.latest_claim(cid)
    assert claim is not None
    assert claim.metadata.get(K_FAILURE_ORIGIN) == "organic_real"


def test_verification_scope_stored_in_claim(tmp_path: Path) -> None:
    cid = _record_with_dq(tmp_path)
    store = MemoryStore(tmp_path / ".chimera-memory")
    claim = store.latest_claim(cid)
    assert claim.metadata.get(K_VERIFICATION_SCOPE) == "package"


def test_scope_paths_stored_as_list(tmp_path: Path) -> None:
    cid = _record_with_dq(tmp_path, scope_paths=["packages/chimera-memory"])
    store = MemoryStore(tmp_path / ".chimera-memory")
    claim = store.latest_claim(cid)
    assert claim.metadata.get("scope_paths") == ["packages/chimera-memory"]


def test_repair_loop_metadata_stored(tmp_path: Path) -> None:
    cid = _record_with_dq(
        tmp_path,
        repair_loop_id="loop-1",
        repair_phase="baseline",
        repair_of_claim_id="abc",
    )
    store = MemoryStore(tmp_path / ".chimera-memory")
    claim = store.latest_claim(cid)
    assert claim.metadata.get(K_REPAIR_LOOP_ID) == "loop-1"
    assert claim.metadata.get(K_REPAIR_PHASE) == "baseline"
    assert claim.metadata.get(K_REPAIR_OF_CLAIM_ID) == "abc"


def test_legacy_claims_without_dq_fields_read_as_unknown(tmp_path: Path) -> None:
    """Legacy claims without DQ metadata are valid; dq_summary counts them as unknown."""
    t0 = datetime(2026, 1, 1, 12, tzinfo=UTC)
    record_claim(
        title="legacy", summary="s", predicted=True,
        evidence=[_ev()], root=tmp_path, claim_time=t0,
        agent_id="a", task_type="test",
    )
    store = MemoryStore(tmp_path / ".chimera-memory")
    claims = store.read_claims()
    metadatas = [c.metadata or {} for c in claims]
    summary = dq_summary(metadatas)
    assert summary["failure_origin_counts"].get("unknown", 0) >= 1


# ---------------------------------------------------------------------------
# Export includes data_quality fields
# ---------------------------------------------------------------------------


def _settled_claim(root: Path) -> None:
    t0 = datetime(2026, 1, 1, 12, tzinfo=UTC)
    cid = _record_with_dq(root, repair_loop_id="rl1", repair_phase="baseline")
    settle_claim(cid, True, t0.replace(hour=13), root=root)


def test_export_includes_data_quality_fields(tmp_path: Path) -> None:
    _settled_claim(tmp_path)
    store = MemoryStore(tmp_path / ".chimera-memory")
    events = build_engine_events(store)
    assert events, "expected at least one export event"
    dq = events[0].get("data_quality", {})
    assert dq.get("failure_origin") == "organic_real"
    assert dq.get("verification_scope") == "package"
    assert dq.get("repair_loop_id") == "rl1"
    assert dq.get("repair_phase") == "baseline"


def test_export_data_quality_null_for_legacy_claims(tmp_path: Path) -> None:
    """Legacy claims export with data_quality fields all set to None."""
    t0 = datetime(2026, 1, 1, 12, tzinfo=UTC)
    cid = record_claim(
        title="t", summary="s", predicted=True, evidence=[_ev()],
        root=tmp_path, claim_time=t0, agent_id="a", task_type="test",
    )
    settle_claim(cid, True, t0.replace(hour=13), root=tmp_path)
    store = MemoryStore(tmp_path / ".chimera-memory")
    events = build_engine_events(store)
    dq = events[0].get("data_quality", {})
    assert dq.get("failure_origin") is None
    assert dq.get("verification_scope") is None


# ---------------------------------------------------------------------------
# dq_summary helper
# ---------------------------------------------------------------------------


def test_dq_summary_counts() -> None:
    metadatas = [
        {K_FAILURE_ORIGIN: "organic_real", K_VERIFICATION_SCOPE: "package", K_REPAIR_LOOP_ID: "l1"},
        {K_FAILURE_ORIGIN: "organic_real", K_VERIFICATION_SCOPE: "workspace"},
        {},  # legacy → unknown
    ]
    summary = dq_summary(metadatas)
    assert summary["failure_origin_counts"]["organic_real"] == 2
    assert summary["failure_origin_counts"]["unknown"] == 1
    assert summary["verification_scope_counts"]["package"] == 1
    assert summary["repair_loop_ids"] == ["l1"]
