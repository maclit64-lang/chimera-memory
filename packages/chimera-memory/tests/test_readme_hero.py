from __future__ import annotations

from pathlib import Path

_README = Path(__file__).resolve().parents[1] / "README.md"


def _head(n: int = 40) -> str:
    return "\n".join(_README.read_text().splitlines()[:n])


def test_readme_names_pr_evidence_as_hero_near_top() -> None:
    """The main artifact, PR_EVIDENCE.md, is named in the first ~12 lines."""
    head = "\n".join(_README.read_text().splitlines()[:12])
    assert "PR_EVIDENCE.md" in head


def test_readme_states_category_near_top() -> None:
    """The proof-carrying-PR positioning is stated near the top."""
    head = _head(12).lower()
    assert "proof" in head and "evidence" in head


def test_readme_hero_keeps_honesty_rule() -> None:
    """The hero framing must not overclaim correctness."""
    head = _head(40).lower()
    # honest framing present
    assert "evidence quality" in head or "not proof of correctness" in head or "no cloud" in head
    # no forbidden correctness/approval language in the hero region
    for forbidden in ("production-ready", "guaranteed", "certified", "the agent lied"):
        assert forbidden not in head


def test_readme_python_version_still_truthful() -> None:
    text = _README.read_text()
    assert "Python 3.12+" in text
    assert "Python 3.10+" not in text
