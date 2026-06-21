"""Opt-in evidence gate (L-005).

A pure policy function over existing X-Ray fields, plus a `--fail-on` CLI flag.
Off by default (`never`). The gate enforces evidence policy; it never claims the
code is correct or incorrect.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from chimera_memory.cli import main
from chimera_memory.xray import EvidenceGateResult, evaluate_evidence_gate

_FORBIDDEN = (
    "code is wrong",
    "code is unsafe",
    "production-ready",
    "approved",
    "certified",
    "guaranteed",
    "malicious",
    "the agent lied",
)


def _result(
    *,
    verdict_label: str = "COVERED — review still advised",
    contradicted: int = 0,
    unsettled: int = 0,
    scope_drift: int = 0,
    evidence_dark_source: int = 0,
    eq: int = 0,
    ti: int = 0,
) -> dict:
    return {
        "verdict_label": verdict_label,
        "counts": {
            "contradicted": contradicted,
            "unsettled": unsettled,
            "scope_drift": scope_drift,
            "evidence_dark_source": evidence_dark_source,
            "evidence_quality_warnings": eq,
            "test_integrity_warnings": ti,
        },
    }


# ── pure policy function ──────────────────────────────────────────────────

def test_never_always_passes() -> None:
    g = evaluate_evidence_gate(
        _result(verdict_label="REVIEW REQUIRED", eq=9, ti=9, contradicted=9),
        fail_on="never",
    )
    assert g.passed is True and g.policy == "never" and g.reasons == ()


def test_review_required_policy() -> None:
    assert not evaluate_evidence_gate(
        _result(verdict_label="REVIEW REQUIRED"), fail_on="review-required"
    ).passed
    assert evaluate_evidence_gate(
        _result(verdict_label="COVERED — review still advised"), fail_on="review-required"
    ).passed


def test_warnings_policy_fails_on_either() -> None:
    assert not evaluate_evidence_gate(_result(eq=1), fail_on="warnings").passed
    assert not evaluate_evidence_gate(_result(ti=1), fail_on="warnings").passed
    assert evaluate_evidence_gate(_result(), fail_on="warnings").passed


def test_evidence_quality_warnings_policy() -> None:
    assert not evaluate_evidence_gate(_result(eq=1), fail_on="evidence-quality-warnings").passed
    # test-integrity warnings do NOT trip the evidence-quality policy
    assert evaluate_evidence_gate(_result(ti=3), fail_on="evidence-quality-warnings").passed


def test_test_integrity_warnings_policy() -> None:
    assert not evaluate_evidence_gate(_result(ti=1), fail_on="test-integrity-warnings").passed
    assert evaluate_evidence_gate(_result(eq=3), fail_on="test-integrity-warnings").passed


def test_contradicted_policy() -> None:
    assert not evaluate_evidence_gate(_result(contradicted=1), fail_on="contradicted").passed
    assert evaluate_evidence_gate(_result(contradicted=0), fail_on="contradicted").passed


def test_invalid_policy_raises() -> None:
    with pytest.raises(ValueError):
        evaluate_evidence_gate(_result(), fail_on="bogus")


def test_gate_result_shape() -> None:
    g = evaluate_evidence_gate(_result(eq=1), fail_on="warnings")
    assert isinstance(g, EvidenceGateResult)
    assert g.policy == "warnings" and g.passed is False
    assert isinstance(g.reasons, tuple) and g.reasons


def test_reasons_use_honest_language() -> None:
    g = evaluate_evidence_gate(_result(eq=2, ti=1), fail_on="warnings")
    blob = " ".join(g.reasons).lower()
    assert blob
    for phrase in _FORBIDDEN:
        assert phrase not in blob


# ── CLI --fail-on wiring ──────────────────────────────────────────────────

def _git(p: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=p, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t.dev")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "keep.txt").write_text("seed\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_cli_fail_on_never_exits_zero(repo: Path) -> None:
    rc = main(["xray", "generate", "--output", "PR_EVIDENCE.md", "--fail-on", "never"])
    assert rc == 0
    assert (repo / "PR_EVIDENCE.md").exists()


def test_cli_default_is_never(repo: Path) -> None:
    # No --fail-on => advisory default, exit 0.
    rc = main(["xray", "generate", "--output", "PR_EVIDENCE.md"])
    assert rc == 0


def test_cli_fail_on_warnings_fails_and_keeps_receipt(repo: Path, capsys) -> None:
    (repo / "tests").mkdir()
    (repo / "tests" / "test_a.py").write_text(
        "import pytest\n\n\n@pytest.mark.skip\ndef test_x():\n    assert 1 == 1\n"
    )
    rc = main(["xray", "generate", "--output", "PR_EVIDENCE.md", "--fail-on", "warnings"])
    assert rc == 2
    assert (repo / "PR_EVIDENCE.md").exists()  # receipt preserved on gate failure
    err = capsys.readouterr().err.lower()
    assert "evidence gate failed" in err
    assert "evidence quality, not code correctness" in err


def test_cli_fail_on_warnings_passes_when_clean(repo: Path) -> None:
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("x = 1\n")  # non-test change, no warnings
    rc = main(["xray", "generate", "--output", "PR_EVIDENCE.md", "--fail-on", "warnings"])
    assert rc == 0


def test_cli_invalid_fail_on_rejected(repo: Path, capsys) -> None:
    rc = main(["xray", "generate", "--fail-on", "bogus"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "invalid choice" in err and "--fail-on" in err
