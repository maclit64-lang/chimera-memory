"""Guard tests for the first-user adoption messaging (ADOPT-1).

These assert the package README stays scannable and honest: the hero artifact,
the choose-your-mode sections, the warning-types table, the FAQ, and the honesty
boundary — with no affirmative correctness/safety overclaim.
"""
from __future__ import annotations

from pathlib import Path

_README = Path(__file__).resolve().parents[1] / "README.md"

_FORBIDDEN = (
    "production-ready",
    "certified",
    "approved to merge",
    "guaranteed",
    "the agent lied",
    "untested",
)


def _text() -> str:
    return _README.read_text()


def test_pr_evidence_is_hero_in_first_12_lines() -> None:
    head = "\n".join(_text().splitlines()[:12])
    assert "PR_EVIDENCE.md" in head


def test_core_positioning_and_honesty_present() -> None:
    t = _text()
    assert "PR_EVIDENCE.md" in t
    assert "evidence quality, not code correctness" in t
    assert "Warnings are review prompts" in t


def test_choose_your_mode_sections_present() -> None:
    t = _text()
    assert "## What you get" in t
    assert "## Choose your mode" in t
    # advisory default and opt-in stricter mode both shown
    assert "fail-on: never" in t
    assert "fail-on: warnings" in t


def test_action_examples_use_v0270_with_prerelease_caveat() -> None:
    t = _text()
    assert "maclit64-lang/chimera-memory@v0.27.0" in t
    # honest about not-yet-tagged
    assert "Until `v0.27.0` is tagged" in t


def test_warning_types_and_faq_present() -> None:
    t = _text()
    assert "## Warning types" in t
    assert "## FAQ" in t
    for family in ("Evidence Quality", "Test Integrity", "Evidence Coverage"):
        assert family in t


def test_no_forbidden_affirmative_claims() -> None:
    lower = _text().lower()
    for phrase in _FORBIDDEN:
        assert phrase not in lower
