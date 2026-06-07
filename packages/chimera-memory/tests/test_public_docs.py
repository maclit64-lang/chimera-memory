"""Guard tests for public-facing docs — ensures fresh-install-smoke.md stays current."""
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[3]
_TRANSCRIPT = _REPO_ROOT / "docs" / "examples" / "fresh-install-smoke.md"
_README = _REPO_ROOT / "packages" / "chimera-memory" / "README.md"


def test_fresh_install_smoke_exists():
    assert _TRANSCRIPT.exists()


def test_fresh_install_smoke_contains_install():
    text = _TRANSCRIPT.read_text()
    assert "pip install chimera-memory" in text


def test_fresh_install_smoke_contains_init():
    text = _TRANSCRIPT.read_text()
    assert "chimera-memory init" in text


def test_fresh_install_smoke_contains_wrap():
    text = _TRANSCRIPT.read_text()
    assert "chimera-memory wrap" in text


def test_fresh_install_smoke_contains_receipt():
    text = _TRANSCRIPT.read_text()
    assert "chimera-memory receipt latest" in text


def test_fresh_install_smoke_contains_m2b_explain():
    text = _TRANSCRIPT.read_text()
    assert "m2b-readiness --explain" in text


def test_fresh_install_smoke_no_private_paths():
    text = _TRANSCRIPT.read_text()
    assert "/Users/agbodaniel" not in text
    assert "/home/" not in text or "placeholder" in text.lower()


def test_fresh_install_smoke_no_real_tokens():
    text = _TRANSCRIPT.read_text()
    assert "pypi-" not in text
    assert "ghp_" not in text


def test_readme_python_version_accurate():
    text = _README.read_text()
    # Should say 3.12, not 3.10
    assert "Python 3.12+" in text
    assert "Python 3.10+" not in text


def test_readme_no_broken_relative_docs_link():
    text = _README.read_text()
    # PyPI-unfriendly relative link should not be present
    assert "](../../docs/prompts/)" not in text
