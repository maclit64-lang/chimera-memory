"""Guard tests for the trust/redaction documentation (BIGREL-1)."""
from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DOC = _REPO_ROOT / "docs" / "trust-and-redaction.md"
_README = _REPO_ROOT / "packages" / "chimera-memory" / "README.md"

# Affirmative overclaims that must not appear. "correct"/"incorrect" are
# excluded because they appear only in honest negations ("does not prove ...").
_FORBIDDEN = (
    "production-ready",
    "certified",
    "approved",
    "guaranteed",
    "the agent lied",
    "malicious",
)


def test_trust_doc_exists() -> None:
    assert _DOC.exists(), "docs/trust-and-redaction.md must exist"


def test_trust_doc_required_content() -> None:
    t = _DOC.read_text()
    low = t.lower()
    assert "local-first" in low
    assert "evidence quality, not code correctness" in low
    assert "PR_EVIDENCE.md" in t
    assert "excerpt" in low          # command stdout/stderr excerpts
    assert "redact" in low           # redaction discussed
    assert "review" in low and "sharing" in low  # review before sharing


def test_trust_doc_no_cloud_claim() -> None:
    low = _DOC.read_text().lower()
    assert "no account" in low or "no cloud" in low or "runs locally" in low


def test_trust_doc_no_forbidden_affirmative_claims() -> None:
    low = _DOC.read_text().lower()
    for phrase in _FORBIDDEN:
        assert phrase not in low


def test_readme_links_to_trust_doc() -> None:
    t = _README.read_text()
    assert "docs/trust-and-redaction.md" in t
    assert "Trust and redaction" in t
