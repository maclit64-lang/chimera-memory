"""Proof Debt command (BIGREL-2).

A local, advisory summary of claims/receipts that still need stronger evidence,
computed only from existing X-Ray result fields. It scores evidence quality, not
code correctness, and never claims the code is wrong/correct.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from chimera_memory.cli import main
from chimera_memory.proof_debt import (
    PROOF_DEBT_SCHEMA_VERSION,
    compute_proof_debt,
    render_proof_debt_text,
)
from chimera_memory.storage import MemoryStore

_FORBIDDEN = (
    "production-ready",
    "approved",
    "certified",
    "guaranteed",
    "the agent lied",
    "malicious",
)


def _xr(
    *,
    settled: list[dict] | None = None,
    eq: list[dict] | None = None,
    ti: list[dict] | None = None,
    cov: list[dict] | None = None,
    label: str = "COVERED — review still advised",
    evidence_dark_source: int = 0,
    scope_drift: int = 0,
) -> dict:
    settled = settled or []
    eq = eq or []
    ti = ti or []
    cov = cov or []
    return {
        "verdict_label": label,
        "settled_claims": settled,
        "evidence_quality_warnings": eq,
        "test_integrity_warnings": ti,
        "evidence_coverage_warnings": cov,
        "counts": {
            "contradicted": sum(1 for c in settled if c["status"] == "CONTRADICTED"),
            "unsettled": sum(1 for c in settled if c["status"] == "UNSETTLED"),
            "evidence_quality_warnings": len(eq),
            "test_integrity_warnings": len(ti),
            "evidence_coverage_warnings": len(cov),
            "evidence_dark_source": evidence_dark_source,
            "scope_drift": scope_drift,
        },
    }


def _claim(cid: str, status: str, intent: str = "do a thing") -> dict:
    return {"claim_id": cid, "status": status, "intent": intent}


def _warn(code: str, title: str) -> dict:
    return {"code": code, "title": title, "severity": "advisory", "explanation": f"{title}.", "hint": "add evidence."}


# ── pure compute_proof_debt ───────────────────────────────────────────────

def test_empty_has_no_items() -> None:
    debt = compute_proof_debt(_xr())
    assert debt["items"] == []
    assert all(v == 0 for v in debt["summary"].values())


def test_unsettled_claim_counted_and_listed() -> None:
    debt = compute_proof_debt(_xr(settled=[_claim("clm_u", "UNSETTLED")]))
    assert debt["summary"]["unsettled_claims"] == 1
    assert any(i["category"] == "UNSETTLED_CLAIM" and i["ref"] == "clm_u" for i in debt["items"])


def test_contradicted_prioritized_above_weaker_debt() -> None:
    debt = compute_proof_debt(
        _xr(settled=[_claim("clm_c", "CONTRADICTED")], cov=[_warn("NO_TARGETED_EVIDENCE_FOR_CHANGED_SOURCE", "No obvious targeted evidence")])
    )
    assert debt["items"][0]["category"] == "CONTRADICTED_CLAIM"
    assert debt["summary"]["contradicted_claims"] == 1


def test_warning_families_counted() -> None:
    debt = compute_proof_debt(
        _xr(
            eq=[_warn("LINT_ONLY_EVIDENCE", "Lint-only evidence")],
            ti=[_warn("TEST_SKIP_ADDED", "Skip added")],
            cov=[_warn("NO_TARGETED_EVIDENCE_FOR_CHANGED_SOURCE", "No obvious targeted evidence")],
        )
    )
    s = debt["summary"]
    assert s["evidence_quality_warnings"] == 1
    assert s["test_integrity_warnings"] == 1
    assert s["evidence_coverage_warnings"] == 1
    cats = {i["category"] for i in debt["items"]}
    assert {"EVIDENCE_QUALITY_WARNING", "TEST_INTEGRITY_WARNING", "EVIDENCE_COVERAGE_WARNING"} <= cats


def test_review_required_receipt_counted() -> None:
    debt = compute_proof_debt(_xr(label="REVIEW REQUIRED"))
    assert debt["summary"]["review_required_receipts"] == 1
    assert any(i["category"] == "REVIEW_REQUIRED_RECEIPT" for i in debt["items"])


def test_evidence_dark_and_scope_drift_counted() -> None:
    debt = compute_proof_debt(_xr(evidence_dark_source=2, scope_drift=1))
    assert debt["summary"]["evidence_dark_sources"] == 2
    assert debt["summary"]["scope_drift"] == 1
    cats = {i["category"] for i in debt["items"]}
    assert "EVIDENCE_DARK_SOURCE" in cats and "SCOPE_DRIFT" in cats


def test_deterministic_ordering_by_severity() -> None:
    xr = _xr(
        settled=[_claim("clm_c", "CONTRADICTED"), _claim("clm_u", "UNSETTLED")],
        ti=[_warn("TEST_SKIP_ADDED", "Skip added")],
        cov=[_warn("NO_TARGETED_EVIDENCE_FOR_CHANGED_SOURCE", "No obvious targeted evidence")],
        eq=[_warn("LINT_ONLY_EVIDENCE", "Lint-only evidence")],
        label="REVIEW REQUIRED",
        evidence_dark_source=1,
        scope_drift=1,
    )
    order = [i["category"] for i in compute_proof_debt(xr)["items"]]
    expected = [
        "CONTRADICTED_CLAIM",
        "UNSETTLED_CLAIM",
        "REVIEW_REQUIRED_RECEIPT",
        "TEST_INTEGRITY_WARNING",
        "EVIDENCE_COVERAGE_WARNING",
        "EVIDENCE_QUALITY_WARNING",
        "EVIDENCE_DARK_SOURCE",
        "SCOPE_DRIFT",
    ]
    assert order == expected
    # stable across repeated calls
    assert compute_proof_debt(xr) == compute_proof_debt(xr)


def test_json_shape() -> None:
    debt = compute_proof_debt(_xr(settled=[_claim("clm_u", "UNSETTLED")]))
    assert debt["schema_version"] == PROOF_DEBT_SCHEMA_VERSION == 1
    assert set(debt["summary"]) == {
        "unsettled_claims", "contradicted_claims", "review_required_receipts",
        "local_relapse_warnings",
        "evidence_quality_warnings", "test_integrity_warnings",
        "evidence_coverage_warnings", "evidence_dark_sources", "scope_drift",
    }
    assert isinstance(debt["items"], list)
    json.dumps(debt)


def test_render_honesty_and_no_overclaim() -> None:
    text = render_proof_debt_text(compute_proof_debt(_xr(settled=[_claim("clm_c", "CONTRADICTED")]))).lower()
    assert "evidence quality, not code correctness" in text
    for p in _FORBIDDEN:
        assert p not in text


def test_render_no_debt_message() -> None:
    text = render_proof_debt_text(compute_proof_debt(_xr())).lower()
    assert "no proof debt found" in text
    assert "does not prove code is correct" in text


# ── CLI ───────────────────────────────────────────────────────────────────

def _git(p: Path, *a: str) -> None:
    subprocess.run(["git", *a], cwd=p, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t.dev")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "app.py").write_text("def f():\n    return 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_cli_proof_debt_in_help(capsys) -> None:
    rc = main(["--help"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "proof-debt" in out


def test_cli_proof_debt_with_debt(repo: Path, capsys) -> None:
    store = MemoryStore.from_paths(root=repo)
    store.initialize()
    (repo / "pkg" / "app.py").write_text("def f():\n    return 2\n")
    store.append_claim_lock(
        {
            "claim_id": "clm_lintonly",
            "intent": "fix bug",
            "scope_path": ".",
            "falsifiers": [{"command": ["ruff", "check", "."]}],
            "must_not_break": [],
            "settlement": {
                "status": "VALIDATED",
                "commands": [{"command": ["ruff", "check", "."], "role": "falsifier", "outcome": "PASS", "exit_code": 0, "stdout_excerpt": ""}],
                "changed_files": ["pkg/app.py"],
                "scope_drift_files": [],
            },
        }
    )
    rc = main(["proof-debt"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Proof Debt" in out
    assert "evidence quality, not code correctness" in out.lower()
    # lint-only quality + coverage warnings should surface as debt
    assert "warnings" in out.lower()


def test_cli_proof_debt_json(repo: Path, capsys) -> None:
    store = MemoryStore.from_paths(root=repo)
    store.initialize()
    rc = main(["proof-debt", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["schema_version"] == 1
    assert "summary" in data and "items" in data


def test_cli_proof_debt_no_debt(repo: Path, capsys) -> None:
    store = MemoryStore.from_paths(root=repo)
    store.initialize()
    (repo / "pkg" / "app.py").write_text("def f():\n    return 2\n")
    # Settled VALIDATED claim with a targeted test command → covered, no warnings.
    store.append_claim_lock(
        {
            "claim_id": "clm_ok",
            "intent": "update f",
            "scope_path": "pkg",
            "falsifiers": [{"command": ["pytest", "pkg/test_app.py::test_f"]}],
            "must_not_break": [],
            "settlement": {
                "status": "VALIDATED",
                "commands": [{"command": ["pytest", "pkg/test_app.py::test_f"], "role": "falsifier", "outcome": "PASS", "exit_code": 0, "stdout_excerpt": "1 passed"}],
                "changed_files": ["pkg/app.py"],
                "scope_drift_files": [],
            },
        }
    )
    rc = main(["proof-debt"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "No proof debt found" in out


_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_proof_debt_doc_exists_and_is_honest() -> None:
    doc = _REPO_ROOT / "docs" / "proof-debt.md"
    assert doc.exists()
    t = doc.read_text()
    assert "chimera-memory proof-debt" in t
    assert "does not prove code is correct or incorrect" in t.lower()
    low = t.lower()
    # "correct"/"safe" appear only in honest negations; check unambiguous overclaims.
    for phrase in ("production-ready", "certified", "approved", "guaranteed", "the agent lied", "malicious"):
        assert phrase not in low


def test_readme_mentions_proof_debt() -> None:
    readme = _REPO_ROOT / "packages" / "chimera-memory" / "README.md"
    t = readme.read_text()
    assert "proof-debt" in t
    assert "docs/proof-debt.md" in t
