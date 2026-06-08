"""Guard tests for claim-locked evidence / Merge X-Ray docs (v0.22)."""
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONTRACTS = _REPO_ROOT / "docs" / "contracts"
_EXAMPLES = _REPO_ROOT / "docs" / "examples"
_README = _REPO_ROOT / "packages" / "chimera-memory" / "README.md"

_CLAIM_CONTRACT = _CONTRACTS / "claim-lock-json.md"
_XRAY_CONTRACT = _CONTRACTS / "xray-json.md"
_CLAIM_EXAMPLE = _EXAMPLES / "claim-locked-coding.md"
_PR_EXAMPLE = _EXAMPLES / "pr-evidence-example.md"

_ALL_DOCS = [_CLAIM_CONTRACT, _XRAY_CONTRACT, _CLAIM_EXAMPLE, _PR_EXAMPLE]


@pytest.mark.parametrize("doc", _ALL_DOCS, ids=lambda p: p.name)
def test_doc_exists(doc: Path) -> None:
    assert doc.exists(), f"Missing: {doc}"


def test_claim_contract_mentions_statuses() -> None:
    text = _CLAIM_CONTRACT.read_text()
    for status in ("LOCKED", "VALIDATED", "CONTRADICTED", "UNSETTLED", "SCOPE_DRIFT"):
        assert status in text


def test_claim_contract_mentions_attribution_seam() -> None:
    text = _CLAIM_CONTRACT.read_text()
    for field in ("terminal_id", "worktree_path", "attribution_confidence"):
        assert field in text


def test_xray_contract_mentions_sections() -> None:
    text = _XRAY_CONTRACT.read_text()
    for section in (
        "Verdict",
        "Settled Claims",
        "Evidence-Dark",
        "Scope Drift",
        "Reviewer Focus",
        "Non-Claims",
    ):
        assert section in text


@pytest.mark.parametrize("doc", _ALL_DOCS, ids=lambda p: p.name)
def test_doc_has_honesty_caveat(doc: Path) -> None:
    text = doc.read_text().lower()
    assert "not proof of correctness" in text or "settled evidence" in text


@pytest.mark.parametrize("doc", _ALL_DOCS, ids=lambda p: p.name)
def test_doc_no_private_paths(doc: Path) -> None:
    assert "/Users/agbodaniel" not in doc.read_text()


@pytest.mark.parametrize("doc", _ALL_DOCS, ids=lambda p: p.name)
def test_doc_no_tokens(doc: Path) -> None:
    text = doc.read_text()
    assert "pypi-" not in text
    assert "ghp_" not in text


@pytest.mark.parametrize("doc", _ALL_DOCS, ids=lambda p: p.name)
def test_doc_no_overclaims(doc: Path) -> None:
    text = doc.read_text().lower()
    assert "guaranteed tested" not in text
    assert "proves the code is correct" not in text
    assert "m2b scoring is built" not in text
    assert "model ranking is built" not in text


def test_readme_mentions_claim_lock() -> None:
    text = _README.read_text()
    assert "chimera-memory claim lock" in text


def test_readme_mentions_xray() -> None:
    text = _README.read_text()
    assert "chimera-memory xray generate" in text
    assert "PR_EVIDENCE.md" in text


def test_readme_xray_section_is_honest() -> None:
    text = _README.read_text()
    assert "settled evidence, not proof of correctness" in text


def test_xray_contract_mentions_new_fields() -> None:
    text = _XRAY_CONTRACT.read_text()
    assert "working_tree_warning" in text
    assert "evidence_dark_classified" in text
    assert "evidence_dark_source" in text
    assert "evidence_dark_cache" in text
