"""Tests for claim errata correction system."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from chimera_memory_types.finding import EvidenceRef, EvidenceRefType

from chimera_memory.cli import main
from chimera_memory.errata import add_errata, apply_errata, load_errata
from chimera_memory.ledger import record_claim, settle_claim
from chimera_memory.m2b_readiness import compute_m2b_readiness
from chimera_memory.storage import MemoryStore

_T0 = datetime(2026, 1, 1, 12, tzinfo=UTC)
_T1 = datetime(2026, 1, 1, 13, tzinfo=UTC)
_CLEAN = {
    "harness_id": "h", "attribution_confidence": "high",
    "identity_source": "cli_flag",
}


def _ev() -> EvidenceRef:
    return EvidenceRef(ref_type=EvidenceRefType.EXTERNAL, ref_id="r", available_at=_T0)


def _make(root: Path, *, origin: str, observed: bool = True,
          agent: str = "a", session_id: str = "sess-001") -> str:
    extra = {**_CLEAN, "failure_origin": origin, "verification_scope": "package",
              "session_id": session_id}
    cid = record_claim(
        title="t", summary="s", predicted=True, evidence=[_ev()],
        root=root, claim_time=_T0, agent_id=agent, model_version="m",
        task_type="test", extra_metadata=extra,
    )
    settle_claim(cid, observed, _T1, root=root)
    return cid


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


def test_add_and_load_errata(tmp_path: Path) -> None:
    mem = tmp_path / ".chimera-memory"
    mem.mkdir()
    add_errata(mem, "abc-123", "invocation_artifact", "shell quote typo")
    errata = load_errata(mem)
    assert "abc-123" in errata
    assert errata["abc-123"]["corrected_failure_origin"] == "invocation_artifact"


def test_load_errata_empty(tmp_path: Path) -> None:
    mem = tmp_path / ".chimera-memory"
    mem.mkdir()
    assert load_errata(mem) == {}


def test_errata_rejects_invalid_origin(tmp_path: Path) -> None:
    mem = tmp_path / ".chimera-memory"
    mem.mkdir()
    with pytest.raises(ValueError):
        add_errata(mem, "abc", "not_valid_origin", "test")


def test_apply_errata_returns_corrected_origin(tmp_path: Path) -> None:
    cid = _make(tmp_path, origin="organic_real", observed=False)
    mem = tmp_path / ".chimera-memory"
    add_errata(mem, cid, "invocation_artifact", "shell typo")
    errata_map = load_errata(mem)
    store = MemoryStore(mem)
    claim = store.latest_claim(cid)
    assert apply_errata(claim, errata_map) == "invocation_artifact"


def test_apply_errata_returns_none_when_no_errata(tmp_path: Path) -> None:
    cid = _make(tmp_path, origin="organic_real")
    store = MemoryStore(tmp_path / ".chimera-memory")
    claim = store.latest_claim(cid)
    assert apply_errata(claim, {}) is None


# ---------------------------------------------------------------------------
# Integration: errata affects m2b-readiness organic_real_failed count
# ---------------------------------------------------------------------------


def test_errata_excludes_invocation_failure_from_m2b_organic_failed(tmp_path: Path) -> None:
    """Claim originally labeled organic_real but corrected to invocation_artifact
    must not count toward organic_real_failed in m2b-readiness."""
    # Create a CONTRADICTED claim labeled organic_real (the mistake)
    cid = _make(tmp_path, origin="organic_real", observed=False)
    mem = tmp_path / ".chimera-memory"
    store = MemoryStore(mem)

    # Before errata: counts as 1 organic_real_failed
    report_before = compute_m2b_readiness(store)
    assert report_before.dq_cohort_summary["organic_real_failed"] == 1

    # Add errata correction
    add_errata(mem, cid, "invocation_artifact",
               reason="shell quoting error — not a product defect")

    # After errata: organic_real_failed drops to 0
    report_after = compute_m2b_readiness(store)
    assert report_after.dq_cohort_summary["organic_real_failed"] == 0
    assert report_after.notes.get("errata_applied") == 1


def test_errata_does_not_delete_original_claim(tmp_path: Path) -> None:
    """The original claim remains in the ledger unchanged."""
    cid = _make(tmp_path, origin="organic_real", observed=False)
    mem = tmp_path / ".chimera-memory"
    add_errata(mem, cid, "invocation_artifact", "test")
    store = MemoryStore(mem)
    claim = store.latest_claim(cid)
    assert claim is not None
    # Original metadata unchanged
    assert claim.metadata.get("failure_origin") == "organic_real"


def test_errata_claim_still_shows_in_failures(tmp_path: Path) -> None:
    """The errata-corrected claim still appears in failures output (it was CONTRADICTED)."""
    cid = _make(tmp_path, origin="organic_real", observed=False)
    mem = tmp_path / ".chimera-memory"
    add_errata(mem, cid, "invocation_artifact", "test")
    store = MemoryStore(mem)
    from chimera_memory.query import build_claim_read_model
    rm = build_claim_read_model(store)
    failed = [c for c in rm.failures if c.claim_id == cid]
    assert failed, "errata-corrected claim must still be visible in failures"


def test_m2b_readiness_json_exposes_errata_count(tmp_path: Path) -> None:
    cid = _make(tmp_path, origin="organic_real", observed=False)
    mem = tmp_path / ".chimera-memory"
    add_errata(mem, cid, "invocation_artifact", "test")
    store = MemoryStore(mem)
    d = compute_m2b_readiness(store).to_dict()
    assert d["notes"]["errata_applied"] == 1


# ---------------------------------------------------------------------------
# Errata propagation to reliability, failures, and export
# ---------------------------------------------------------------------------


def test_reliability_organic_only_excludes_corrected_invocation(tmp_path: Path) -> None:
    """reliability --organic-only must exclude errata-corrected invocation_artifact."""
    from chimera_memory.reliability import build_reliability_summary

    # Create 1 genuine organic + 1 misclassified invocation_artifact
    _make(tmp_path, origin="organic_real", observed=True)
    cid_bad = _make(tmp_path, origin="organic_real", observed=False)
    mem = tmp_path / ".chimera-memory"
    store = MemoryStore(mem)

    # Before errata: organic-only filter shows 2 claims
    before = build_reliability_summary(store, filters={"failure_origin": "organic_real"})
    assert before.clean_claims == 2

    # Add errata correction
    add_errata(mem, cid_bad, "invocation_artifact", "shell quoting error")

    # After errata: organic-only filter shows only 1 claim
    after = build_reliability_summary(store, filters={"failure_origin": "organic_real"})
    assert after.clean_claims == 1
    assert after.notes.get("errata_applied_count") == 1


def test_failures_filter_organic_real_excludes_corrected(tmp_path: Path) -> None:
    """failures --failure-origin organic_real must exclude errata-corrected claims."""
    from chimera_memory.errata import effective_failure_origin

    cid = _make(tmp_path, origin="organic_real", observed=False)
    mem = tmp_path / ".chimera-memory"
    add_errata(mem, cid, "invocation_artifact", "wrong path")

    store = MemoryStore(mem)
    errata_map = load_errata(mem)
    claim = store.latest_claim(cid)
    assert effective_failure_origin(claim, errata_map) == "invocation_artifact"


def test_failures_filter_invocation_artifact_includes_corrected(tmp_path: Path) -> None:
    """failures --failure-origin invocation_artifact includes errata-corrected claims."""
    from chimera_memory.errata import effective_failure_origin

    cid = _make(tmp_path, origin="organic_real", observed=False)
    mem = tmp_path / ".chimera-memory"
    add_errata(mem, cid, "invocation_artifact", "typo")

    store = MemoryStore(mem)
    errata_map = load_errata(mem)
    claim = store.latest_claim(cid)
    assert effective_failure_origin(claim, errata_map) == "invocation_artifact"


def test_export_effective_data_quality_block(tmp_path: Path) -> None:
    """Export event must include effective_data_quality with errata correction."""
    from chimera_memory.export import build_engine_events

    cid = _make(tmp_path, origin="organic_real", observed=False)
    mem = tmp_path / ".chimera-memory"
    add_errata(mem, cid, "invocation_artifact", "shell quoting error")

    store = MemoryStore(mem)
    events = build_engine_events(store)
    assert events, "expected at least one event"
    evt = events[0]
    assert "effective_data_quality" in evt
    edq = evt["effective_data_quality"]
    assert edq["errata_applied"] is True
    assert edq["failure_origin"] == "invocation_artifact"
    assert edq.get("corrected_from") == "organic_real"
    # Original data_quality block unchanged
    assert evt["data_quality"]["failure_origin"] == "organic_real"


def test_export_effective_data_quality_no_errata(tmp_path: Path) -> None:
    """Export event for non-corrected claim shows errata_applied=False."""
    from chimera_memory.export import build_engine_events

    cid = _make(tmp_path, origin="organic_real", observed=True)
    store = MemoryStore(tmp_path / ".chimera-memory")
    events = build_engine_events(store)
    assert events
    evt = events[0]
    assert evt["effective_data_quality"]["errata_applied"] is False
    assert evt["effective_data_quality"]["failure_origin"] == "organic_real"


def test_effective_metadata_helper(tmp_path: Path) -> None:
    """effective_metadata returns full overlay dict."""
    from chimera_memory.errata import effective_metadata

    cid = _make(tmp_path, origin="organic_real", observed=False)
    mem = tmp_path / ".chimera-memory"
    add_errata(mem, cid, "invocation_artifact", "test reason", note="test note")

    store = MemoryStore(mem)
    errata_map = load_errata(mem)
    claim = store.latest_claim(cid)
    em = effective_metadata(claim, errata_map)
    assert em["errata_applied"] is True
    assert em["effective"]["failure_origin"] == "invocation_artifact"
    assert em["raw"]["failure_origin"] == "organic_real"
    assert em["errata_reason"] == "test reason"


def test_errata_add_cli_resolves_short_prefix(tmp_path: Path, monkeypatch) -> None:
    """errata add with 8-char prefix resolves to full UUID — no mismatch."""
    monkeypatch.chdir(tmp_path)
    cid = _make(tmp_path, origin="organic_real", observed=False)
    # Add errata using only the first 8 chars (as happens when copying from CONTRADICTED output)
    prefix = cid[:8]
    ret = main(["errata", "add", prefix,
                "--failure-origin", "invocation_artifact",
                "--reason", "shell quoting"])
    assert ret == 0
    mem = tmp_path / ".chimera-memory"
    errata = load_errata(mem)
    # The errata must be keyed on the FULL UUID, not the prefix
    assert cid in errata, f"errata must use full UUID, not prefix. Keys: {list(errata.keys())}"
    assert errata[cid]["corrected_failure_origin"] == "invocation_artifact"

    # Verify errata actually applies to m2b-readiness
    store = MemoryStore(mem)
    report = compute_m2b_readiness(store)
    assert report.dq_cohort_summary["organic_real_failed"] == 0
