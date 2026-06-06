"""C4-lite: tests for chimera-memory status command (build_dogfood_status)."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from chimera_memory_types.finding import EvidenceRefType

from chimera_memory.cli import main
from chimera_memory.ledger import build_dogfood_status, record_claim, settle_claim
from chimera_memory.storage import MemoryStore

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ev(t: datetime) -> dict:
    return {"ref_type": EvidenceRefType.EXTERNAL, "ref_id": "git:abc", "available_at": t}


def _add_clean_claim(
    root: Path,
    *,
    agent_id: str = "kiro",
    model_version: str = "claude-sonnet-4.6",
    task_type: str = "test",
    session_id: str = "sess-test-001",
    attribution_confidence: str = "high",
    identity_source: str = "cli_flag",
    passed: bool = True,
    offset_seconds: int = 0,
) -> str:
    t0 = datetime(2026, 6, 1, 12, tzinfo=UTC) + timedelta(seconds=offset_seconds)
    t1 = t0 + timedelta(seconds=10)
    cid = record_claim(
        title="claim",
        summary="s",
        predicted=True,
        evidence=[_ev(t0)],
        root=root,
        claim_time=t0,
        agent_id=agent_id,
        model_version=model_version,
        task_type=task_type,
        extra_metadata={
            "session_id": session_id,
            "attribution_confidence": attribution_confidence,
            "identity_source": identity_source,
        },
    )
    settle_claim(cid, passed, t1, root=root)
    return cid


def _init(tmp_path: Path) -> None:
    MemoryStore.from_paths(root=tmp_path).initialize()


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


def test_status_command_counts_unique_clean_claims(tmp_path) -> None:
    _init(tmp_path)
    _add_clean_claim(tmp_path, offset_seconds=0)
    _add_clean_claim(tmp_path, offset_seconds=100)

    s = build_dogfood_status(root=tmp_path)
    assert s["clean_unique_claims"] == 2
    assert s["unique_claims"] == 2
    assert s["raw_records"] == 4  # 2 proposed + 2 validated


def test_status_command_excludes_bad_attribution_claims(tmp_path) -> None:
    _init(tmp_path)
    # 1 clean claim
    _add_clean_claim(tmp_path, offset_seconds=0)
    # unknown-agent claim
    _add_clean_claim(tmp_path, agent_id="unknown-agent", offset_seconds=100)
    # null model claim (model_version omitted → None in metadata)
    t0 = datetime(2026, 6, 1, 14, tzinfo=UTC)
    t1 = t0 + timedelta(seconds=10)
    cid = record_claim(
        title="c", summary="s", predicted=True, evidence=[_ev(t0)],
        root=tmp_path, claim_time=t0, agent_id="kiro", model_version=None,
        task_type="test",
        extra_metadata={"session_id": "s1", "attribution_confidence": "high",
                        "identity_source": "cli_flag"},
    )
    settle_claim(cid, True, t1, root=tmp_path)

    s = build_dogfood_status(root=tmp_path)
    assert s["clean_unique_claims"] == 1
    assert s["excluded"]["unknown_agent"] == 1
    assert s["excluded"]["model_version_null"] == 1


def test_status_command_reports_segments_by_agent_model_harness_task(tmp_path) -> None:
    _init(tmp_path)
    _add_clean_claim(tmp_path, agent_id="kiro", task_type="test", offset_seconds=0)
    _add_clean_claim(tmp_path, agent_id="kiro", task_type="docs", offset_seconds=100)
    _add_clean_claim(tmp_path, agent_id="planning-agent", model_version="unknown",
                     task_type="planning", offset_seconds=200)

    s = build_dogfood_status(root=tmp_path)
    assert s["segments"]["agent_id"]["kiro"] == 2
    assert s["segments"]["agent_id"]["planning-agent"] == 1
    assert s["segments"]["task_type"]["test"] == 1
    assert s["segments"]["task_type"]["docs"] == 1
    assert s["segments"]["task_type"]["planning"] == 1
    assert s["segments"]["model_version"]["claude-sonnet-4.6"] == 2
    assert s["segments"]["model_version"]["unknown"] == 1


def test_status_json_flag_produces_parseable_output(tmp_path, monkeypatch, capsys) -> None:
    _init(tmp_path)
    _add_clean_claim(tmp_path)
    monkeypatch.chdir(tmp_path)
    code = main(["status", "--json"])
    assert code == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert "clean_unique_claims" in parsed
    assert "progress" in parsed
    assert "excluded" in parsed
    assert "segments" in parsed
    assert "comparison_gate" in parsed
    assert isinstance(parsed["m2_ready"], bool)


def test_status_reports_progress_toward_30_gate(tmp_path) -> None:
    _init(tmp_path)
    for i in range(5):
        _add_clean_claim(tmp_path, offset_seconds=i * 100)

    s = build_dogfood_status(root=tmp_path, gate_target=30)
    assert s["progress"]["current"] == 5
    assert s["progress"]["target"] == 30
    assert s["progress"]["met"] is False

    s2 = build_dogfood_status(root=tmp_path, gate_target=5)
    assert s2["progress"]["met"] is True


def test_status_does_not_double_count_proposed_and_validated_records(tmp_path) -> None:
    _init(tmp_path)
    _add_clean_claim(tmp_path, offset_seconds=0)  # creates 2 raw records (proposed + validated)

    s = build_dogfood_status(root=tmp_path)
    assert s["raw_records"] == 2  # 2 store records
    assert s["unique_claims"] == 1  # but 1 unique claim
    assert s["clean_unique_claims"] == 1  # and 1 clean claim


# =============================================================================
# E3 — status JSON + legacy compatibility contract tests
# =============================================================================


def test_status_json_contract_keys_are_stable(tmp_path, monkeypatch, capsys) -> None:
    """status --json top-level keys are stable for downstream tooling."""
    _init(tmp_path)
    _add_clean_claim(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["status", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    expected_top_level = {
        "raw_records", "unique_claims", "settled_unique_claims", "clean_unique_claims",
        "progress", "excluded", "segments", "comparison_gate", "m2_ready", "reason",
    }
    assert expected_top_level <= set(out.keys())


def test_status_json_progress_contract_is_stable(tmp_path, monkeypatch, capsys) -> None:
    """progress sub-dict has stable keys and correct invariants."""
    _init(tmp_path)
    for i in range(3):
        _add_clean_claim(tmp_path, offset_seconds=i * 100)
    monkeypatch.chdir(tmp_path)
    assert main(["status", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    prog = out["progress"]
    assert set(prog.keys()) >= {"current", "target", "met"}
    assert prog["target"] == 30
    assert prog["current"] == out["clean_unique_claims"]
    assert prog["met"] == (out["clean_unique_claims"] >= 30)


def test_status_json_excluded_contract_is_stable(tmp_path, monkeypatch, capsys) -> None:
    """excluded sub-dict has stable keys covering all D0 §9 exclusion reasons."""
    _init(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["status", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    expected_excl_keys = {
        "missing_session_id", "unknown_agent", "model_version_null",
        "missing_task_type", "missing_attribution_confidence",
        "missing_identity_source", "unsettled",
    }
    assert expected_excl_keys == set(out["excluded"].keys())


def test_status_handles_legacy_pre_c1_unknown_agent_records(tmp_path) -> None:
    """Legacy pre-C1 records are readable, counted, but excluded from clean claims."""
    _init(tmp_path)
    # Simulate a pre-C1 claim: session_id + task_type present, but no attribution
    t0 = datetime(2026, 6, 1, 12, tzinfo=UTC)
    t1 = t0 + timedelta(seconds=10)
    cid = record_claim(
        title="legacy", summary="s", predicted=True, evidence=[_ev(t0)],
        root=tmp_path, claim_time=t0,
        agent_id="unknown-agent",
        model_version=None,
        task_type="test",
        extra_metadata={"session_id": "sess-pre-c1-001"},
        # no attribution_confidence, no identity_source (pre-C1 shape)
    )
    settle_claim(cid, True, t1, root=tmp_path)

    s = build_dogfood_status(root=tmp_path)

    assert s["raw_records"] == 2        # proposed + validated
    assert s["unique_claims"] == 1
    assert s["settled_unique_claims"] == 1
    assert s["clean_unique_claims"] == 0  # excluded
    assert s["excluded"]["unknown_agent"] == 1
    assert s["excluded"]["model_version_null"] == 1
    assert s["excluded"]["missing_attribution_confidence"] == 1
    assert s["excluded"]["missing_identity_source"] == 1
    assert s["progress"]["current"] == 0


def test_status_allows_missing_harness_id_for_clean_claims(tmp_path) -> None:
    """harness_id is not required by D0 §9 clean-claim rules. Claims without it still count."""
    _init(tmp_path)
    # Clean claim but with no harness_id in extra_metadata (pre-C2 style)
    t0 = datetime(2026, 6, 1, 12, tzinfo=UTC)
    t1 = t0 + timedelta(seconds=10)
    cid = record_claim(
        title="pre-c2", summary="s", predicted=True, evidence=[_ev(t0)],
        root=tmp_path, claim_time=t0,
        agent_id="kiro", model_version="claude-sonnet-4.6", task_type="test",
        extra_metadata={
            "session_id": "sess-pre-c2-001",
            "attribution_confidence": "high",
            "identity_source": "cli_flag",
            # harness_id intentionally absent
        },
    )
    settle_claim(cid, True, t1, root=tmp_path)

    s = build_dogfood_status(root=tmp_path)
    assert s["clean_unique_claims"] == 1
    assert s["segments"]["harness_id"].get("None", 0) == 1  # none key present


def test_status_json_comparison_gate_contract_is_stable(tmp_path, monkeypatch, capsys) -> None:
    """comparison_gate has stable entries for all four comparison dimensions."""
    _init(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["status", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    cg = out["comparison_gate"]
    assert set(cg.keys()) == {"agent_id", "model_version", "harness_id", "task_type"}
    for dim_val in cg.values():
        assert isinstance(dim_val, dict)


# =============================================================================
# I2B tests — integrity in status
# =============================================================================


def test_status_text_includes_integrity_summary(tmp_path, monkeypatch, capsys) -> None:
    """status text output includes an Integrity block."""
    _init(tmp_path)
    _add_clean_claim(tmp_path)
    monkeypatch.chdir(tmp_path)
    code = main(["status"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Integrity:" in out
    assert "Chained records:" in out


def test_status_json_includes_integrity_contract(tmp_path, monkeypatch, capsys) -> None:
    """status --json includes 'integrity' key with required fields."""
    _init(tmp_path)
    _add_clean_claim(tmp_path)
    monkeypatch.chdir(tmp_path)
    code = main(["status", "--json"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert "integrity" in out
    integ = out["integrity"]
    for key in ("status", "chained_records", "broken_records", "unsigned_gaps", "errors_count"):
        assert key in integ


def test_status_integrity_does_not_change_clean_claim_counts(tmp_path, monkeypatch) -> None:
    """Adding integrity to status output does not affect clean-claim counts."""
    _init(tmp_path)
    for i in range(3):
        _add_clean_claim(tmp_path, offset_seconds=i * 100)
    s = build_dogfood_status(root=tmp_path)
    assert s["clean_unique_claims"] == 3  # integrity field does not affect counting
    assert "integrity" in s
