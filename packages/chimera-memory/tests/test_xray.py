"""Tests for the Merge X-Ray / PR_EVIDENCE.md generator (v0.22)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from chimera_memory.claim_lock import lock_claim, settle_claim
from chimera_memory.cli import main
from chimera_memory.claim_lock import ClaimSpec
from chimera_memory.storage import MemoryStore
from chimera_memory.xray import generate_xray, render_markdown

_PASS = [sys.executable, "-c", "import sys; sys.exit(0)"]


def _git(tmp_path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t.dev")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "packages" / "cart").mkdir(parents=True)
    (tmp_path / "packages" / "payments").mkdir(parents=True)
    (tmp_path / "packages" / "cart" / "checkout.py").write_text("x = 1\n")
    (tmp_path / "packages" / "payments" / "refund.py").write_text("y = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _spec(scope: str = "packages/cart", falsifiers=None) -> ClaimSpec:
    return ClaimSpec(
        intent="fix checkout null deref",
        scope_path=scope,
        predicted_outcome="all pass",
        falsifiers=falsifiers if falsifiers is not None else [list(_PASS)],
        must_not_break=[],
    )


def test_xray_post_hoc_when_no_claims(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    (repo / "packages" / "cart" / "checkout.py").write_text("x = 2\n")
    result = generate_xray(store, root=repo)
    assert result["mode"] == "post_hoc"
    assert "Post-hoc" in result["verdict"]


def test_xray_validated_claim_covers_changed_file(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    rec = lock_claim(store, _spec(), root=repo)
    (repo / "packages" / "cart" / "checkout.py").write_text("x = 2\n")
    settle_claim(store, rec["claim_id"], root=repo)
    result = generate_xray(store, root=repo)
    assert "packages/cart/checkout.py" not in result["evidence_dark_files"]
    assert any(
        c["status"] == "VALIDATED" for c in result["settled_claims"]
    )


def test_xray_uncovered_file_is_evidence_dark(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    rec = lock_claim(store, _spec(), root=repo)
    (repo / "packages" / "cart" / "checkout.py").write_text("x = 2\n")
    (repo / "packages" / "payments" / "refund.py").write_text("y = 2\n")
    settle_claim(store, rec["claim_id"], root=repo)
    result = generate_xray(store, root=repo)
    assert "packages/payments/refund.py" in result["evidence_dark_files"]


def test_xray_scope_drift_appears(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    rec = lock_claim(store, _spec(), root=repo)
    (repo / "packages" / "payments" / "refund.py").write_text("y = 2\n")
    settle_claim(store, rec["claim_id"], root=repo)
    result = generate_xray(store, root=repo)
    assert "packages/payments/refund.py" in result["scope_drift_files"]


def test_xray_markdown_sections_present(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    rec = lock_claim(store, _spec(), root=repo)
    (repo / "packages" / "cart" / "checkout.py").write_text("x = 2\n")
    settle_claim(store, rec["claim_id"], root=repo)
    md = render_markdown(generate_xray(store, root=repo))
    for header in (
        "# PR Evidence — Merge X-Ray",
        "## Verdict",
        "## Settled Claims",
        "## Evidence-Dark Changes",
        "## Scope Drift",
        "## Weak / Unsettled Evidence",
        "## Reviewer Focus",
        "## Non-Claims",
    ):
        assert header in md


def test_xray_markdown_has_non_claims_caveat(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    md = render_markdown(generate_xray(store, root=repo))
    assert "settled evidence, not proof of correctness" in md


def test_xray_reviewer_focus_listed(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    rec = lock_claim(store, _spec(), root=repo)
    (repo / "packages" / "payments" / "refund.py").write_text("y = 2\n")
    settle_claim(store, rec["claim_id"], root=repo)
    result = generate_xray(store, root=repo)
    assert result["reviewer_focus"]
    assert any("refund.py" in f for f in result["reviewer_focus"])


def test_xray_json_is_stable_shape(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    result = generate_xray(store, root=repo)
    for key in (
        "schema_version",
        "verdict",
        "changed_files",
        "settled_claims",
        "evidence_dark_files",
        "scope_drift_files",
        "reviewer_focus",
        "counts",
        "caveat",
    ):
        assert key in result
    # JSON serialisable
    json.dumps(result)


def test_xray_does_not_claim_correctness(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    md = render_markdown(generate_xray(store, root=repo)).lower()
    assert "proof of correctness" not in md.replace(
        "not proof of correctness", ""
    ).replace("does not prove the code is correct", "")
    assert "guaranteed tested" not in md


# ── CLI ───────────────────────────────────────────────────────────────────
def test_cli_xray_generate_writes_file(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    rec = lock_claim(store, _spec(), root=repo)
    (repo / "packages" / "cart" / "checkout.py").write_text("x = 2\n")
    settle_claim(store, rec["claim_id"], root=repo)
    out = repo / "PR_EVIDENCE.md"
    assert main(["xray", "generate", "--output", str(out)]) == 0
    text = out.read_text()
    assert "PR Evidence" in text
    assert "Non-Claims" in text


def test_cli_xray_generate_json(repo: Path, capsys) -> None:
    assert main(["xray", "generate", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema_version"] == 1
