"""Tests proving errata loading uses store.memory_dir, not Path.cwd()."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from chimera_memory_types.finding import EvidenceRef, EvidenceRefType

from chimera_memory.errata import add_errata
from chimera_memory.export import build_engine_events
from chimera_memory.ledger import build_dogfood_status, record_claim, settle_claim
from chimera_memory.m2b_readiness import compute_m2b_readiness
from chimera_memory.reliability import build_reliability_summary
from chimera_memory.storage import MemoryStore

_T0 = datetime(2026, 1, 1, 12, tzinfo=UTC)
_T1 = datetime(2026, 1, 1, 13, tzinfo=UTC)
_CLEAN = {
    "harness_id": "h", "attribution_confidence": "high",
    "identity_source": "cli_flag", "session_id": "sess-001",
}


def _ev() -> EvidenceRef:
    return EvidenceRef(ref_type=EvidenceRefType.EXTERNAL, ref_id="r", available_at=_T0)


def _make_contradicted(root: Path) -> str:
    """Create a CONTRADICTED claim labeled organic_real in the ledger at root."""
    extra = {**_CLEAN, "failure_origin": "organic_real", "verification_scope": "package"}
    cid = record_claim(
        title="t", summary="s", predicted=True, evidence=[_ev()],
        root=root, claim_time=_T0, agent_id="a", model_version="m",
        task_type="test", extra_metadata=extra,
    )
    settle_claim(cid, False, _T1, root=root)
    return cid


def _setup(tmp_path: Path) -> tuple[Path, str]:
    """Create ledger in tmp_path with one corrected claim. Returns (ledger_root, claim_id)."""
    cid = _make_contradicted(tmp_path)
    mem = tmp_path / ".chimera-memory"
    add_errata(mem, cid, "invocation_artifact", "shell quoting error")
    return tmp_path, cid


# ---------------------------------------------------------------------------
# reliability — non-cwd store path
# ---------------------------------------------------------------------------


def test_reliability_uses_store_memory_dir_not_cwd(tmp_path: Path, monkeypatch) -> None:
    """reliability filter uses errata from store.memory_dir even when cwd differs."""
    ledger_root, cid = _setup(tmp_path)
    store = MemoryStore.from_paths(root=ledger_root)

    # Change cwd to a different directory (no .chimera-memory there)
    other_dir = tmp_path / "other_cwd"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)

    # errata should still apply because reliability uses store.memory_dir
    summary = build_reliability_summary(store, filters={"failure_origin": "organic_real"})
    assert summary.clean_claims == 0, (
        "corrected invocation_artifact must be excluded from organic_real filter"
    )


def test_reliability_invocation_artifact_filter_from_non_cwd(tmp_path: Path, monkeypatch) -> None:
    ledger_root, cid = _setup(tmp_path)
    store = MemoryStore.from_paths(root=ledger_root)
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)

    summary = build_reliability_summary(store, filters={"failure_origin": "invocation_artifact"})
    assert summary.clean_claims == 1, "corrected claim included under invocation_artifact filter"


# ---------------------------------------------------------------------------
# m2b-readiness — non-cwd store path
# ---------------------------------------------------------------------------


def test_m2b_readiness_uses_store_memory_dir_not_cwd(tmp_path: Path, monkeypatch) -> None:
    ledger_root, cid = _setup(tmp_path)
    store = MemoryStore.from_paths(root=ledger_root)
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)

    report = compute_m2b_readiness(store)
    # organic_real_failed should be 0 (the only failure was corrected to invocation_artifact)
    assert report.dq_cohort_summary.get("organic_real_failed", 0) == 0
    assert report.notes.get("errata_applied", 0) >= 1


# ---------------------------------------------------------------------------
# status _dq_summary — non-cwd store path
# ---------------------------------------------------------------------------


def test_status_dq_summary_uses_store_memory_dir_not_cwd(tmp_path: Path, monkeypatch) -> None:
    ledger_root, cid = _setup(tmp_path)
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)

    status = build_dogfood_status(root=ledger_root)
    dq = status.get("data_quality", {})
    # effective_failure_origin_counts should show invocation_artifact (corrected)
    eff = dq.get("effective_failure_origin_counts", {})
    assert eff.get("invocation_artifact", 0) >= 1
    assert eff.get("organic_real", 0) == 0
    assert dq.get("errata_applied_count", 0) >= 1


# ---------------------------------------------------------------------------
# export — non-cwd store path
# ---------------------------------------------------------------------------


def test_export_effective_dq_uses_store_memory_dir_not_cwd(tmp_path: Path, monkeypatch) -> None:
    ledger_root, cid = _setup(tmp_path)
    store = MemoryStore.from_paths(root=ledger_root)
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)

    events = build_engine_events(store)
    assert events
    edq = events[0].get("effective_data_quality", {})
    assert edq.get("errata_applied") is True
    assert edq.get("failure_origin") == "invocation_artifact"


# ---------------------------------------------------------------------------
# Legacy/no-errata unchanged behavior
# ---------------------------------------------------------------------------


def test_no_errata_dq_summary_unchanged(tmp_path: Path) -> None:
    """Without errata, _dq_summary returns raw counts with no effective_ keys."""
    extra = {**_CLEAN, "failure_origin": "organic_real", "verification_scope": "package"}
    cid = record_claim(
        title="t", summary="s", predicted=True, evidence=[_ev()],
        root=tmp_path, claim_time=_T0, agent_id="a", model_version="m",
        task_type="test", extra_metadata=extra,
    )
    settle_claim(cid, True, _T1, root=tmp_path)
    status = build_dogfood_status(root=tmp_path)
    dq = status.get("data_quality", {})
    # No errata applied
    assert dq.get("errata_applied_count", 0) == 0
    assert "effective_failure_origin_counts" not in dq
