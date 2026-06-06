"""I3A: tests for the shared claim read model in query.py."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from chimera_memory_types.finding import EvidenceRefType

from chimera_memory.ledger import build_dogfood_status, record_claim, settle_claim
from chimera_memory.query import build_claim_read_model
from chimera_memory.storage import MemoryStore


def _init(tmp_path: Path) -> MemoryStore:
    store = MemoryStore.from_paths(root=tmp_path)
    store.initialize()
    return store


def _ev(t: datetime) -> dict:
    return {"ref_type": EvidenceRefType.EXTERNAL, "ref_id": "git:abc", "available_at": t}


def _add_claim(
    tmp_path: Path,
    *,
    agent_id: str = "kiro",
    model_version: str | None = "claude-sonnet-4.6",
    task_type: str = "test",
    session_id: str = "sess-001",
    attribution_confidence: str = "high",
    identity_source: str = "cli_flag",
    passed: bool = True,
    offset: int = 0,
) -> str:
    t0 = datetime(2026, 6, 1, 12, tzinfo=UTC) + timedelta(seconds=offset)
    t1 = t0 + timedelta(seconds=5)
    extra: dict = {
        "session_id": session_id,
        "attribution_confidence": attribution_confidence,
        "identity_source": identity_source,
    }
    cid = record_claim(
        title="t", summary="s", predicted=True, evidence=[_ev(t0)],
        root=tmp_path, claim_time=t0,
        agent_id=agent_id, model_version=model_version, task_type=task_type,
        extra_metadata=extra,
    )
    settle_claim(cid, passed, t1, root=tmp_path)
    return cid


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


def test_query_counts_raw_unique_settled_clean_claims(tmp_path) -> None:
    _init(tmp_path)
    _add_claim(tmp_path, offset=0)   # 2 raw records (proposed + validated)
    _add_claim(tmp_path, offset=100)

    store = MemoryStore.from_paths(root=tmp_path)
    rm = build_claim_read_model(store)
    assert rm.raw_records == 4       # 2 claims × 2 records each
    assert rm.unique_claims == 2
    assert rm.settled_unique_claims == 2
    assert rm.clean_unique_claims == 2


def test_query_does_not_double_count_proposed_and_settled_records(tmp_path) -> None:
    _init(tmp_path)
    _add_claim(tmp_path)  # 2 raw records, 1 unique claim

    store = MemoryStore.from_paths(root=tmp_path)
    rm = build_claim_read_model(store)
    assert rm.raw_records == 2
    assert rm.unique_claims == 1
    assert rm.clean_unique_claims == 1


def test_query_excludes_pre_c1_unknown_agent_claims(tmp_path) -> None:
    _init(tmp_path)
    _add_claim(tmp_path, agent_id="kiro", offset=0)
    _add_claim(tmp_path, agent_id="unknown-agent", offset=100)

    store = MemoryStore.from_paths(root=tmp_path)
    rm = build_claim_read_model(store)
    assert rm.clean_unique_claims == 1
    assert rm.exclusions.unknown_agent == 1


def test_query_allows_missing_harness_id_for_clean_claims(tmp_path) -> None:
    """harness_id absence does not disqualify a clean claim."""
    _init(tmp_path)
    # No harness_id in extra_metadata
    t0 = datetime(2026, 6, 1, 12, tzinfo=UTC)
    t1 = t0 + timedelta(seconds=5)
    cid = record_claim(
        title="t", summary="s", predicted=True, evidence=[_ev(t0)],
        root=tmp_path, claim_time=t0,
        agent_id="kiro", model_version="m", task_type="test",
        extra_metadata={
            "session_id": "sess-001",
            "attribution_confidence": "high",
            "identity_source": "cli_flag",
        },
    )
    settle_claim(cid, True, t1, root=tmp_path)

    store = MemoryStore.from_paths(root=tmp_path)
    rm = build_claim_read_model(store)
    assert rm.clean_unique_claims == 1


def test_query_segments_clean_claims(tmp_path) -> None:
    _init(tmp_path)
    _add_claim(tmp_path, agent_id="kiro", task_type="test", offset=0)
    _add_claim(tmp_path, agent_id="kiro", task_type="lint", offset=100)
    _add_claim(tmp_path, agent_id="other", task_type="docs", offset=200)

    store = MemoryStore.from_paths(root=tmp_path)
    rm = build_claim_read_model(store)
    assert rm.segments.by_agent_id["kiro"] == 2
    assert rm.segments.by_agent_id["other"] == 1
    assert rm.segments.by_task_type["test"] == 1
    assert rm.segments.by_task_type["lint"] == 1


def test_query_collects_contradicted_failures_only(tmp_path) -> None:
    _init(tmp_path)
    _add_claim(tmp_path, passed=True, offset=0)
    _add_claim(tmp_path, passed=False, offset=100)  # CONTRADICTED

    store = MemoryStore.from_paths(root=tmp_path)
    rm = build_claim_read_model(store)
    assert len(rm.failures) == 1
    assert rm.clean_unique_claims == 2  # both are clean (failure doesn't mean dirty)


def test_query_matches_status_clean_claim_counts(tmp_path) -> None:
    """build_claim_read_model and build_dogfood_status must agree on counts."""
    _init(tmp_path)
    _add_claim(tmp_path, offset=0)
    _add_claim(tmp_path, agent_id="unknown-agent", offset=100)

    store = MemoryStore.from_paths(root=tmp_path)
    rm = build_claim_read_model(store)
    status = build_dogfood_status(root=tmp_path)

    assert rm.clean_unique_claims == status["clean_unique_claims"]
    assert rm.raw_records == status["raw_records"]
    assert rm.exclusions.unknown_agent == status["excluded"]["unknown_agent"]


def test_query_latest_claims_from_records_matches_store_latest_claims(tmp_path) -> None:
    """latest_claims_from_records() produces the same result as store.latest_claims()."""
    from chimera_memory.query import latest_claims_from_records

    _init(tmp_path)
    _add_claim(tmp_path, offset=0)
    _add_claim(tmp_path, offset=100)

    store = MemoryStore.from_paths(root=tmp_path)
    raw = store.read_claims()
    from_helper = {c.claim_id for c in latest_claims_from_records(raw)}
    from_store = {c.claim_id for c in store.latest_claims()}
    assert from_helper == from_store


def test_build_claim_read_model_uses_single_raw_record_source(tmp_path) -> None:
    """build_claim_read_model counts are consistent after single-pass refactor."""
    _init(tmp_path)
    _add_claim(tmp_path, offset=0)
    _add_claim(tmp_path, agent_id="unknown-agent", offset=100)

    store = MemoryStore.from_paths(root=tmp_path)
    rm = build_claim_read_model(store)
    # raw_records should be 2 claims × 2 records each = 4
    assert rm.raw_records == 4
    # unique = 2, clean = 1 (unknown-agent excluded)
    assert rm.unique_claims == 2
    assert rm.clean_unique_claims == 1
