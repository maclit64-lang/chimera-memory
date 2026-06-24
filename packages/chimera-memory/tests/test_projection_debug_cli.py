"""Stage 1C: read-only projection debug CLI tests.

Exercises `chimera-memory evidence-events` and `chimera-memory settled-claims`
through cli.main(...), asserting the JSON contract, read-only behavior, graceful
handling of empty/nonexistent stores, absence of overclaim language, and that
existing commands still respond.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from chimera_memory.cli import main

_FORBIDDEN = (
    "safe to merge",
    "production ready",
    "production-ready",
    "certified",
    "approved",
    "guaranteed",
    "proves correctness",
    "proves safety",
)

_EVENT_KEYS = {
    "schema_version", "event_id", "event_kind", "source", "record_ref",
    "raw_record_type", "raw_record_hash", "timestamp", "claim_id",
    "session_id", "evidence_id", "status", "exit_code", "summary",
}
_CLAIM_KEYS = {
    "schema_version", "claim_id", "latest_status", "event_count",
    "opened_event_ids", "settlement_event_ids", "score_event_ids",
    "session_event_ids", "event_ids", "first_timestamp", "last_timestamp",
    "latest_exit_code", "summary", "has_claim_record",
    "has_settlement_record", "has_score_record",
}


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")


def _seed(root: Path) -> Path:
    """Seed a tiny store; return its .chimera-memory dir."""
    mem = root / ".chimera-memory"
    _write_jsonl(mem / "claims.jsonl", [
        {"claim_id": "c1", "claim_status": "proposed", "title": "cmd will pass",
         "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
         "metadata": {"session_id": "s1"}},
        {"claim_id": "c1", "claim_status": "validated", "title": "cmd will pass",
         "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:05Z",
         "metadata": {"session_id": "s1"}},
    ])
    _write_jsonl(mem / "outcomes.jsonl", [
        {"claim_id": "c1", "event_key": "c1:k", "observed_at": "2026-01-01T00:00:05Z",
         "outcome": {"observed": True}, "metadata": {"exit_code": 0}},
    ])
    _write_jsonl(mem / "scores.jsonl", [
        {"record_id": "r1", "claim_id": "c1", "created_at": "2026-01-01T00:00:06Z",
         "settlement": {"status": "validated"}},
    ])
    _write_jsonl(mem / "sessions.jsonl", [
        {"event": "start", "session": {"session_id": "s1", "started_at": "2026-01-01T00:00:00Z",
                                       "ended_at": None, "final_status": None}},
        {"event": "end", "session": {"session_id": "s1", "started_at": "2026-01-01T00:00:00Z",
                                     "ended_at": "2026-01-01T00:00:07Z", "final_status": "passed"}},
    ])
    return mem


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


def test_evidence_events_json_contract(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = _seed(tmp_path)
    code, out = _run(capsys, "evidence-events", "--json", "--memory-dir", str(mem))
    assert code == 0
    data = json.loads(out)
    assert data["schema_version"] == 1
    assert isinstance(data["events"], list)
    assert len(data["events"]) == 6
    assert set(data["events"][0]) == _EVENT_KEYS


def test_settled_claims_json_contract(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = _seed(tmp_path)
    code, out = _run(capsys, "settled-claims", "--json", "--memory-dir", str(mem))
    assert code == 0
    data = json.loads(out)
    assert data["schema_version"] == 1
    assert isinstance(data["settled_claims"], list)
    assert len(data["settled_claims"]) == 1
    claim = data["settled_claims"][0]
    assert set(claim) == _CLAIM_KEYS
    assert claim["claim_id"] == "c1"
    assert claim["latest_status"] == "validated"
    assert len(claim["opened_event_ids"]) == 2  # lifecycle folded


def test_empty_store_returns_empty_arrays(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = tmp_path / ".chimera-memory"
    mem.mkdir()
    _, out_e = _run(capsys, "evidence-events", "--json", "--memory-dir", str(mem))
    assert json.loads(out_e) == {"schema_version": 1, "events": []}
    _, out_s = _run(capsys, "settled-claims", "--json", "--memory-dir", str(mem))
    assert json.loads(out_s) == {"schema_version": 1, "settled_claims": []}


def test_command_is_read_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = _seed(tmp_path)
    before = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    _run(capsys, "evidence-events", "--json", "--memory-dir", str(mem))
    _run(capsys, "settled-claims", "--json", "--memory-dir", str(mem))
    after = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    assert before == after


def test_nonexistent_store_is_graceful_and_non_mutating(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nope" / ".chimera-memory"
    code, out = _run(capsys, "evidence-events", "--json", "--memory-dir", str(missing))
    assert code == 0
    assert json.loads(out) == {"schema_version": 1, "events": []}
    code, out = _run(capsys, "settled-claims", "--json", "--memory-dir", str(missing))
    assert code == 0
    assert json.loads(out) == {"schema_version": 1, "settled_claims": []}
    assert not missing.exists()  # nothing was created


def test_no_forbidden_overclaim_phrases(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = _seed(tmp_path)
    blob = ""
    _, out = _run(capsys, "evidence-events", "--json", "--memory-dir", str(mem))
    blob += out
    _, out = _run(capsys, "settled-claims", "--json", "--memory-dir", str(mem))
    blob += out
    for cmd in ("evidence-events", "settled-claims"):
        _, help_out = _run(capsys, cmd, "--help")
        blob += help_out
    low = blob.lower()
    for phrase in _FORBIDDEN:
        assert phrase not in low, f"overclaim phrase leaked: {phrase!r}"


def test_non_json_output_is_terse_and_read_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = _seed(tmp_path)
    code, out = _run(capsys, "evidence-events", "--memory-dir", str(mem))
    assert code == 0
    assert "read-only" in out.lower()
    assert out.strip().startswith("6 ")


def test_existing_cli_commands_still_respond(capsys: pytest.CaptureFixture[str]) -> None:
    # The new commands must not have broken parsing/dispatch for existing ones.
    code, out = _run(capsys, "--version")
    assert code == 0
    assert "chimera-memory" in out
    code, _ = _run(capsys, "proof-debt", "--help")
    assert code == 0
