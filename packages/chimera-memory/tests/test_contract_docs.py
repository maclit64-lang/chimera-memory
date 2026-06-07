"""Guard tests for JSON contract documentation accuracy."""

import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_DIR = REPO_ROOT / "docs" / "contracts"

REPAIR_LOOPS_DOC = CONTRACTS_DIR / "repair-loops-json.md"
DOCTOR_DOC = CONTRACTS_DIR / "doctor-json.md"
PREFLIGHT_DOC = CONTRACTS_DIR / "preflight-json.md"
M2B_DOC = CONTRACTS_DIR / "m2b-readiness-json.md"

ALL_DOCS = [REPAIR_LOOPS_DOC, DOCTOR_DOC, PREFLIGHT_DOC, M2B_DOC]


@pytest.mark.parametrize("doc", ALL_DOCS, ids=lambda p: p.name)
def test_contract_doc_exists(doc):
    assert doc.exists(), f"Missing: {doc}"


def test_repair_loops_mentions_status_fields():
    text = REPAIR_LOOPS_DOC.read_text()
    assert "status" in text
    assert "missing_phase" in text


def test_repair_loops_mentions_loop_arrays():
    text = REPAIR_LOOPS_DOC.read_text()
    assert "open_loops" in text
    assert "complete_loops" in text
    assert "malformed_loops" in text


def test_doctor_mentions_evidence_hygiene():
    text = DOCTOR_DOC.read_text()
    assert "evidence_hygiene" in text
    assert "next_actions" in text


def test_preflight_mentions_open_repair_loops():
    text = PREFLIGHT_DOC.read_text()
    assert "open_repair_loops_for_scope" in text


def test_m2b_mentions_explain():
    text = M2B_DOC.read_text()
    assert "explain" in text


@pytest.mark.parametrize("doc", ALL_DOCS, ids=lambda p: p.name)
def test_contract_doc_no_private_paths(doc):
    text = doc.read_text()
    assert "/Users/agbodaniel" not in text


@pytest.mark.parametrize("doc", ALL_DOCS, ids=lambda p: p.name)
def test_contract_doc_no_tokens(doc):
    text = doc.read_text()
    assert "pypi-" not in text
    assert "ghp_" not in text


@pytest.mark.parametrize("doc", ALL_DOCS, ids=lambda p: p.name)
def test_contract_doc_no_overclaims(doc):
    text = doc.read_text().lower()
    assert "m2b scoring is built" not in text
    assert "model ranking is built" not in text
    assert "routing is built" not in text
