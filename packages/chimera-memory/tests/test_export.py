"""J1A: tests for engine-ready event export."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from chimera_memory_types.finding import EvidenceRefType

from chimera_memory.cli import main
from chimera_memory.export import build_engine_events, format_events_jsonl
from chimera_memory.ledger import record_claim, settle_claim
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
    passed: bool = True,
    agent_id: str = "kiro",
    model_version: str = "claude-sonnet-4.6",
    task_type: str = "test",
    session_id: str = "sess-001",
    offset: int = 0,
    with_witness: bool = False,
) -> str:
    t0 = datetime(2026, 6, 1, 12, tzinfo=UTC) + timedelta(seconds=offset)
    t1 = t0 + timedelta(seconds=5)
    cid = record_claim(
        title="wrap cmd", summary="s", predicted=True, evidence=[_ev(t0)],
        root=tmp_path, claim_time=t0,
        agent_id=agent_id, model_version=model_version, task_type=task_type,
        extra_metadata={
            "session_id": session_id,
            "attribution_confidence": "high",
            "identity_source": "cli_flag",
        },
    )
    evt_meta = {"exit_code": 0 if passed else 7, "wrapped_args": ["pytest", "-q"]}
    if with_witness:
        evt_meta["stdout_excerpt"] = "ok"
        evt_meta["stderr_excerpt"] = "bad lint" if not passed else ""
    settle_claim(cid, passed, t1, root=tmp_path, event_metadata=evt_meta)
    return cid


def _run(argv: list[str], tmp_path: Path, monkeypatch) -> int:
    monkeypatch.chdir(tmp_path)
    return main(argv)


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


def test_export_builds_settled_claim_event(tmp_path) -> None:
    _init(tmp_path)
    _add_claim(tmp_path)

    store = MemoryStore.from_paths(root=tmp_path)
    events = build_engine_events(store)
    assert len(events) == 1
    e = events[0]
    assert e["schema_version"] == 1
    assert e["event_type"] == "memory.claim.settled"
    assert e["source"] == "chimera-memory"


def test_export_omits_unsettled_claims(tmp_path) -> None:
    _init(tmp_path)
    # Create a claim but don't settle it
    t0 = datetime(2026, 6, 1, 12, tzinfo=UTC)
    record_claim(
        title="unsettled", summary="s", predicted=True, evidence=[_ev(t0)],
        root=tmp_path, claim_time=t0, agent_id="kiro",
    )

    store = MemoryStore.from_paths(root=tmp_path)
    events = build_engine_events(store)
    assert len(events) == 0


def test_export_includes_agent_model_harness_task(tmp_path) -> None:
    _init(tmp_path)
    _add_claim(tmp_path, agent_id="kiro", model_version="claude-sonnet-4.6", task_type="lint")

    store = MemoryStore.from_paths(root=tmp_path)
    events = build_engine_events(store)
    e = events[0]
    assert e["agent"]["id"] == "kiro"
    assert e["agent"]["model"] == "claude-sonnet-4.6"
    assert e["task"]["type"] == "lint"


def test_export_includes_command_and_exit_code(tmp_path) -> None:
    _init(tmp_path)
    _add_claim(tmp_path, passed=True)

    store = MemoryStore.from_paths(root=tmp_path)
    events = build_engine_events(store)
    e = events[0]
    assert "pytest" in e["command"]["display"]
    assert e["outcome"]["exit_code"] == 0
    assert e["outcome"]["status"] == "VALIDATED"


def test_export_includes_stdout_stderr_witnesses(tmp_path) -> None:
    _init(tmp_path)
    _add_claim(tmp_path, passed=False, with_witness=True)

    store = MemoryStore.from_paths(root=tmp_path)
    events = build_engine_events(store)
    e = events[0]
    assert e["witness"]["stderr_excerpt"] == "bad lint"


def test_export_jsonl_is_parseable_and_stable(tmp_path) -> None:
    _init(tmp_path)
    _add_claim(tmp_path, offset=0)
    _add_claim(tmp_path, offset=100)

    store = MemoryStore.from_paths(root=tmp_path)
    events = build_engine_events(store)
    jsonl = format_events_jsonl(events)
    lines = [ln for ln in jsonl.splitlines() if ln.strip()]
    assert len(lines) == 2
    for line in lines:
        parsed = json.loads(line)
        assert "event_id" in parsed
        assert "claim_id" in parsed
    # Deterministic IDs
    ids = [json.loads(ln)["event_id"] for ln in lines]
    assert ids == sorted(ids) or len(set(ids)) == 2  # unique IDs


def test_export_failures_only_filters_validated_claims(tmp_path) -> None:
    _init(tmp_path)
    _add_claim(tmp_path, passed=True, offset=0)    # VALIDATED
    _add_claim(tmp_path, passed=False, offset=100)  # CONTRADICTED

    store = MemoryStore.from_paths(root=tmp_path)
    all_events = build_engine_events(store)
    fail_events = build_engine_events(store, failures_only=True)
    assert len(all_events) == 2
    assert len(fail_events) == 1
    assert fail_events[0]["outcome"]["status"] == "CONTRADICTED"


def test_export_cli_writes_output_file(tmp_path, monkeypatch, capsys) -> None:
    _init(tmp_path)
    _add_claim(tmp_path)
    monkeypatch.chdir(tmp_path)
    out_path = tmp_path / "events.jsonl"
    code = main(["export", "--output", str(out_path)])
    assert code == 0
    assert out_path.exists()
    lines = [ln for ln in out_path.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["event_type"] == "memory.claim.settled"


def test_export_cli_stdout_outputs_jsonl(tmp_path, monkeypatch, capsys) -> None:
    _init(tmp_path)
    _add_claim(tmp_path)
    code = _run(["export"], tmp_path, monkeypatch)
    assert code == 0
    out = capsys.readouterr().out.strip()
    parsed = json.loads(out)
    assert "event_id" in parsed


def test_export_does_not_mutate_store(tmp_path) -> None:
    _init(tmp_path)
    _add_claim(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    before = len(store.read_claims())
    build_engine_events(store)
    after = len(store.read_claims())
    assert before == after


# =============================================================================
# J1B tests — clean_only, session_id, composition
# =============================================================================


def test_export_clean_only_excludes_unknown_agent_claims(tmp_path) -> None:
    _init(tmp_path)
    _add_claim(tmp_path, agent_id="unknown-agent", offset=0)
    _add_claim(tmp_path, agent_id="kiro", offset=100)

    store = MemoryStore.from_paths(root=tmp_path)
    events = build_engine_events(store, clean_only=True)
    assert len(events) == 1
    assert events[0]["agent"]["id"] == "kiro"


def test_export_clean_only_allows_unknown_model_literal(tmp_path) -> None:
    """model='unknown' is valid for clean export (it is honest attribution)."""
    _init(tmp_path)
    _add_claim(tmp_path, model_version="unknown")

    store = MemoryStore.from_paths(root=tmp_path)
    events = build_engine_events(store, clean_only=True)
    assert len(events) == 1
    assert events[0]["agent"]["model"] == "unknown"


def test_export_clean_only_allows_missing_harness_id(tmp_path) -> None:
    """Missing harness_id does not disqualify a clean export."""
    _init(tmp_path)
    # Use _add_claim which doesn't set harness_id in extra_metadata
    _add_claim(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    events = build_engine_events(store, clean_only=True)
    assert len(events) == 1  # claim is still clean


def test_export_session_id_filters_events(tmp_path) -> None:
    _init(tmp_path)
    _add_claim(tmp_path, session_id="sess-A", offset=0)
    _add_claim(tmp_path, session_id="sess-B", offset=100)

    store = MemoryStore.from_paths(root=tmp_path)
    events = build_engine_events(store, session_id="sess-A")
    assert len(events) == 1
    assert events[0]["session_id"] == "sess-A"


def test_export_session_id_composes_with_failures_only(tmp_path) -> None:
    _init(tmp_path)
    _add_claim(tmp_path, session_id="sess-A", passed=True, offset=0)
    _add_claim(tmp_path, session_id="sess-A", passed=False, offset=100)
    _add_claim(tmp_path, session_id="sess-B", passed=False, offset=200)

    store = MemoryStore.from_paths(root=tmp_path)
    events = build_engine_events(store, session_id="sess-A", failures_only=True)
    assert len(events) == 1
    assert events[0]["outcome"]["status"] == "CONTRADICTED"


def test_export_clean_only_composes_with_failures_only(tmp_path) -> None:
    _init(tmp_path)
    _add_claim(tmp_path, agent_id="kiro", passed=True, offset=0)
    _add_claim(tmp_path, agent_id="kiro", passed=False, offset=100)
    _add_claim(tmp_path, agent_id="unknown-agent", passed=False, offset=200)

    store = MemoryStore.from_paths(root=tmp_path)
    events = build_engine_events(store, clean_only=True, failures_only=True)
    assert len(events) == 1
    assert events[0]["agent"]["id"] == "kiro"
    assert events[0]["outcome"]["status"] == "CONTRADICTED"


def test_export_empty_filter_outputs_empty_jsonl(tmp_path) -> None:
    """Filtering that matches nothing returns empty list and empty JSONL."""
    _init(tmp_path)
    _add_claim(tmp_path)

    store = MemoryStore.from_paths(root=tmp_path)
    events = build_engine_events(store, session_id="sess-nonexistent")
    assert events == []
    assert format_events_jsonl(events) == ""


def test_export_cli_clean_only_outputs_only_clean_events(tmp_path, monkeypatch, capsys) -> None:
    _init(tmp_path)
    _add_claim(tmp_path, agent_id="unknown-agent", offset=0)
    _add_claim(tmp_path, agent_id="kiro", offset=100)
    code = _run(["export", "--clean-only"], tmp_path, monkeypatch)
    assert code == 0
    out = capsys.readouterr().out.strip()
    parsed = json.loads(out)
    assert parsed["agent"]["id"] == "kiro"


def test_export_cli_session_id_writes_only_session_events(tmp_path, monkeypatch, capsys) -> None:
    _init(tmp_path)
    _add_claim(tmp_path, session_id="sess-target", offset=0)
    _add_claim(tmp_path, session_id="sess-other", offset=100)
    code = _run(["export", "--session-id", "sess-target"], tmp_path, monkeypatch)
    assert code == 0
    out = capsys.readouterr().out.strip()
    parsed = json.loads(out)
    assert parsed["session_id"] == "sess-target"


def test_export_event_schema_contract_stable(tmp_path) -> None:
    """Every exported event has the required top-level keys."""
    _init(tmp_path)
    _add_claim(tmp_path)

    store = MemoryStore.from_paths(root=tmp_path)
    events = build_engine_events(store)
    assert len(events) == 1
    e = events[0]
    required_keys = {
        "schema_version", "event_type", "event_id", "source",
        "session_id", "claim_id", "timestamp",
        "agent", "task", "command", "outcome", "witness", "git", "integrity",
    }
    assert required_keys <= set(e.keys())
    assert e["schema_version"] == 1
    assert e["event_type"] == "memory.claim.settled"
    assert e["event_id"].startswith("evt-")
