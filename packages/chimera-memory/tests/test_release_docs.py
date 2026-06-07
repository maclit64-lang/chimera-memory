"""Guard tests for release documentation integrity."""

import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_DOCS = [
    (REPO_ROOT / "docs" / "releases" / "v0.11.0.md", "0.11.0"),
    (REPO_ROOT / "docs" / "releases" / "v0.12.0.md", "0.12.0"),
]


@pytest.mark.parametrize("doc_path,ver", RELEASE_DOCS, ids=["v0.11.0", "v0.12.0"])
def test_release_doc_exists(doc_path, ver):
    assert doc_path.exists(), f"Missing: {doc_path}"


@pytest.mark.parametrize("doc_path,ver", RELEASE_DOCS, ids=["v0.11.0", "v0.12.0"])
def test_release_doc_mentions_version(doc_path, ver):
    text = doc_path.read_text()
    assert "chimera-memory" in text.lower()
    assert ver in text


@pytest.mark.parametrize("doc_path,ver", RELEASE_DOCS, ids=["v0.11.0", "v0.12.0"])
def test_release_doc_has_pypi_link(doc_path, ver):
    text = doc_path.read_text()
    assert f"https://pypi.org/project/chimera-memory/{ver}/" in text


@pytest.mark.parametrize("doc_path,ver", RELEASE_DOCS, ids=["v0.11.0", "v0.12.0"])
def test_release_doc_has_source_link(doc_path, ver):
    text = doc_path.read_text()
    assert "https://github.com/maclit64-lang/chimera-memory" in text


@pytest.mark.parametrize("doc_path,ver", RELEASE_DOCS, ids=["v0.11.0", "v0.12.0"])
def test_release_doc_no_private_paths(doc_path, ver):
    text = doc_path.read_text()
    assert "/Users/agbodaniel" not in text


@pytest.mark.parametrize("doc_path,ver", RELEASE_DOCS, ids=["v0.11.0", "v0.12.0"])
def test_release_doc_no_tokens(doc_path, ver):
    text = doc_path.read_text()
    assert "pypi-" not in text
    assert "ghp_" not in text


@pytest.mark.parametrize("doc_path,ver", RELEASE_DOCS, ids=["v0.11.0", "v0.12.0"])
def test_release_doc_no_m2b_scoring_claim(doc_path, ver):
    text = doc_path.read_text().lower()
    assert "m2b scoring is built" not in text
    assert "model ranking is built" not in text
    assert "routing is built" not in text
