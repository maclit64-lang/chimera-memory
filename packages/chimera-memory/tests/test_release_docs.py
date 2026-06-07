"""Guard tests for release documentation integrity."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_DOC = REPO_ROOT / "docs" / "releases" / "v0.11.0.md"


def test_release_doc_exists():
    assert RELEASE_DOC.exists(), f"Missing: {RELEASE_DOC}"


def test_release_doc_mentions_version():
    text = RELEASE_DOC.read_text()
    assert "chimera-memory" in text.lower()
    assert "0.11.0" in text


def test_release_doc_has_pypi_link():
    text = RELEASE_DOC.read_text()
    assert "https://pypi.org/project/chimera-memory/0.11.0/" in text


def test_release_doc_has_source_link():
    text = RELEASE_DOC.read_text()
    assert "https://github.com/maclit64-lang/chimera-memory" in text


def test_release_doc_no_private_paths():
    text = RELEASE_DOC.read_text()
    assert "/Users/agbodaniel" not in text


def test_release_doc_no_tokens():
    text = RELEASE_DOC.read_text()
    assert "pypi-" not in text
    assert "ghp_" not in text


def test_release_doc_no_m2b_scoring_claim():
    text = RELEASE_DOC.read_text().lower()
    assert "m2b scoring is built" not in text
    assert "model ranking is built" not in text
    assert "routing is built" not in text
