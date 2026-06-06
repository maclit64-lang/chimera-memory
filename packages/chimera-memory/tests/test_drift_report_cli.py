from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from chimera_memory.cli import main
from chimera_memory.drift import detect_drift
from chimera_memory.ledger import export_report, record_claim, settle_claim

BASE_TIME = datetime(2026, 6, 2, 12, tzinfo=UTC)


def _record_settled(
    root: Path,
    index: int,
    *,
    model_version: str = "model-a",
    agent_id: str = "agent-4",
    task_type: str = "coding",
    confidence: float | None = 0.9,
    observed: bool = True,
) -> str:
    claim_time = BASE_TIME + timedelta(minutes=index * 2)
    outcome_time = claim_time + timedelta(minutes=1)
    claim_id = record_claim(
        title=f"claim {index}",
        summary="Drift fixture claim.",
        predicted=True,
        evidence=[
            {
                "ref_type": "external",
                "ref_id": f"fixture:{index}",
                "available_at": claim_time,
            }
        ],
        root=root,
        claim_time=claim_time,
        outcome_time=outcome_time,
        confidence=confidence,
        agent_id=agent_id,
        model_version=model_version,
        task_type=task_type,
    )
    settle_claim(claim_id, observed, outcome_time, root=root)
    return claim_id


def test_drift_insufficient_data_below_min(tmp_path) -> None:
    for index in range(5):
        _record_settled(tmp_path, index, model_version="model-sparse")

    result = detect_drift(root=tmp_path, by="model_version")
    group = result["groups"][0]

    assert group["status"] == "INSUFFICIENT_DATA"
    assert group["settled_count"] == 5


def test_drift_fires_on_planted_score_shift(tmp_path) -> None:
    for index in range(15):
        _record_settled(tmp_path, index, model_version="model-shift", confidence=0.9, observed=True)
    for index in range(15, 30):
        _record_settled(tmp_path, index, model_version="model-shift", confidence=0.9, observed=False)

    result = detect_drift(root=tmp_path, by="model_version")
    group = result["groups"][0]

    assert group["status"] == "DRIFT_ADVISORY"
    assert group["score_shift"] > 0
    assert "advisory only" in group["message"]
    assert "not statistical proof" in group["message"]


def test_drift_ok_without_shift(tmp_path) -> None:
    for index in range(30):
        _record_settled(tmp_path, index, model_version="model-ok", confidence=0.9, observed=True)

    result = detect_drift(root=tmp_path, by="model_version")
    group = result["groups"][0]

    assert group["status"] == "OK"
    assert group["score_shift"] == pytest.approx(0.0)


def test_overconfidence_only_when_confidence_present(tmp_path) -> None:
    _record_settled(
        tmp_path,
        0,
        model_version="model-conf",
        agent_id="agent-conf",
        confidence=0.9,
        observed=False,
    )
    _record_settled(
        tmp_path,
        1,
        model_version="model-none",
        agent_id="agent-none",
        confidence=None,
        observed=True,
    )

    report = export_report(root=tmp_path)
    groups = {group["group"]["agent_id"]: group for group in report["groups"]}
    claim = next(claim for claim in detect_drift(root=tmp_path)["groups"])

    assert groups["agent-conf"]["overconfidence"] == pytest.approx(0.9)
    assert groups["agent-none"]["overconfidence"] is None
    assert claim


def test_report_cli_prints_local_reliability_report(monkeypatch, tmp_path, capsys) -> None:
    _record_settled(tmp_path, 0, agent_id="agent-4", model_version="model-a", task_type="coding")
    monkeypatch.chdir(tmp_path)

    assert main(["report", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["groups"][0]["group"] == {
        "agent_id": "agent-4",
        "model_version": "model-a",
        "task_type": "coding",
    }
    output = json.dumps(payload).lower()
    assert "dashboard" not in output
    assert "html" not in output
    assert "cloud" not in output


def test_drift_cli_prints_insufficient_data(monkeypatch, tmp_path, capsys) -> None:
    _record_settled(tmp_path, 0, model_version="model-sparse")
    monkeypatch.chdir(tmp_path)

    assert main(["drift", "--by", "model_version"]) == 0

    assert "INSUFFICIENT_DATA" in capsys.readouterr().out


def test_drift_cli_json(monkeypatch, tmp_path, capsys) -> None:
    _record_settled(tmp_path, 0, model_version="model-json")
    monkeypatch.chdir(tmp_path)

    assert main(["drift", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["groups"][0]["group"] == "model-json"
    assert payload["groups"][0]["status"] == "INSUFFICIENT_DATA"


def test_no_proof_claim_language() -> None:
    drift_text = Path("packages/chimera-memory/src/chimera_memory/drift.py").read_text()
    assert "not statistical proof" in drift_text
    forbidden = [
        "proved",
        "p-value",
        "significant",
        "martingale",
        "e-value",
        "evalue",
        "anytime",
        "finance",
        "replay",
        "preflight",
        "causal",
        "warrant",
    ]
    for token in forbidden:
        assert token not in drift_text

    tree = ast.parse(drift_text)
    assert tree


def test_report_includes_status_note_for_gate_progress(monkeypatch, tmp_path, capsys) -> None:
    """Plain report output includes a note pointing to chimera-memory status."""
    _record_settled(tmp_path, 0)
    monkeypatch.chdir(tmp_path)

    assert main(["report"]) == 0
    out = capsys.readouterr().out
    assert "chimera-memory status" in out
    assert "dogfood gate progress" in out.lower() or "clean-claim" in out.lower()


def test_report_does_not_double_count_proposed_and_settled_records(
    monkeypatch, tmp_path, capsys
) -> None:
    """chimera-memory report uses latest_claims() so proposed+validated records
    for the same claim are not double-counted."""
    _record_settled(tmp_path, 0)  # produces 2 raw records, 1 unique claim

    monkeypatch.chdir(tmp_path)
    assert main(["report", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    # There should be exactly 1 group with count=1 (not count=2)
    groups = payload["groups"]
    assert len(groups) == 1
    assert groups[0]["count"] == 1


def test_report_output_still_mentions_status_note(monkeypatch, tmp_path, capsys) -> None:
    """Plain report output includes the pointer to chimera-memory status."""
    _record_settled(tmp_path, 0)
    monkeypatch.chdir(tmp_path)
    assert main(["report"]) == 0
    out = capsys.readouterr().out
    assert "chimera-memory status" in out
