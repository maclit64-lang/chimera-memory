"""I2A: CLI tests for chimera-memory verify command."""
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


def _add_claim(tmp_path: Path, offset: int = 0) -> str:
    t0 = datetime(2026, 6, 1, 12, tzinfo=UTC) + timedelta(seconds=offset)
    t1 = t0 + timedelta(seconds=5)
    cid = record_claim(
        title="test claim", summary="s", predicted=True, evidence=[_ev(t0)],
        root=tmp_path, claim_time=t0, agent_id="kiro",
        model_version="claude-sonnet-4.6", task_type="test",
    )
    settle_claim(cid, True, t1, root=tmp_path)
    return cid


def _run(argv: list[str], tmp_path: Path, monkeypatch) -> int:
    monkeypatch.chdir(tmp_path)
    return main(argv)


def test_verify_command_reports_ok(tmp_path, monkeypatch, capsys) -> None:
    _init(tmp_path)
    _add_claim(tmp_path)
    code = _run(["verify"], tmp_path, monkeypatch)
    assert code == 0
    out = capsys.readouterr().out
    assert "Status:" in out
    assert "Broken records:  0" in out


def test_verify_command_reports_legacy_unsigned(tmp_path, monkeypatch, capsys) -> None:
    _init(tmp_path)
    claims_path = tmp_path / ".chimera-memory" / "claims.jsonl"
    claims_path.write_text('{"claim_id": "old"}\n', encoding="utf-8")
    code = _run(["verify"], tmp_path, monkeypatch)
    assert code == 0  # LEGACY_UNSIGNED exits 0
    out = capsys.readouterr().out
    assert "LEGACY_UNSIGNED" in out


def test_verify_command_json_is_parseable(tmp_path, monkeypatch, capsys) -> None:
    _init(tmp_path)
    _add_claim(tmp_path)
    code = _run(["verify", "--json"], tmp_path, monkeypatch)
    assert code == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert "status" in parsed
    assert "broken_records" in parsed
    assert "errors" in parsed


def test_verify_command_exits_nonzero_on_broken_chain(tmp_path, monkeypatch) -> None:
    _init(tmp_path)
    _add_claim(tmp_path)
    claims_path = tmp_path / ".chimera-memory" / "claims.jsonl"
    text = claims_path.read_text(encoding="utf-8")
    claims_path.write_text(text.replace('"title":', '"TAMPERED":'), encoding="utf-8")
    code = _run(["verify"], tmp_path, monkeypatch)
    assert code == 1
