"""M2A: unit tests for the read-only reliability summary builder."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from chimera_memory_types.finding import EvidenceRefType

from chimera_memory.ledger import record_claim, settle_claim
from chimera_memory.reliability import (
    _confidence,
    build_reliability_summary,
    format_reliability_text,
)
from chimera_memory.storage import MemoryStore


def _init(tmp_path: Path) -> MemoryStore:
    store = MemoryStore.from_paths(root=tmp_path)
    store.initialize()
    return store


def _ev(t: datetime) -> dict:
    return {"ref_type": EvidenceRefType.EXTERNAL, "ref_id": "git:abc", "available_at": t}


def _add(
    tmp_path: Path,
    *,
    passed: bool = True,
    agent_id: str = "kiro",
    model_version: str = "claude-sonnet-4.6",
    task_type: str = "test",
    session_id: str = "sess-001",
    offset: int = 0,
    command: str = "pytest",
) -> str:
    t0 = datetime(2026, 6, 1, 12, tzinfo=UTC) + timedelta(seconds=offset)
    t1 = t0 + timedelta(seconds=5)
    cid = record_claim(
        title=f"wrap {command}", summary="s", predicted=True, evidence=[_ev(t0)],
        root=tmp_path, claim_time=t0,
        agent_id=agent_id, model_version=model_version, task_type=task_type,
        extra_metadata={
            "session_id": session_id,
            "attribution_confidence": "high",
            "identity_source": "cli_flag",
        },
    )
    settle_claim(cid, passed, t1, root=tmp_path,
                 event_metadata={"exit_code": 0 if passed else 1,
                                 "wrapped_args": command.split()})
    return cid


# ---------------------------------------------------------------------------
# confidence label tests
# ---------------------------------------------------------------------------


def test_confidence_label_insufficient_below_5() -> None:
    assert _confidence(0) == "INSUFFICIENT"
    assert _confidence(4) == "INSUFFICIENT"


def test_confidence_label_low_5_to_24() -> None:
    assert _confidence(5) == "LOW"
    assert _confidence(24) == "LOW"


def test_confidence_label_medium_25_and_above() -> None:
    assert _confidence(25) == "MEDIUM"
    assert _confidence(100) == "MEDIUM"


# ---------------------------------------------------------------------------
# reliability builder tests
# ---------------------------------------------------------------------------


def test_reliability_counts_validated_and_contradicted_latest_claims(tmp_path) -> None:
    _init(tmp_path)
    _add(tmp_path, passed=True, offset=0)
    _add(tmp_path, passed=False, offset=10)

    store = MemoryStore.from_paths(root=tmp_path)
    summary = build_reliability_summary(store)
    assert summary.clean_claims == 2
    groups = summary.by_agent_model_task
    assert len(groups) == 1
    g = groups[0]
    assert g.validated == 1
    assert g.contradicted == 1
    assert g.total == 2
    assert g.validation_rate == 0.5
    assert g.failure_rate == 0.5


def test_reliability_does_not_double_count_proposed_and_settled_records(tmp_path) -> None:
    """Each claim_id should count once using latest-per-claim semantics."""
    _init(tmp_path)
    # propose + settle = 2 raw records for 1 unique clean claim
    _add(tmp_path, passed=True, offset=0)

    store = MemoryStore.from_paths(root=tmp_path)
    summary = build_reliability_summary(store)
    assert summary.clean_claims == 1
    assert summary.by_agent_model_task[0].total == 1


def test_reliability_groups_by_agent_model_task_type(tmp_path) -> None:
    _init(tmp_path)
    _add(tmp_path, agent_id="kiro", task_type="test", offset=0)
    _add(tmp_path, agent_id="kiro", task_type="lint", offset=10)
    _add(tmp_path, agent_id="codebuff", model_version="mimo", task_type="test", offset=20)

    store = MemoryStore.from_paths(root=tmp_path)
    summary = build_reliability_summary(store)
    groups = {(g.agent_id, g.task_type): g for g in summary.by_agent_model_task}
    assert ("kiro", "test") in groups
    assert ("kiro", "lint") in groups
    assert ("codebuff", "test") in groups
    assert summary.groups_total == 3


def test_reliability_excludes_unclean_unknown_agent_records(tmp_path) -> None:
    _init(tmp_path)
    _add(tmp_path, agent_id="kiro", offset=0)
    # unknown-agent claim — not clean
    t0 = datetime(2026, 6, 1, 12, tzinfo=UTC) + timedelta(seconds=100)
    t1 = t0 + timedelta(seconds=5)
    cid = record_claim(
        title="unknown", summary="s", predicted=True, evidence=[_ev(t0)],
        root=tmp_path, claim_time=t0, agent_id="unknown-agent",
    )
    settle_claim(cid, True, t1, root=tmp_path)

    store = MemoryStore.from_paths(root=tmp_path)
    summary = build_reliability_summary(store)
    assert summary.clean_claims == 1
    agent_ids = {g.agent_id for g in summary.by_agent_model_task}
    assert "unknown-agent" not in agent_ids


def test_reliability_notes_failure_quality_not_machine_readable(tmp_path) -> None:
    _init(tmp_path)
    _add(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    summary = build_reliability_summary(store)
    notes = summary.notes
    assert notes["read_only"] is True
    assert notes["no_routing"] is True
    assert notes["no_autonomy"] is True
    assert notes["no_model_ranking"] is True
    assert "failure-quality" in notes["classification_quality"]
    assert "organic" in notes["classification_quality"]


def test_reliability_is_read_only(tmp_path) -> None:
    """build_reliability_summary must not add claims or modify the store."""
    _init(tmp_path)
    _add(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    before = len(store.read_claims())
    build_reliability_summary(store)
    after = len(store.read_claims())
    assert before == after


def test_reliability_possible_synthetic_detection(tmp_path) -> None:
    """Claims with 'python -c ... SystemExit' commands are flagged."""
    _init(tmp_path)
    t0 = datetime(2026, 6, 1, 12, tzinfo=UTC)
    t1 = t0 + timedelta(seconds=5)
    cid = record_claim(
        title="synth", summary="s", predicted=True, evidence=[_ev(t0)],
        root=tmp_path, claim_time=t0, agent_id="kiro",
        model_version="claude-sonnet-4.6", task_type="lint",
        extra_metadata={"session_id": "s1", "attribution_confidence": "high",
                        "identity_source": "cli_flag"},
    )
    settle_claim(cid, False, t1, root=tmp_path,
                 event_metadata={"exit_code": 7,
                                 "wrapped_args": ["python", "-c", "raise SystemExit(7)"]})

    store = MemoryStore.from_paths(root=tmp_path)
    summary = build_reliability_summary(store)
    assert summary.by_agent_model_task[0].possible_synthetic_count == 1


def test_reliability_to_dict_contract_stable(tmp_path) -> None:
    _init(tmp_path)
    _add(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    summary = build_reliability_summary(store)
    d = summary.to_dict()
    for key in ("clean_claims", "groups_total", "failures_total",
                "by_agent_model_task", "notes"):
        assert key in d
    assert isinstance(d["by_agent_model_task"], list)
    g = d["by_agent_model_task"][0]
    for gkey in ("agent_id", "model_version", "task_type", "total", "validated",
                 "contradicted", "validation_rate", "failure_rate", "confidence"):
        assert gkey in g


def test_reliability_text_format_includes_warnings(tmp_path) -> None:
    _init(tmp_path)
    _add(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    summary = build_reliability_summary(store)
    text = format_reliability_text(summary)
    assert "Read-only: yes" in text
    assert "Warning" in text
    assert "failure-quality" in text or "ranking" in text
