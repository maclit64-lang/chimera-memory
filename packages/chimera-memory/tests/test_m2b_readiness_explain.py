"""Tests for v0.10 m2b-readiness --explain and dependency constraint hygiene."""
from __future__ import annotations

import json
from pathlib import Path


from chimera_memory.cli import main


_REPO_ROOT = Path(__file__).parents[3]


def _setup(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    main(["init"])


# ---------------------------------------------------------------------------
# --explain text output
# ---------------------------------------------------------------------------

def test_m2b_readiness_explain_text_output(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    main(["m2b-readiness", "--explain"])
    out = capsys.readouterr().out
    assert "Why readiness is blocked" in out
    assert "organic_real_failed" in out
    assert "comparable_groups" in out
    assert "remaining" in out


def test_m2b_readiness_explain_shows_thresholds(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    main(["m2b-readiness", "--explain"])
    out = capsys.readouterr().out
    # Must show required threshold value
    assert "5" in out  # organic_failures_min


def test_m2b_readiness_explain_says_do_not_manufacture_failures(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    main(["m2b-readiness", "--explain"])
    out = capsys.readouterr().out
    assert "manufacture" in out.lower() or "Do not manufacture" in out


def test_m2b_readiness_explain_does_not_include_score_or_ranking(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    main(["m2b-readiness", "--explain"])
    out = capsys.readouterr().out.lower()
    # Must not output any score value or ranking
    assert "score:" not in out
    assert "rank:" not in out
    assert "ranking:" not in out


def test_m2b_readiness_explain_includes_how_to_advice(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    main(["m2b-readiness", "--explain"])
    out = capsys.readouterr().out
    assert "same_scope_after_fix" in out
    assert "organic_real" in out


# ---------------------------------------------------------------------------
# --explain --json output
# ---------------------------------------------------------------------------

def test_m2b_readiness_explain_json_output(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    capsys.readouterr()
    main(["m2b-readiness", "--explain", "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    assert "explain" in d
    exp = d["explain"]
    assert "organic_real_failed_current" in exp
    assert "organic_real_failed_threshold" in exp
    assert "organic_real_failed_remaining" in exp
    assert "comparable_groups_current" in exp
    assert "comparable_groups_threshold" in exp
    assert "comparable_groups_remaining" in exp
    assert "total_organic_real_claims" in exp
    assert "advice" in exp
    assert isinstance(exp["advice"], list)
    assert len(exp["advice"]) > 0


def test_m2b_readiness_explain_json_remaining_non_negative(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    capsys.readouterr()
    main(["m2b-readiness", "--explain", "--json"])
    d = json.loads(capsys.readouterr().out)
    exp = d["explain"]
    assert exp["organic_real_failed_remaining"] >= 0
    assert exp["comparable_groups_remaining"] >= 0


def test_m2b_readiness_explain_json_advice_no_manufacture(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    capsys.readouterr()
    main(["m2b-readiness", "--explain", "--json"])
    d = json.loads(capsys.readouterr().out)
    advice_text = " ".join(d["explain"]["advice"]).lower()
    assert "manufacture" in advice_text


# ---------------------------------------------------------------------------
# Without --explain, JSON unchanged
# ---------------------------------------------------------------------------

def test_m2b_readiness_no_explain_json_unchanged(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    capsys.readouterr()
    main(["m2b-readiness", "--json"])
    d = json.loads(capsys.readouterr().out)
    # "explain" key must NOT be present without --explain
    assert "explain" not in d
    # Existing keys must still be present
    assert "readiness_level" in d
    assert "blockers" in d
    assert "schema_version" in d
    assert "dq_cohort_summary" in d
    assert "thresholds" in d


# ---------------------------------------------------------------------------
# Dependency constraint
# ---------------------------------------------------------------------------

def test_dependency_constraint_present():
    pyproject = (_REPO_ROOT / "packages" / "chimera-memory" / "pyproject.toml").read_text()
    assert "chimera-memory-types>=0.24.0,<1.0" in pyproject


# ---------------------------------------------------------------------------
# Contract doc and README
# ---------------------------------------------------------------------------

def test_m2b_readiness_json_contract_doc_exists():
    assert (_REPO_ROOT / "docs" / "contracts" / "m2b-readiness-json.md").exists()


def test_readme_mentions_m2b_readiness_explain():
    readme = (_REPO_ROOT / "packages" / "chimera-memory" / "README.md").read_text()
    assert "m2b-readiness --explain" in readme
