"""BIGREL-3: local relapse warning — conservative, advisory, local-only.

Flags when a current claim/change resembles a previously CONTRADICTED local
claim (overlapping scope + same normalized intent or shared specific command
fingerprint). It never claims recurrence, correctness, safety, or blame.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from chimera_memory.proof_debt import compute_proof_debt
from chimera_memory.storage import MemoryStore
from chimera_memory.xray import (
    LocalRelapseWarning,
    detect_local_relapse_warnings,
    evaluate_evidence_gate,
    generate_xray,
    render_markdown,
    render_pr_comment,
)

# Words that would overclaim — must never appear in relapse output.
_FORBIDDEN = (
    "bug returned", "issue recurred", "recurred", "came back", "code is wrong",
    "is wrong", "unsafe", "production-ready", "approved", "certified",
    "guaranteed", "the agent lied", "malicious",
)


def _claim(
    claim_id: str, status: str, intent: str, scope: str,
    falsifiers: list[dict] | None = None,
) -> dict:
    return {
        "claim_id": claim_id,
        "intent": intent,
        "scope_path": scope,
        "falsifiers": falsifiers or [],
        "must_not_break": [],
        "settlement": {"status": status, "commands": [], "scope_drift_files": []},
    }


# ── detector: true / false positives ──────────────────────────────────────


def test_no_prior_contradicted_claim_no_warning() -> None:
    claims = [_claim("c_now", "VALIDATED", "fix login redirect", "pkg/auth")]
    assert detect_local_relapse_warnings(claims, ["pkg/auth/login.py"]) == []


def test_same_intent_overlapping_scope_warns() -> None:
    claims = [
        _claim("c_now", "VALIDATED", "fix login redirect", "pkg/auth"),
        _claim("c_old", "CONTRADICTED", "fix login redirect", "pkg/auth"),
    ]
    warns = detect_local_relapse_warnings(claims, ["pkg/auth/login.py"])
    assert len(warns) == 1
    assert warns[0].prior_claim_id == "c_old"
    assert warns[0].code == "LOCAL_RELAPSE_WARNING"


def test_same_intent_unrelated_scope_no_warning() -> None:
    claims = [
        _claim("c_now", "VALIDATED", "fix login redirect", "pkg/auth"),
        _claim("c_old", "CONTRADICTED", "fix login redirect", "lib/unrelated"),
    ]
    assert detect_local_relapse_warnings(claims, ["pkg/auth/login.py"]) == []


def test_overlapping_scope_different_intent_no_warning() -> None:
    claims = [
        _claim("c_now", "VALIDATED", "add pagination to results", "pkg/auth"),
        _claim("c_old", "CONTRADICTED", "refactor cache layer", "pkg/auth"),
    ]
    assert detect_local_relapse_warnings(claims, ["pkg/auth/login.py"]) == []


def test_generic_command_only_overlap_no_warning() -> None:
    """Overlapping scope + only a generic bare command (pytest) must not trigger."""
    claims = [
        _claim("c_now", "VALIDATED", "add pagination", "pkg/auth",
               falsifiers=[{"command": ["pytest"]}]),
        _claim("c_old", "CONTRADICTED", "refactor cache", "pkg/auth",
               falsifiers=[{"command": ["uv", "run", "pytest"]}]),
    ]
    assert detect_local_relapse_warnings(claims, ["pkg/auth/login.py"]) == []


def test_same_claim_id_no_self_match() -> None:
    """A contradicted claim covering the change must not match itself."""
    claims = [_claim("c1", "CONTRADICTED", "fix login redirect", "pkg/auth")]
    assert detect_local_relapse_warnings(claims, ["pkg/auth/login.py"]) == []


def test_prior_validated_no_warning() -> None:
    claims = [
        _claim("c_now", "VALIDATED", "fix login redirect", "pkg/auth"),
        _claim("c_old", "VALIDATED", "fix login redirect", "pkg/auth"),
    ]
    assert detect_local_relapse_warnings(claims, ["pkg/auth/login.py"]) == []


def test_shared_specific_command_fingerprint_warns() -> None:
    """Different intent but a shared specific command target + overlap triggers."""
    fals = [{"command": ["pytest", "pkg/auth/test_login.py::test_redirect"]}]
    claims = [
        _claim("c_now", "VALIDATED", "polish login flow", "pkg/auth", falsifiers=fals),
        _claim("c_old", "CONTRADICTED", "stabilize redirect", "pkg/auth", falsifiers=fals),
    ]
    warns = detect_local_relapse_warnings(claims, ["pkg/auth/login.py"])
    assert len(warns) == 1
    assert "command" in warns[0].match_reason


def test_intent_normalization_matches_despite_punctuation_case() -> None:
    claims = [
        _claim("c_now", "VALIDATED", "Fix  Login Redirect!", "pkg/auth"),
        _claim("c_old", "CONTRADICTED", "fix login redirect", "pkg/auth"),
    ]
    assert len(detect_local_relapse_warnings(claims, ["pkg/auth/login.py"])) == 1


def test_deterministic_order_by_prior_claim_id() -> None:
    claims = [
        _claim("c_now", "VALIDATED", "fix login redirect", "pkg/auth"),
        _claim("c_bbb", "CONTRADICTED", "fix login redirect", "pkg/auth"),
        _claim("c_aaa", "CONTRADICTED", "fix login redirect", "pkg/auth"),
    ]
    warns = detect_local_relapse_warnings(claims, ["pkg/auth/login.py"])
    ids = [w.prior_claim_id for w in warns]
    assert ids == sorted(ids) == ["c_aaa", "c_bbb"]


def test_warning_text_has_no_overclaim() -> None:
    claims = [
        _claim("c_now", "VALIDATED", "fix login redirect", "pkg/auth"),
        _claim("c_old", "CONTRADICTED", "fix login redirect", "pkg/auth"),
    ]
    w = detect_local_relapse_warnings(claims, ["pkg/auth/login.py"])[0]
    blob = " ".join([w.title, w.explanation, w.hint, w.match_reason]).lower()
    for bad in _FORBIDDEN:
        assert bad not in blob, f"overclaim word {bad!r} in relapse warning"
    assert "resembles" in blob and "review" in blob


def test_local_relapse_warning_to_dict_exposes_prior_id() -> None:
    w = LocalRelapseWarning(
        code="LOCAL_RELAPSE_WARNING", title="t", severity="advisory",
        explanation="e", hint="h", prior_claim_id="c_old", match_reason="r",
    )
    d = w.to_dict()
    assert d["prior_claim_id"] == "c_old"
    assert d["code"] == "LOCAL_RELAPSE_WARNING"


# ── integration: generate_xray + markdown + PR comment + JSON ──────────────


def _git(p: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=p, check=True, capture_output=True)


def _repo_with_relapse(tmp_path: Path) -> MemoryStore:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t.dev")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "auth.py").write_text("def f():\n    return 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")
    (tmp_path / "pkg" / "auth.py").write_text("def f():\n    return 2\n")
    store = MemoryStore.from_paths(root=tmp_path)
    store.initialize()
    # Prior contradicted claim + current validated claim, same intent + scope.
    store.append_claim_lock(_claim("c_old", "CONTRADICTED", "fix auth token refresh", "pkg"))
    store.append_claim_lock({
        **_claim("c_now", "VALIDATED", "fix auth token refresh", "pkg"),
        "settlement": {
            "status": "VALIDATED", "settled_at": "2026-06-22T00:00:00+00:00",
            "commands": [], "changed_files": ["pkg/auth.py"], "scope_drift_files": [],
        },
    })
    return store


def test_generate_xray_surfaces_relapse_additively(tmp_path: Path, monkeypatch) -> None:
    store = _repo_with_relapse(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = generate_xray(store, root=tmp_path)
    assert result["counts"]["local_relapse_warnings"] == 1
    assert len(result["local_relapse_warnings"]) == 1
    assert result["local_relapse_warnings"][0]["prior_claim_id"] == "c_old"
    json.dumps(result)  # additive + serialisable


def test_markdown_relapse_section_present_only_when_present(tmp_path: Path, monkeypatch) -> None:
    store = _repo_with_relapse(tmp_path)
    monkeypatch.chdir(tmp_path)
    md = render_markdown(generate_xray(store, root=tmp_path))
    assert "## Local Relapse Warnings" in md
    assert "c_old" in md
    # advisory caveat present; isolate the section and assert no overclaim in it.
    section = md.split("## Local Relapse Warnings", 1)[1].split("\n## ", 1)[0].lower()
    assert "advisory" in section and "resembles" in section
    for bad in _FORBIDDEN:
        assert bad not in section, f"overclaim word {bad!r} in relapse section"


def test_markdown_no_relapse_section_when_absent(tmp_path: Path, monkeypatch) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t.dev")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.py").write_text("x = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")
    (tmp_path / "a.py").write_text("x = 2\n")
    store = MemoryStore.from_paths(root=tmp_path)
    store.initialize()
    monkeypatch.chdir(tmp_path)
    md = render_markdown(generate_xray(store, root=tmp_path))
    assert "## Local Relapse Warnings" not in md


def test_pr_comment_compact_relapse_line(tmp_path: Path, monkeypatch) -> None:
    store = _repo_with_relapse(tmp_path)
    monkeypatch.chdir(tmp_path)
    comment = render_pr_comment(generate_xray(store, root=tmp_path))
    assert "Local relapse warnings: 1" in comment


# ── gate integration ───────────────────────────────────────────────────────


def _gate_result(relapse: int = 0, **extra: int) -> dict:
    counts = {
        "evidence_quality_warnings": 0, "test_integrity_warnings": 0,
        "evidence_coverage_warnings": 0, "contradicted": 0, "unsettled": 0,
        "scope_drift": 0, "evidence_dark_source": 0,
        "local_relapse_warnings": relapse, **extra,
    }
    return {"verdict_label": "COVERED — review still advised", "counts": counts}


def test_gate_warnings_includes_relapse() -> None:
    res = evaluate_evidence_gate(_gate_result(relapse=1), fail_on="warnings")
    assert not res.passed
    assert any("relapse" in r.lower() for r in res.reasons)


def test_gate_never_passes_with_relapse() -> None:
    assert evaluate_evidence_gate(_gate_result(relapse=1), fail_on="never").passed


def test_gate_specific_relapse_policy() -> None:
    assert not evaluate_evidence_gate(_gate_result(relapse=1), fail_on="local-relapse-warnings").passed
    assert evaluate_evidence_gate(_gate_result(relapse=0), fail_on="local-relapse-warnings").passed


def test_gate_warnings_clean_passes() -> None:
    assert evaluate_evidence_gate(_gate_result(relapse=0), fail_on="warnings").passed


# ── proof-debt integration ─────────────────────────────────────────────────


def _xr(local_relapse: list[dict] | None = None, **extra) -> dict:
    counts = {
        "unsettled": 0, "contradicted": 0, "evidence_quality_warnings": 0,
        "test_integrity_warnings": 0, "evidence_coverage_warnings": 0,
        "evidence_dark_source": 0, "scope_drift": 0,
        "local_relapse_warnings": len(local_relapse or []),
    }
    return {
        "verdict_label": "COVERED — review still advised",
        "settled_claims": [],
        "evidence_quality_warnings": [],
        "test_integrity_warnings": [],
        "evidence_coverage_warnings": [],
        "local_relapse_warnings": local_relapse or [],
        "counts": counts,
        **extra,
    }


def _relapse_dict(prior_id: str = "c_old") -> dict:
    return {
        "code": "LOCAL_RELAPSE_WARNING",
        "title": "Possible local relapse signal",
        "severity": "advisory",
        "explanation": "This change resembles a previously contradicted local claim with overlapping scope.",
        "hint": "Review the prior contradicted claim and add targeted evidence before relying on the current result.",
        "prior_claim_id": prior_id,
        "match_reason": "matching claim intent and overlapping scope",
    }


def test_proof_debt_includes_relapse_item() -> None:
    debt = compute_proof_debt(_xr(local_relapse=[_relapse_dict("c_old")]))
    cats = [it["category"] for it in debt["items"]]
    assert "LOCAL_RELAPSE_WARNING" in cats
    assert debt["summary"]["local_relapse_warnings"] == 1
    item = next(it for it in debt["items"] if it["category"] == "LOCAL_RELAPSE_WARNING")
    assert item["ref"] == "c_old"


def test_proof_debt_relapse_ranked_below_review_above_quality() -> None:
    debt = compute_proof_debt(_xr(
        local_relapse=[_relapse_dict("c_old")],
        settled_claims=[{"claim_id": "x", "status": "CONTRADICTED", "intent": "i"}],
        evidence_quality_warnings=[{"code": "GREEN_ONLY_EVIDENCE", "title": "Green-only", "explanation": "e", "hint": "h"}],
        counts={
            "unsettled": 0, "contradicted": 1, "evidence_quality_warnings": 1,
            "test_integrity_warnings": 0, "evidence_coverage_warnings": 0,
            "evidence_dark_source": 0, "scope_drift": 0, "local_relapse_warnings": 1,
        },
    ))
    cats = [it["category"] for it in debt["items"]]
    assert cats.index("CONTRADICTED_CLAIM") < cats.index("LOCAL_RELAPSE_WARNING")
    assert cats.index("LOCAL_RELAPSE_WARNING") < cats.index("EVIDENCE_QUALITY_WARNING")


def test_proof_debt_relapse_text_has_no_overclaim() -> None:
    from chimera_memory.proof_debt import render_proof_debt_text

    text = render_proof_debt_text(compute_proof_debt(_xr(local_relapse=[_relapse_dict()]))).lower()
    for bad in _FORBIDDEN:
        assert bad not in text, f"overclaim word {bad!r} in proof-debt text"


# ── docs guards ─────────────────────────────────────────────────────────────


def test_readme_documents_local_relapse() -> None:
    t = " ".join((Path(__file__).resolve().parents[1] / "README.md").read_text().split())
    assert "Local Relapse" in t
    assert "previously contradicted local claim" in t
    assert "not proof that a bug returned" in t


def test_proof_debt_doc_lists_relapse_category() -> None:
    t = (Path(__file__).resolve().parents[3] / "docs" / "proof-debt.md").read_text()
    assert "LOCAL_RELAPSE_WARNING" in t
