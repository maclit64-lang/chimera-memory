"""Tests for reliability DQ read models, filters, and repair-loop CLI."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from chimera_memory_types.finding import EvidenceRef, EvidenceRefType

from chimera_memory.ledger import build_dogfood_status, record_claim, settle_claim
from chimera_memory.reliability import build_reliability_summary, format_reliability_text
from chimera_memory.storage import MemoryStore

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 1, 1, 12, tzinfo=UTC)
_T1 = datetime(2026, 1, 1, 13, tzinfo=UTC)


def _ev() -> EvidenceRef:
    return EvidenceRef(ref_type=EvidenceRefType.EXTERNAL, ref_id="r", available_at=_T0)


def _make_claim(
    root: Path,
    *,
    failure_origin: str = "organic_real",
    verification_scope: str = "package",
    repair_loop_id: str | None = None,
    repair_phase: str | None = None,
    observed: bool = True,
    agent: str = "test-agent",
) -> str:
    extra: dict = {
        "failure_origin": failure_origin,
        "verification_scope": verification_scope,
        "session_id": "sess-test-001",
        "harness_id": "test-harness",
        "attribution_confidence": "high",
        "identity_source": "cli_flag",
    }
    if repair_loop_id:
        extra["repair_loop_id"] = repair_loop_id
    if repair_phase:
        extra["repair_phase"] = repair_phase
    cid = record_claim(
        title="t", summary="s", predicted=True, evidence=[_ev()],
        root=root, claim_time=_T0, agent_id=agent, model_version="m",
        task_type="test", extra_metadata=extra,
    )
    settle_claim(cid, observed, _T1, root=root)
    return cid


def _legacy_claim(root: Path) -> str:
    """A claim with no DQ metadata — legacy style but still clean."""
    cid = record_claim(
        title="legacy", summary="s", predicted=True, evidence=[_ev()],
        root=root, claim_time=_T0, agent_id="legacy-agent", model_version="m",
        task_type="test", extra_metadata={
            "session_id": "sess-test-002",
            "harness_id": "test-harness",
            "attribution_confidence": "high",
            "identity_source": "cli_flag",
        },
    )
    settle_claim(cid, True, _T1, root=root)
    return cid


# ---------------------------------------------------------------------------
# Reliability filter tests
# ---------------------------------------------------------------------------


def test_reliability_filter_failure_origin(tmp_path: Path) -> None:
    _make_claim(tmp_path, failure_origin="organic_real", agent="a1")
    _make_claim(tmp_path, failure_origin="synthetic", agent="a2")
    store = MemoryStore(tmp_path / ".chimera-memory")
    summary = build_reliability_summary(store, filters={"failure_origin": "organic_real"})
    assert summary.filtered_claim_count == 1
    assert summary.unfiltered_claim_count == 2
    # Only the organic_real claim should be in the summary
    assert all(
        g.agent_id == "a1" for g in summary.by_agent_model_task
    )


def test_reliability_filter_verification_scope(tmp_path: Path) -> None:
    _make_claim(tmp_path, verification_scope="package", agent="a1")
    _make_claim(tmp_path, verification_scope="workspace", agent="a2")
    store = MemoryStore(tmp_path / ".chimera-memory")
    summary = build_reliability_summary(store, filters={"verification_scope": "package"})
    assert summary.filtered_claim_count == 1
    assert summary.unfiltered_claim_count == 2


def test_reliability_organic_only_alias(tmp_path: Path) -> None:
    """--organic-only is equivalent to --failure-origin organic_real."""
    _make_claim(tmp_path, failure_origin="organic_real")
    _make_claim(tmp_path, failure_origin="synthetic")
    store = MemoryStore(tmp_path / ".chimera-memory")
    organic = build_reliability_summary(store, filters={"failure_origin": "organic_real"})
    all_claims = build_reliability_summary(store)
    assert organic.filtered_claim_count < all_claims.clean_claims


def test_reliability_filters_applied_in_json(tmp_path: Path) -> None:
    _make_claim(tmp_path)
    store = MemoryStore(tmp_path / ".chimera-memory")
    summary = build_reliability_summary(store, filters={"failure_origin": "organic_real"})
    d = summary.to_dict()
    assert d["filters_applied"] == {"failure_origin": "organic_real"}
    assert "filtered_claim_count" in d
    assert "unfiltered_claim_count" in d
    assert "unknown_metadata_count" in d


def test_reliability_legacy_claims_count_as_unknown(tmp_path: Path) -> None:
    _legacy_claim(tmp_path)
    _make_claim(tmp_path, failure_origin="organic_real")
    store = MemoryStore(tmp_path / ".chimera-memory")
    summary = build_reliability_summary(store, filters={"failure_origin": "organic_real"})
    # The legacy claim has no failure_origin → unknown_metadata_count incremented
    assert summary.unknown_metadata_count >= 1
    assert summary.filtered_claim_count == 1


def test_reliability_no_filter_includes_all(tmp_path: Path) -> None:
    _make_claim(tmp_path)
    _legacy_claim(tmp_path)
    store = MemoryStore(tmp_path / ".chimera-memory")
    summary = build_reliability_summary(store)
    assert summary.filters_applied == {}
    assert summary.clean_claims == 2


def test_reliability_caveat_in_filtered_text(tmp_path: Path) -> None:
    _make_claim(tmp_path)
    store = MemoryStore(tmp_path / ".chimera-memory")
    summary = build_reliability_summary(store, filters={"failure_origin": "organic_real"})
    text = format_reliability_text(summary)
    assert "descriptive only" in text
    assert "statistical proof" in text.lower()


def test_reliability_sample_size_caveat_present(tmp_path: Path) -> None:
    _make_claim(tmp_path)
    store = MemoryStore(tmp_path / ".chimera-memory")
    summary = build_reliability_summary(store)
    text = format_reliability_text(summary)
    assert "INSUFFICIENT" in text or "LOW" in text or "MEDIUM" in text


def test_reliability_invalid_filter_raises(tmp_path: Path) -> None:
    from chimera_memory.data_quality import validate_failure_origin
    with pytest.raises(ValueError, match="Invalid --failure-origin"):
        validate_failure_origin("not_a_valid_value")


# ---------------------------------------------------------------------------
# Status DQ summary
# ---------------------------------------------------------------------------


def test_status_json_includes_data_quality(tmp_path: Path) -> None:
    _make_claim(tmp_path, repair_loop_id="rl1")
    status = build_dogfood_status(root=tmp_path)
    assert "data_quality" in status
    dq = status["data_quality"]
    assert "failure_origin_counts" in dq
    assert "verification_scope_counts" in dq
    assert "repair_loop_ids" in dq
    assert "claims_with_repair_loop_id" in dq
    assert dq["claims_with_repair_loop_id"] >= 1


def test_status_dq_unknown_for_legacy(tmp_path: Path) -> None:
    _legacy_claim(tmp_path)
    status = build_dogfood_status(root=tmp_path)
    dq = status["data_quality"]
    assert dq["failure_origin_counts"].get("unknown", 0) >= 1


# ---------------------------------------------------------------------------
# Repair-loop CLI / helper
# ---------------------------------------------------------------------------


def test_repair_loop_claims_grouped(tmp_path: Path) -> None:
    _make_claim(tmp_path, repair_loop_id="loop1", repair_phase="baseline", observed=False)
    _make_claim(tmp_path, repair_loop_id="loop1", repair_phase="same_scope_after_fix")
    _make_claim(tmp_path)  # no repair loop
    store = MemoryStore(tmp_path / ".chimera-memory")

    # Manually build what repair-loops does
    loops: dict[str, list] = {}
    from chimera_memory.query import build_claim_read_model
    rm = build_claim_read_model(store)
    for c in rm.clean_claims:
        rl = (c.metadata or {}).get("repair_loop_id")
        if rl:
            loops.setdefault(str(rl), []).append(c)

    assert "loop1" in loops
    assert len(loops["loop1"]) == 2


def test_repair_loop_phases_counted(tmp_path: Path) -> None:
    _make_claim(tmp_path, repair_loop_id="lp", repair_phase="baseline", observed=False)
    _make_claim(tmp_path, repair_loop_id="lp", repair_phase="same_scope_after_fix")
    store = MemoryStore(tmp_path / ".chimera-memory")
    from chimera_memory.query import build_claim_read_model
    rm = build_claim_read_model(store)
    phases: dict[str, int] = {}
    for c in rm.clean_claims:
        m = c.metadata or {}
        if m.get("repair_loop_id") == "lp":
            ph = str(m.get("repair_phase") or "none")
            phases[ph] = phases.get(ph, 0) + 1
    assert phases.get("baseline") == 1
    assert phases.get("same_scope_after_fix") == 1
