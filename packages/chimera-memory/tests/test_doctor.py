"""Tests for chimera-memory doctor subcommand."""

from __future__ import annotations

import json

import pytest

from chimera_memory.cli import main


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()  # init now requires a git repo
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _init():
    main(["init"])


# ---------------------------------------------------------------------------
# Doctor on uninitialized dir
# ---------------------------------------------------------------------------


def test_doctor_uninitialized_exits_critical(tmp_path):
    result = main(["doctor"])
    assert result == 2, f"expected exit 2 on uninitialized dir, got {result}"


def test_doctor_does_not_create_memory_dir(tmp_path):
    main(["doctor"])
    assert not (tmp_path / ".chimera-memory").exists()


def test_doctor_uninitialized_json_has_critical(tmp_path, capsys):
    capsys.readouterr()  # clear any prior output
    main(["doctor", "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    assert d["overall_status"] == "critical"
    assert d["exit_code"] == 2
    assert "not initialized" in d["critical"][0]


# ---------------------------------------------------------------------------
# Doctor on initialized store
# ---------------------------------------------------------------------------


def test_doctor_initialized_exits_warning_no_session(tmp_path):
    _init()
    result = main(["doctor"])
    assert result == 1  # warning: no active session


def test_doctor_no_session_json_has_warning(tmp_path, capsys):
    _init()
    capsys.readouterr()
    main(["doctor", "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    assert "no active session" in " ".join(d["warnings"])


def test_doctor_legacy_unsigned_not_critical(tmp_path):
    _init()
    result = main(["doctor"])
    assert result != 2, "LEGACY_UNSIGNED with 0 broken must not be exit 2"


def test_doctor_json_stable_keys(tmp_path, capsys):
    _init()
    capsys.readouterr()
    main(["doctor", "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    for key in ("schema_version", "overall_status", "exit_code", "checks",
                "counts", "next_steps", "warnings", "critical"):
        assert key in d, f"missing key: {key}"


def test_doctor_json_counts_m2b_level(tmp_path, capsys):
    _init()
    capsys.readouterr()
    main(["doctor", "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    assert "m2b_readiness_level" in d["counts"]


# ---------------------------------------------------------------------------
# Doctor .gitignore check
# ---------------------------------------------------------------------------


def test_doctor_warns_when_gitignore_missing_entry(tmp_path, capsys):
    _init()
    (tmp_path / ".gitignore").write_text("*.pyc\n")
    capsys.readouterr()
    main(["doctor", "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    assert any(".gitignore" in w for w in d["warnings"])


def test_doctor_ok_when_gitignore_has_entry(tmp_path, capsys):
    _init()  # init adds .gitignore
    capsys.readouterr()
    main(["doctor", "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    assert not any(".gitignore" in w for w in d["warnings"])


def test_doctor_does_not_count_unsettled_as_failure(tmp_path, capsys):
    """Doctor organic_real failure count must not include unsettled records."""
    _init()
    # Record-only (no settle): write a raw claim file manually
    import json as _json
    claims_file = tmp_path / ".chimera-memory" / "claims.jsonl"
    raw = {"claim_id": "fake-unsettled-00000000", "predicted": True,
           "failure_origin": "organic_real", "title": "unsettled",
           "summary": "", "evidence": [], "confidence": None,
           "agent_id": "test", "model_version": "test",
           "claim_time": "2026-01-01T00:00:00+00:00"}
    with claims_file.open("a") as f:
        f.write(_json.dumps(raw) + "\n")
    capsys.readouterr()
    main(["doctor", "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    # The raw unsettled claim must not inflate organic_real_failures
    assert d["counts"]["organic_real_failures"] == 0
