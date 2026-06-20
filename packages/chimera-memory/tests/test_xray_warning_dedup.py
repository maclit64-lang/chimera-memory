from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from chimera_memory.storage import MemoryStore
from chimera_memory.xray import generate_xray, render_markdown


def _git(tmp_path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t.dev")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "pkg").mkdir(parents=True)
    (tmp_path / "pkg" / "a.py").write_text("x = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")
    # leave an uncommitted change so working-tree mode is exercised
    (tmp_path / "pkg" / "a.py").write_text("x = 2\n")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_working_tree_guidance_not_duplicated(repo: Path) -> None:
    """The 'For PR reviews use' guidance appears at most once in the rendered report."""
    store = MemoryStore.from_paths(root=repo)
    md = render_markdown(generate_xray(store, root=repo))
    assert md.count("For PR reviews use:") <= 1


def test_working_tree_mode_header_present(repo: Path) -> None:
    """Dedup must not remove the single working-tree-mode disclosure."""
    store = MemoryStore.from_paths(root=repo)
    md = render_markdown(generate_xray(store, root=repo))
    assert "Working-tree mode" in md
