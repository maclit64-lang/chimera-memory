"""Guard the consolidated v0.27.0 final-release notes (BIGREL-4).

Locks that the release note describes the full big-release stack and keeps the
honesty boundary, without overclaiming. Negated honesty wording (e.g. "not proof
that a bug returned", "does not prove the code is correct") is allowed — only
unambiguous affirmative overclaims are rejected.
"""
from __future__ import annotations

from pathlib import Path

_NOTES = Path(__file__).resolve().parents[3] / "docs" / "releases" / "v0.27.0.md"

# Unambiguous affirmative overclaims (these never appear in honest negations).
_FORBIDDEN_AFFIRMATIVE = (
    "production-ready", "certified", "approved to merge", "guaranteed",
    "the agent lied", "malicious",
)


def test_release_notes_exist() -> None:
    assert _NOTES.exists()


def test_release_notes_cover_full_stack() -> None:
    t = _NOTES.read_text()
    for marker in (
        "PR_EVIDENCE.md",
        "GitHub Action",
        "Evidence Quality Warnings",
        "Test Integrity Warnings",
        "Evidence Coverage Warnings",
        "Local Relapse Warnings",
        "Opt-in evidence gate",
        "Proof Debt command",
        "Schema and trust boundary",
        "Storage performance test hardening",
    ):
        assert marker in t, f"release notes missing: {marker}"


def test_release_notes_keep_honesty_boundary() -> None:
    t = _NOTES.read_text()
    assert "scores evidence quality, not code correctness" in t
    assert "not proof that a bug returned" in t


def test_release_notes_state_local_only_status() -> None:
    assert "Not pushed, tagged, or published" in _NOTES.read_text()


def test_release_notes_gate_aggregate_is_current() -> None:
    t = _NOTES.read_text()
    # `warnings` covers all four families incl. local relapse (true + CLI-usable).
    assert "aggregates all four warning families" in t


def test_release_notes_no_affirmative_overclaim() -> None:
    lower = _NOTES.read_text().lower()
    for phrase in _FORBIDDEN_AFFIRMATIVE:
        assert phrase not in lower, f"overclaim phrase in release notes: {phrase!r}"
