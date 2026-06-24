"""Stage 0: consolidated anti-overclaim membrane guard.

Canonical xray.py carries the honesty disclaimer but has no single
banned-phrase guard constant; enforcement is spread across surface
tests. This test consolidates the contract: a generated public
surface (PR_EVIDENCE markdown) must never *affirm* correctness,
safety, approval, certification, or merge-readiness, and must
affirmatively state the honesty caveat.

Non-brittle by construction: it asserts on the presence/absence of
canonical forbidden phrases in the rendered output, not on exact
prose snapshots. The canonical denial wording is "does not prove the
code is correct, secure, or complete" — it does NOT use any of the
forbidden phrases below, so a whole-document scan is safe.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from chimera_memory.storage import MemoryStore
from chimera_memory.xray import generate_xray, render_markdown

# The membrane: these must never appear as affirmations on a public surface.
FORBIDDEN_AFFIRMATIONS = (
    "safe to merge",
    "production ready",
    "production-ready",
    "certified",
    "approved",
    "guaranteed",
    "proves correctness",
    "proves safety",
)


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t.dev")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("x = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _render(repo: Path) -> str:
    store = MemoryStore.from_paths(root=repo)
    return render_markdown(generate_xray(store, root=repo))


def test_clean_repo_surface_has_no_forbidden_affirmations(repo: Path) -> None:
    md = _render(repo).lower()
    for phrase in FORBIDDEN_AFFIRMATIONS:
        assert phrase not in md, f"membrane breach: {phrase!r} present in PR_EVIDENCE"


def test_evidence_dark_surface_has_no_forbidden_affirmations(repo: Path) -> None:
    # An uncovered (evidence-dark) change exercises the REVIEW REQUIRED path.
    (repo / "pkg" / "mod.py").write_text("x = 2\n")
    md = _render(repo).lower()
    for phrase in FORBIDDEN_AFFIRMATIONS:
        assert phrase not in md, f"membrane breach: {phrase!r} present in PR_EVIDENCE"


def test_surface_states_the_honesty_caveat(repo: Path) -> None:
    # Positive membrane: the surface must affirmatively disclaim correctness.
    md = _render(repo).lower()
    assert "does not prove the code is correct" in md
    assert "evidence quality" in md
