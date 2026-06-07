"""Tests for v0.9 repair-loop guidance and JSON contract hardening."""
from __future__ import annotations

import json
from pathlib import Path


from chimera_memory.cli import _analyze_repair_loops, main
from chimera_memory.storage import MemoryStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    main(["init"])
    main(["session", "start", "--branch", "t", "--task-label", "t",
          "--agent", "a", "--model", "m", "--harness-id", "h"])


def _wrap(scope: str | None = None,
          failure_origin: str = "organic_real",
          exit_code: int = 0,
          repair_loop_id: str | None = None,
          repair_phase: str | None = None) -> None:
    args = ["wrap"]
    if scope:
        args += ["--scope-path", scope]
    args += ["--failure-origin", failure_origin, "--verification-scope", "package"]
    if repair_loop_id:
        args += ["--repair-loop-id", repair_loop_id]
    if repair_phase:
        args += ["--repair-phase", repair_phase]
    args += ["--", "python3", "-c", f"import sys; sys.exit({exit_code})"]
    main(args)


# ---------------------------------------------------------------------------
# _analyze_repair_loops unit tests
# ---------------------------------------------------------------------------

def test_analyze_open_loop(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _wrap(scope=str(tmp_path), exit_code=1,
          repair_loop_id="loop-open", repair_phase="baseline")
    store = MemoryStore.from_paths(root=tmp_path)
    data = _analyze_repair_loops(store)
    assert len(data["open_loops"]) == 1
    assert data["open_loops"][0]["repair_loop_id"] == "loop-open"
    assert data["open_loops"][0]["baseline_count"] == 1
    assert data["open_loops"][0]["same_scope_after_fix_count"] == 0
    assert len(data["complete_loops"]) == 0


def test_analyze_complete_loop(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _wrap(scope=str(tmp_path), exit_code=1,
          repair_loop_id="loop-done", repair_phase="baseline")
    _wrap(scope=str(tmp_path), exit_code=0,
          repair_loop_id="loop-done", repair_phase="same_scope_after_fix")
    store = MemoryStore.from_paths(root=tmp_path)
    data = _analyze_repair_loops(store)
    assert len(data["complete_loops"]) == 1
    assert data["complete_loops"][0]["repair_loop_id"] == "loop-done"
    assert len(data["open_loops"]) == 0


def test_analyze_ssaf_without_baseline_is_malformed(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    # SSAF validated but no CONTRADICTED baseline
    _wrap(scope=str(tmp_path), exit_code=0,
          repair_loop_id="loop-bad", repair_phase="same_scope_after_fix")
    store = MemoryStore.from_paths(root=tmp_path)
    data = _analyze_repair_loops(store)
    assert len(data["malformed_loops"]) == 1
    assert data["malformed_loops"][0]["repair_loop_id"] == "loop-bad"
    assert len(data["complete_loops"]) == 0


def test_analyze_regression_check_does_not_complete(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _wrap(scope=str(tmp_path), exit_code=1,
          repair_loop_id="loop-rcheck", repair_phase="baseline")
    _wrap(scope=str(tmp_path), exit_code=0,
          repair_loop_id="loop-rcheck", repair_phase="regression_check")
    store = MemoryStore.from_paths(root=tmp_path)
    data = _analyze_repair_loops(store)
    # regression_check does NOT close the loop
    assert len(data["open_loops"]) == 1
    assert data["open_loops"][0]["repair_loop_id"] == "loop-rcheck"
    assert len(data["complete_loops"]) == 0


def test_analyze_open_loop_includes_next_action(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _wrap(scope=str(tmp_path), exit_code=1,
          repair_loop_id="loop-na", repair_phase="baseline")
    store = MemoryStore.from_paths(root=tmp_path)
    data = _analyze_repair_loops(store)
    na = data["open_loops"][0]["next_action"]
    assert "same_scope_after_fix" in str(na)
    assert "loop-na" in str(na)


# ---------------------------------------------------------------------------
# repair-loops CLI text output
# ---------------------------------------------------------------------------

def test_repair_loops_text_open_section(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    _wrap(scope=str(tmp_path), exit_code=1,
          repair_loop_id="loop-text", repair_phase="baseline")
    capsys.readouterr()
    main(["repair-loops"])
    out = capsys.readouterr().out
    assert "Open (1)" in out
    assert "loop-text" in out
    assert "SSAF" in out


def test_repair_loops_text_complete_section(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    _wrap(scope=str(tmp_path), exit_code=1,
          repair_loop_id="loop-c", repair_phase="baseline")
    _wrap(scope=str(tmp_path), exit_code=0,
          repair_loop_id="loop-c", repair_phase="same_scope_after_fix")
    capsys.readouterr()
    main(["repair-loops"])
    out = capsys.readouterr().out
    assert "Complete (1)" in out
    assert "loop-c" in out
    assert "fixed_same_scope" in out


def test_repair_loops_text_malformed_section(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    _wrap(scope=str(tmp_path), exit_code=0,
          repair_loop_id="loop-m", repair_phase="same_scope_after_fix")
    capsys.readouterr()
    main(["repair-loops"])
    out = capsys.readouterr().out
    assert "Malformed" in out
    assert "loop-m" in out


def test_repair_loops_text_regression_note(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    _wrap(scope=str(tmp_path), exit_code=1,
          repair_loop_id="loop-note", repair_phase="baseline")
    capsys.readouterr()
    main(["repair-loops"])
    out = capsys.readouterr().out
    assert "regression_check does NOT" in out


# ---------------------------------------------------------------------------
# repair-loops --json
# ---------------------------------------------------------------------------

def test_repair_loops_json_schema_version(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    capsys.readouterr()
    main(["repair-loops", "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    assert d["schema_version"] == 1


def test_repair_loops_json_open_loops(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    _wrap(scope=str(tmp_path), exit_code=1,
          repair_loop_id="loop-j", repair_phase="baseline")
    capsys.readouterr()
    main(["repair-loops", "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    assert len(d["open_loops"]) == 1
    assert d["open_loops"][0]["repair_loop_id"] == "loop-j"
    assert d["open_loops"][0]["status"] == "open"
    assert d["open_loops"][0]["missing_phase"] == "same_scope_after_fix"


def test_repair_loops_json_complete_loops(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    _wrap(scope=str(tmp_path), exit_code=1,
          repair_loop_id="loop-cj", repair_phase="baseline")
    _wrap(scope=str(tmp_path), exit_code=0,
          repair_loop_id="loop-cj", repair_phase="same_scope_after_fix")
    capsys.readouterr()
    main(["repair-loops", "--json"])
    d = json.loads(capsys.readouterr().out)
    assert len(d["complete_loops"]) == 1
    assert d["complete_loops"][0]["repair_loop_id"] == "loop-cj"
    assert d["complete_loops"][0]["status"] == "complete"
    assert d["complete_loops"][0]["missing_phase"] is None


def test_repair_loops_json_malformed_loops(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    _wrap(scope=str(tmp_path), exit_code=0,
          repair_loop_id="loop-mj", repair_phase="same_scope_after_fix")
    capsys.readouterr()
    main(["repair-loops", "--json"])
    d = json.loads(capsys.readouterr().out)
    assert len(d["malformed_loops"]) == 1
    assert d["malformed_loops"][0]["status"] == "malformed"
    assert d["malformed_loops"][0]["missing_phase"] == "baseline"


def test_repair_loops_json_next_actions(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    _wrap(scope=str(tmp_path), exit_code=1,
          repair_loop_id="loop-na-j", repair_phase="baseline")
    capsys.readouterr()
    main(["repair-loops", "--json"])
    d = json.loads(capsys.readouterr().out)
    assert len(d["next_actions"]) == 1
    assert "loop-na-j" in d["next_actions"][0]


# ---------------------------------------------------------------------------
# Doctor next_actions with open loop
# ---------------------------------------------------------------------------

def test_doctor_next_actions_include_repair_loops_pointer(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    _wrap(scope=str(tmp_path), exit_code=1,
          repair_loop_id="loop-doc", repair_phase="baseline")
    capsys.readouterr()
    main(["doctor"])
    out = capsys.readouterr().out
    assert "repair-loops" in out
    assert "loop-doc" in out


# ---------------------------------------------------------------------------
# Preflight open-loop context
# ---------------------------------------------------------------------------

def test_preflight_shows_open_loop_for_matching_scope(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    scope = str(tmp_path)
    _wrap(scope=scope, exit_code=1,
          repair_loop_id="loop-pf", repair_phase="baseline")
    capsys.readouterr()
    main(["preflight", "--scope-path", scope])
    out = capsys.readouterr().out
    assert "Open repair loops" in out
    assert "loop-pf" in out


def test_preflight_no_loop_for_nonmatching_scope(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    scope = str(tmp_path / "pkg-a")
    other_scope = str(tmp_path / "pkg-b")
    _wrap(scope=scope, exit_code=1,
          repair_loop_id="loop-pfb", repair_phase="baseline")
    capsys.readouterr()
    main(["preflight", "--scope-path", other_scope])
    out = capsys.readouterr().out
    assert "loop-pfb" not in out


def test_preflight_json_open_repair_loops_field(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    scope = str(tmp_path)
    _wrap(scope=scope, exit_code=1,
          repair_loop_id="loop-pfj", repair_phase="baseline")
    capsys.readouterr()
    main(["preflight", "--scope-path", scope, "--json"])
    d = json.loads(capsys.readouterr().out)
    assert "open_repair_loops_for_scope" in d
    assert "loop-pfj" in d["open_repair_loops_for_scope"]


# ---------------------------------------------------------------------------
# Agent-guide and template dogfood
# ---------------------------------------------------------------------------

def test_agent_guide_ssaf_vs_regression_distinction(capsys):
    main(["agent-guide", "--agent", "generic"])
    out = capsys.readouterr().out
    assert "same_scope_after_fix" in out
    assert "regression_check" in out
    # Must not conflate them
    assert "fixed_same_scope" in out
    assert "later_regression_validated" in out


def test_agent_guide_manufacture_warning(capsys):
    main(["agent-guide"])
    out = capsys.readouterr().out
    assert "manufacture" in out.lower() or "fabricat" in out.lower() or "Do not" in out


def test_template_dogfood_includes_repair_scaffold(capsys, tmp_path):
    main(["template", "dogfood", "--scope-path", str(tmp_path)])
    out = capsys.readouterr().out
    assert "REAL BUG" in out
    assert "same_scope_after_fix" in out
    assert "regression_check does NOT" in out


# ---------------------------------------------------------------------------
# Contract docs exist
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parents[3]


def test_contract_docs_exist():
    contracts = _REPO_ROOT / "docs" / "contracts"
    assert (contracts / "doctor-json.md").exists()
    assert (contracts / "preflight-json.md").exists()
    assert (contracts / "repair-loops-json.md").exists()
