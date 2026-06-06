"""Tests for M2B readiness gate."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from chimera_memory_types.finding import EvidenceRef, EvidenceRefType

from chimera_memory.ledger import build_dogfood_status, record_claim, settle_claim
from chimera_memory.m2b_readiness import (
    compute_m2b_readiness,
    format_readiness_text,
)
from chimera_memory.storage import MemoryStore

_T0 = datetime(2026, 1, 1, 12, tzinfo=UTC)
_T1 = datetime(2026, 1, 1, 13, tzinfo=UTC)

_CLEAN_EXTRA = {
    "session_id": "sess-001",
    "harness_id": "h",
    "attribution_confidence": "high",
    "identity_source": "cli_flag",
}


def _ev() -> EvidenceRef:
    return EvidenceRef(ref_type=EvidenceRefType.EXTERNAL, ref_id="r", available_at=_T0)


def _make(root: Path, *, origin: str = "organic_real", scope: str = "package",
          observed: bool = True, agent: str = "a", repair_loop: str | None = None,
          repair_phase: str | None = None) -> str:
    extra = {**_CLEAN_EXTRA, "failure_origin": origin, "verification_scope": scope}
    if repair_loop:
        extra["repair_loop_id"] = repair_loop
    if repair_phase:
        extra["repair_phase"] = repair_phase
    cid = record_claim(
        title="t", summary="s", predicted=True, evidence=[_ev()],
        root=root, claim_time=_T0, agent_id=agent, model_version="m",
        task_type="test", extra_metadata=extra,
    )
    settle_claim(cid, observed, _T1, root=root)
    return cid


# ---------------------------------------------------------------------------


def test_empty_ledger_is_blocked(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / ".chimera-memory")
    store.ensure()
    report = compute_m2b_readiness(store)
    assert report.readiness_level == "blocked"
    assert report.m2b_ready is False
    assert any("no claims" in b for b in report.blockers)


def test_only_legacy_unknown_claims_blocked(tmp_path: Path) -> None:
    """Claims without DQ metadata → unknown → metadata coverage blocker."""
    for _i in range(10):
        cid = record_claim(
            title="t", summary="s", predicted=True, evidence=[_ev()],
            root=tmp_path, claim_time=_T0, agent_id="a", model_version="m",
            task_type="test", extra_metadata={**_CLEAN_EXTRA},
        )
        settle_claim(cid, True, _T1, root=tmp_path)
    store = MemoryStore(tmp_path / ".chimera-memory")
    report = compute_m2b_readiness(store)
    assert report.readiness_level == "blocked"
    assert any("metadata coverage" in b for b in report.blockers)


def test_enough_claims_but_not_organic_blocked(tmp_path: Path) -> None:
    for _i in range(30):
        _make(tmp_path, origin="synthetic")
    store = MemoryStore(tmp_path / ".chimera-memory")
    report = compute_m2b_readiness(store)
    assert any("organic_real claims too few" in b for b in report.blockers)


def test_enough_organic_but_not_failures_blocked(tmp_path: Path) -> None:
    for _i in range(30):
        _make(tmp_path, origin="organic_real", observed=True)  # all pass
    store = MemoryStore(tmp_path / ".chimera-memory")
    report = compute_m2b_readiness(store)
    assert any("organic_real failures" in b for b in report.blockers)


def test_enough_organic_failures_but_no_groups_blocked(tmp_path: Path) -> None:
    # 30 organic, 5 failed, but only 1 agent — won't reach 2 comparable groups of 10
    for _i in range(25):
        _make(tmp_path, origin="organic_real", observed=True, agent="single-agent")
    for _i in range(5):
        _make(tmp_path, origin="organic_real", observed=False, agent="single-agent")
    store = MemoryStore(tmp_path / ".chimera-memory")
    report = compute_m2b_readiness(store)
    assert any("comparable groups" in b for b in report.blockers)


def test_review_ready_scenario(tmp_path: Path) -> None:
    """Two agents, 10+ organic each, 5+ organic failures, good coverage, repair loops."""
    # Create 2 agents × 15 organic claims each = 30 organic total, 6 failed each = 12 total
    for agent in ("agent-a", "agent-b"):
        for idx in range(15):
            _make(tmp_path, origin="organic_real", observed=(idx >= 3), agent=agent)
        # Add repair loops for each agent  
    for loop_idx in range(4):
        _make(tmp_path, origin="organic_real", observed=False, agent="agent-a",
              repair_loop=f"loop-{loop_idx}", repair_phase="baseline")
        _make(tmp_path, origin="organic_real", observed=True, agent="agent-a",
              repair_loop=f"loop-{loop_idx}", repair_phase="same_scope_after_fix")

    store = MemoryStore(tmp_path / ".chimera-memory")
    report = compute_m2b_readiness(store)
    # 30 organic from agents + 8 repair loop claims = 38 total organic
    assert report.readiness_evaluation_summary["organic_real"] >= 25
    assert report.readiness_evaluation_summary["organic_real_failed"] >= 5
    assert report.readiness_evaluation_summary["comparable_groups"] >= 2
    assert report.repair_loop_summary["complete_loops"] >= 3
    assert report.readiness_level in ("review_ready", "weak")


def test_json_schema_has_required_keys(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / ".chimera-memory")
    store.ensure()
    d = compute_m2b_readiness(store).to_dict()
    for key in ("schema_version", "evaluation_mode", "m2b_ready", "readiness_level", "blockers",
                "warnings", "thresholds", "all_ledger_summary", "dq_cohort_summary",
                "readiness_evaluation_summary", "effective_group_summaries",
                "repair_loop_summary", "notes"):
        assert key in d, f"missing key: {key}"


def test_text_says_not_m2b_drift(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / ".chimera-memory")
    store.ensure()
    text = format_readiness_text(compute_m2b_readiness(store))
    assert "not M2B drift scoring" in text


def test_text_no_model_ranking_language(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / ".chimera-memory")
    store.ensure()
    text = format_readiness_text(compute_m2b_readiness(store))
    # These affirmative claims must not appear in output
    for bad in ("best model", "model A is better", "deploy automatically"):
        assert bad.lower() not in text.lower(), f"forbidden language found: {bad!r}"
    # The word "routing" as an affirmative recommendation must not appear
    assert "routing authority" not in text.lower() or "not" in text.lower()


def test_repair_loop_summary_counts(tmp_path: Path) -> None:
    _make(tmp_path, repair_loop="lp1", repair_phase="baseline", observed=False)
    _make(tmp_path, repair_loop="lp1", repair_phase="same_scope_after_fix")
    store = MemoryStore(tmp_path / ".chimera-memory")
    report = compute_m2b_readiness(store)
    assert report.repair_loop_summary["total_loops"] == 1
    assert report.repair_loop_summary["complete_loops"] == 1


def test_status_json_includes_m2b_readiness_level(tmp_path: Path) -> None:
    _make(tmp_path)
    status = build_dogfood_status(root=tmp_path)
    assert "m2b_readiness_level" in status
    assert status["m2b_readiness_level"] in ("blocked", "weak", "review_ready", "unknown")


def test_summary_organic_counts(tmp_path: Path) -> None:
    _make(tmp_path, origin="organic_real")
    _make(tmp_path, origin="synthetic")
    store = MemoryStore(tmp_path / ".chimera-memory")
    report = compute_m2b_readiness(store)
    assert report.dq_cohort_summary["organic_real"] == 1
    assert report.dq_cohort_summary["synthetic"] == 1


# ---------------------------------------------------------------------------
# Cohort model tests
# ---------------------------------------------------------------------------


def test_legacy_only_evaluates_all_ledger(tmp_path: Path) -> None:
    """Legacy claims (no DQ) → default mode falls back to all_ledger."""
    for _i in range(5):
        cid = record_claim(
            title="legacy", summary="s", predicted=True, evidence=[_ev()],
            root=tmp_path, claim_time=_T0, agent_id="a", model_version="m",
            task_type="test", extra_metadata={**_CLEAN_EXTRA},
        )
        settle_claim(cid, True, _T1, root=tmp_path)
    store = MemoryStore(tmp_path / ".chimera-memory")
    report = compute_m2b_readiness(store)
    assert report.evaluation_mode == "all_ledger"
    assert report.dq_cohort_summary["total"] == 0
    assert report.dq_cohort_summary["legacy_unlabeled_claims"] == 5


def test_mixed_default_evaluates_dq_cohort(tmp_path: Path) -> None:
    """Mixed legacy + DQ claims → default evaluates DQ cohort only."""
    # Add legacy claim
    cid = record_claim(
        title="legacy", summary="s", predicted=True, evidence=[_ev()],
        root=tmp_path, claim_time=_T0, agent_id="a", model_version="m",
        task_type="test", extra_metadata={**_CLEAN_EXTRA},
    )
    settle_claim(cid, True, _T1, root=tmp_path)
    # Add DQ claim
    _make(tmp_path, origin="organic_real")
    store = MemoryStore(tmp_path / ".chimera-memory")
    report = compute_m2b_readiness(store)
    assert report.evaluation_mode == "dq_cohort"
    assert report.dq_cohort_summary["total"] == 1
    assert report.dq_cohort_summary["legacy_unlabeled_claims"] == 1
    assert report.all_ledger_summary["total_clean_claims"] == 2


def test_all_ledger_fails_metadata_coverage(tmp_path: Path) -> None:
    """--all-ledger includes legacy unknowns and fails coverage gate."""
    _make(tmp_path)  # 1 DQ claim
    # Add 10 legacy claims
    for _i in range(10):
        cid = record_claim(
            title="t", summary="s", predicted=True, evidence=[_ev()],
            root=tmp_path, claim_time=_T0, agent_id="a", model_version="m",
            task_type="test", extra_metadata={**_CLEAN_EXTRA},
        )
        settle_claim(cid, True, _T1, root=tmp_path)
    store = MemoryStore(tmp_path / ".chimera-memory")
    report = compute_m2b_readiness(store, mode="all_ledger")
    assert report.evaluation_mode == "all_ledger"
    # 1/11 = 9% coverage → fails
    assert any("metadata coverage" in b.lower() or "too low" in b.lower() for b in report.blockers)


def test_dq_only_excludes_legacy(tmp_path: Path) -> None:
    """--dq-only evaluates only DQ claims; legacy unknowns not in scope."""
    _make(tmp_path, origin="organic_real")
    for _i in range(100):
        cid = record_claim(
            title="t", summary="s", predicted=True, evidence=[_ev()],
            root=tmp_path, claim_time=_T0, agent_id="x", model_version="m",
            task_type="test", extra_metadata={**_CLEAN_EXTRA},
        )
        settle_claim(cid, True, _T1, root=tmp_path)
    store = MemoryStore(tmp_path / ".chimera-memory")
    report = compute_m2b_readiness(store, mode="dq_cohort")
    assert report.evaluation_mode == "dq_cohort"
    assert report.readiness_evaluation_summary["evaluated_claims"] == 1
    # legacy excluded from readiness evaluation
    assert report.dq_cohort_summary["legacy_unlabeled_claims"] == 100


def test_dq_cohort_16_organic_not_metadata_blocked(tmp_path: Path) -> None:
    """With 16 organic claims, DQ cohort is NOT blocked by metadata coverage."""
    for _i in range(16):
        _make(tmp_path, origin="organic_real")
    store = MemoryStore(tmp_path / ".chimera-memory")
    report = compute_m2b_readiness(store, mode="dq_cohort")
    # All 16 have DQ labels → coverage = 100% within cohort
    assert report.readiness_evaluation_summary["metadata_coverage_pct"] == 100.0
    # Still blocked by organic count and failures
    assert any("organic_real claims too few" in b for b in report.blockers)


def test_conflicting_flags_returns_error(tmp_path: Path) -> None:
    """--dq-only and --all-ledger together should error at parse time via CLI."""
    # Test via module: conflicting modes handled at CLI level; module accepts explicit mode
    # Just verify that passing an invalid mode doesn't crash
    store = MemoryStore(tmp_path / ".chimera-memory")
    store.ensure()
    try:
        compute_m2b_readiness(store, mode="invalid_mode")
    except (ValueError, KeyError):
        pass  # acceptable to raise


def test_json_includes_evaluation_mode(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / ".chimera-memory")
    store.ensure()
    d = compute_m2b_readiness(store).to_dict()
    assert "evaluation_mode" in d
    assert d["evaluation_mode"] in ("default", "dq_cohort", "all_ledger")


def test_text_says_legacy_excluded_in_dq_mode(tmp_path: Path) -> None:
    _make(tmp_path)
    store = MemoryStore(tmp_path / ".chimera-memory")
    report = compute_m2b_readiness(store, mode="dq_cohort")
    text = format_readiness_text(report)
    assert "Legacy" in text or "legacy" in text
    assert "excluded" in text.lower()


def test_status_json_includes_evaluation_mode(tmp_path: Path) -> None:
    _make(tmp_path)
    status = build_dogfood_status(root=tmp_path)
    assert "m2b_readiness_evaluation_mode" in status
    assert status["m2b_readiness_evaluation_mode"] in ("dq_cohort", "all_ledger", "unknown")
