"""Tests for v0.8 doctor evidence hygiene + preflight empty-ledger guidance."""
from __future__ import annotations

import json
from pathlib import Path


from chimera_memory.cli import _build_evidence_hygiene, _build_next_actions, main
from chimera_memory.storage import MemoryStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup(tmp_path: Path, monkeypatch) -> None:
    """Init store and start a session in tmp_path."""
    monkeypatch.chdir(tmp_path)
    main(["init"])
    main(["session", "start", "--branch", "t", "--task-label", "t",
          "--agent", "a", "--model", "m", "--harness-id", "h"])


def _wrap(scope: str | None = None, failure_origin: str | None = None,
          exit_code: int = 0,
          repair_loop_id: str | None = None,
          repair_phase: str | None = None) -> None:
    """Wrap a trivial command to produce one settled claim."""
    args = ["wrap"]
    if scope:
        args += ["--scope-path", scope]
    if failure_origin:
        args += ["--failure-origin", failure_origin]
    args += ["--verification-scope", "package"]
    if repair_loop_id:
        args += ["--repair-loop-id", repair_loop_id]
    if repair_phase:
        args += ["--repair-phase", repair_phase]
    args += ["--", "python3", "-c", f"import sys; sys.exit({exit_code})"]
    main(args)


# ---------------------------------------------------------------------------
# _build_evidence_hygiene unit tests
# ---------------------------------------------------------------------------

def test_hygiene_all_scoped_and_known_origin(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _wrap(scope=str(tmp_path), failure_origin="organic_real")
    _wrap(scope=str(tmp_path), failure_origin="controlled_real")
    store = MemoryStore.from_paths(root=tmp_path)
    h = _build_evidence_hygiene(store)
    assert h["total_claims"] == 2
    assert h["scoped_claim_count"] == 2
    assert h["unscoped_claim_count"] == 0
    assert h["unknown_failure_origin_count"] == 0
    assert h["scoped_claim_ratio"] == 1.0


def test_hygiene_detects_unscoped_claims(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _wrap(scope=str(tmp_path), failure_origin="organic_real")
    _wrap(scope=None, failure_origin="organic_real")  # unscoped
    store = MemoryStore.from_paths(root=tmp_path)
    h = _build_evidence_hygiene(store)
    assert h["unscoped_claim_count"] == 1
    assert h["scoped_claim_count"] == 1


def test_hygiene_detects_unknown_failure_origin(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    # No --failure-origin → missing → unknown
    _wrap(scope=str(tmp_path), failure_origin=None)
    _wrap(scope=str(tmp_path), failure_origin=None)
    _wrap(scope=str(tmp_path), failure_origin="organic_real")
    store = MemoryStore.from_paths(root=tmp_path)
    h = _build_evidence_hygiene(store)
    assert h["unknown_failure_origin_count"] == 2


def test_hygiene_detects_repair_phase_without_loop(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    # repair_phase without repair_loop_id
    _wrap(scope=str(tmp_path), failure_origin="organic_real",
          repair_phase="baseline", repair_loop_id=None)
    # repair_phase WITH repair_loop_id (not an orphan)
    _wrap(scope=str(tmp_path), failure_origin="organic_real",
          repair_phase="baseline", repair_loop_id="loop-1")
    store = MemoryStore.from_paths(root=tmp_path)
    h = _build_evidence_hygiene(store)
    assert h["repair_phase_without_loop_count"] == 1


def test_hygiene_detects_open_repair_loop(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    # baseline contradiction only — no same_scope_after_fix
    _wrap(scope=str(tmp_path), failure_origin="organic_real",
          exit_code=1, repair_loop_id="loop-open", repair_phase="baseline")
    store = MemoryStore.from_paths(root=tmp_path)
    h = _build_evidence_hygiene(store)
    assert h["open_repair_loop_count"] == 1
    assert "loop-open" in list(h["open_repair_loop_ids"])
    assert h["complete_repair_loop_count"] == 0


def test_hygiene_detects_complete_repair_loop(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _wrap(scope=str(tmp_path), failure_origin="organic_real",
          exit_code=1, repair_loop_id="loop-done", repair_phase="baseline")
    _wrap(scope=str(tmp_path), failure_origin="organic_real",
          exit_code=0, repair_loop_id="loop-done", repair_phase="same_scope_after_fix")
    store = MemoryStore.from_paths(root=tmp_path)
    h = _build_evidence_hygiene(store)
    assert h["complete_repair_loop_count"] == 1
    assert h["open_repair_loop_count"] == 0


def test_hygiene_counts_test_fixture_claims(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _wrap(scope=str(tmp_path), failure_origin="test_first_contract")
    _wrap(scope=str(tmp_path), failure_origin="synthetic")
    _wrap(scope=str(tmp_path), failure_origin="organic_real")
    store = MemoryStore.from_paths(root=tmp_path)
    h = _build_evidence_hygiene(store)
    assert h["test_fixture_claim_count"] == 2


def test_hygiene_counts_invocation_artifacts(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _wrap(scope=str(tmp_path), failure_origin="invocation_artifact")
    _wrap(scope=str(tmp_path), failure_origin="organic_real")
    store = MemoryStore.from_paths(root=tmp_path)
    h = _build_evidence_hygiene(store)
    assert h["invocation_artifact_count"] == 1


def test_hygiene_empty_store(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    store = MemoryStore.from_paths(root=tmp_path)
    h = _build_evidence_hygiene(store)
    assert h["total_claims"] == 0
    assert h["scoped_claim_count"] == 0
    assert h["scoped_claim_ratio"] == 0.0


# ---------------------------------------------------------------------------
# _build_next_actions unit tests (pure function, no CLI)
# ---------------------------------------------------------------------------

def test_next_actions_empty_for_clean_ledger():
    h = {
        "total_claims": 5, "scoped_claim_count": 5, "unscoped_claim_count": 0,
        "unknown_failure_origin_count": 0, "repair_phase_without_loop_count": 0,
        "open_repair_loop_count": 0, "open_repair_loop_ids": [],
        "complete_repair_loop_count": 2,
    }
    assert _build_next_actions(h) == []


def test_next_actions_unscoped():
    h = {
        "total_claims": 3, "scoped_claim_count": 1, "unscoped_claim_count": 2,
        "unknown_failure_origin_count": 0, "repair_phase_without_loop_count": 0,
        "open_repair_loop_ids": [],
    }
    actions = _build_next_actions(h)
    assert any("--scope-path" in a for a in actions)


def test_next_actions_unknown_origin():
    h = {
        "total_claims": 3, "scoped_claim_count": 3, "unscoped_claim_count": 0,
        "unknown_failure_origin_count": 2, "repair_phase_without_loop_count": 0,
        "open_repair_loop_ids": [],
    }
    actions = _build_next_actions(h)
    assert any("agent-guide" in a for a in actions)
    assert any("2 claim" in a for a in actions)


def test_next_actions_open_loop():
    h = {
        "total_claims": 3, "scoped_claim_count": 3, "unscoped_claim_count": 0,
        "unknown_failure_origin_count": 0, "repair_phase_without_loop_count": 0,
        "open_repair_loop_ids": ["loop-abc"],
    }
    actions = _build_next_actions(h)
    assert any("loop-abc" in a for a in actions)
    assert any("same_scope_after_fix" in a for a in actions)


# ---------------------------------------------------------------------------
# CLI integration: doctor text + JSON
# ---------------------------------------------------------------------------

def test_doctor_hygiene_section_in_text(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    capsys.readouterr()  # clear setup output
    main(["doctor"])
    out = capsys.readouterr().out
    assert "Evidence Hygiene:" in out


def test_doctor_json_has_evidence_hygiene(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    capsys.readouterr()
    main(["doctor", "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    assert "evidence_hygiene" in d
    assert "next_actions" in d
    assert "total_claims" in d["evidence_hygiene"]
    assert isinstance(d["next_actions"], list)


def test_doctor_preserves_existing_json_fields(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    capsys.readouterr()
    main(["doctor", "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    for key in ("schema_version", "overall_status", "exit_code", "checks",
                "counts", "warnings", "critical", "next_steps"):
        assert key in d, f"missing existing key: {key}"


def test_doctor_exit_code_behavior_preserved(tmp_path, monkeypatch):
    """Uninitialized dir = exit 2. Hygiene must not override critical exit codes."""
    monkeypatch.chdir(tmp_path)
    rc = main(["doctor"])
    assert rc == 2


def test_doctor_clean_ledger_empty_next_actions(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    _wrap(scope=str(tmp_path), failure_origin="organic_real")
    capsys.readouterr()  # clear any wrap output
    main(["doctor"])
    out = capsys.readouterr().out
    assert "Next actions:" not in out


# ---------------------------------------------------------------------------
# Preflight empty-ledger guidance
# ---------------------------------------------------------------------------

def test_preflight_empty_ledger_text_guidance(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    capsys.readouterr()
    main(["preflight", "--scope-path", str(tmp_path)])
    out = capsys.readouterr().out
    assert "No historical failures for this scope yet." in out
    assert "template dogfood" in out


def test_preflight_empty_ledger_json_note(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    capsys.readouterr()
    main(["preflight", "--scope-path", str(tmp_path), "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    assert d.get("intelligence_note") == "no_matching_scoped_claims"


def test_preflight_with_failures_no_empty_note(tmp_path, monkeypatch, capsys):
    """When there are matching failures, intelligence_note must NOT appear."""
    _setup(tmp_path, monkeypatch)
    _wrap(scope=str(tmp_path), failure_origin="organic_real", exit_code=1)
    capsys.readouterr()
    main(["preflight", "--scope-path", str(tmp_path), "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    assert "intelligence_note" not in d


# ---------------------------------------------------------------------------
# README
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parents[3]


def test_readme_mentions_is_my_ledger_healthy():
    readme = (_REPO_ROOT / "packages" / "chimera-memory" / "README.md").read_text()
    assert "Is my ledger healthy?" in readme
    assert "evidence" in readme.lower()
