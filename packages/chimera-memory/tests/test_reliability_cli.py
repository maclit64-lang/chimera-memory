"""M2A: CLI tests for chimera-memory reliability command."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from chimera_memory_types.finding import EvidenceRefType

from chimera_memory.cli import main
from chimera_memory.ledger import record_claim, settle_claim
from chimera_memory.storage import MemoryStore


def _init(tmp_path: Path) -> MemoryStore:
    store = MemoryStore.from_paths(root=tmp_path)
    store.initialize()
    return store


def _ev(t: datetime) -> dict:
    return {"ref_type": EvidenceRefType.EXTERNAL, "ref_id": "git:abc", "available_at": t}


def _add(tmp_path: Path, *, passed: bool = True, agent_id: str = "kiro",
         model_version: str = "v1", task_type: str = "test", offset: int = 0) -> None:
    t0 = datetime(2026, 6, 1, 12, tzinfo=UTC) + timedelta(seconds=offset)
    t1 = t0 + timedelta(seconds=5)
    cid = record_claim(
        title="t", summary="s", predicted=True, evidence=[_ev(t0)],
        root=tmp_path, claim_time=t0,
        agent_id=agent_id, model_version=model_version, task_type=task_type,
        extra_metadata={"session_id": "s1", "attribution_confidence": "high",
                        "identity_source": "cli_flag"},
    )
    settle_claim(cid, passed, t1, root=tmp_path,
                 event_metadata={"exit_code": 0 if passed else 1, "wrapped_args": ["pytest"]})


def test_reliability_cli_outputs_text_summary(tmp_path, monkeypatch, capsys) -> None:
    _init(tmp_path)
    _add(tmp_path, passed=True, offset=0)
    _add(tmp_path, passed=False, offset=10)
    monkeypatch.chdir(tmp_path)
    code = main(["reliability"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Chimera Memory Reliability" in out
    assert "kiro" in out
    assert "validated=" in out


def test_reliability_cli_json_outputs_parseable_contract(tmp_path, monkeypatch, capsys) -> None:
    _init(tmp_path)
    _add(tmp_path, passed=True, offset=0)
    monkeypatch.chdir(tmp_path)
    code = main(["reliability", "--json"])
    assert code == 0
    out = capsys.readouterr().out
    d = json.loads(out)
    for key in ("clean_claims", "groups_total", "failures_total",
                "by_agent_model_task", "notes"):
        assert key in d
    assert d["notes"]["read_only"] is True
    assert d["notes"]["no_routing"] is True
    assert d["notes"]["no_model_ranking"] is True


def test_reliability_cli_help_explains_read_only_raw_rates(capsys) -> None:
    try:
        main(["--help"])
    except SystemExit:
        pass
    out = capsys.readouterr().out
    # Top-level help shows the reliability subcommand description
    assert "reliability" in out
    assert "read-only" in out.lower() or "raw" in out.lower() or "ranking" in out.lower()


def test_reliability_cli_warns_not_model_ranking(tmp_path, monkeypatch, capsys) -> None:
    _init(tmp_path)
    _add(tmp_path, offset=0)
    monkeypatch.chdir(tmp_path)
    main(["reliability"])
    out = capsys.readouterr().out
    assert "rank" in out.lower() or "Warning" in out or "routing" in out.lower()
