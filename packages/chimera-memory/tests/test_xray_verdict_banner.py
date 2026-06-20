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
    (tmp_path / "packages" / "cart").mkdir(parents=True)
    (tmp_path / "packages" / "payments").mkdir(parents=True)
    (tmp_path / "packages" / "cart" / "checkout.py").write_text("x = 1\n")
    (tmp_path / "packages" / "payments" / "refund.py").write_text("y = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _banner_line(md: str) -> str:
    for line in md.splitlines():
        if line.startswith("## Verdict"):
            return line
    raise AssertionError("no verdict banner found")


def test_banner_is_first_heading_and_labeled(repo: Path) -> None:
    """The verdict banner is a labeled `## Verdict: <LABEL>` heading near the top."""
    store = MemoryStore.from_paths(root=repo)
    md = render_markdown(generate_xray(store, root=repo))
    banner = _banner_line(md)
    # Banner carries an at-a-glance label, not just the bare word "Verdict".
    assert banner.startswith("## Verdict: ")
    # It is the first H2 in the document.
    first_h2 = next(line for line in md.splitlines() if line.startswith("## "))
    assert first_h2 == banner


def test_banner_review_required_when_evidence_dark(repo: Path) -> None:
    """An uncovered (evidence-dark) change yields a REVIEW REQUIRED banner."""
    (repo / "packages" / "payments" / "refund.py").write_text("y = 2\n")
    store = MemoryStore.from_paths(root=repo)
    md = render_markdown(generate_xray(store, root=repo))
    assert "## Verdict: REVIEW REQUIRED" in md


def test_banner_carries_evidence_quality_caveat(repo: Path) -> None:
    """The banner block restates the honesty rule (evidence quality, not correctness)."""
    store = MemoryStore.from_paths(root=repo)
    md = render_markdown(generate_xray(store, root=repo))
    # Within the first ~8 lines after the banner, the no-correctness caveat appears.
    idx = md.splitlines().index(_banner_line(md))
    head = "\n".join(md.splitlines()[idx : idx + 8]).lower()
    assert "evidence quality" in head
    assert "not code correctness" in head


def test_banner_uses_no_forbidden_language(repo: Path) -> None:
    """The verdict banner must never use correctness/safety/approval language."""
    (repo / "packages" / "payments" / "refund.py").write_text("y = 3\n")
    store = MemoryStore.from_paths(root=repo)
    md = render_markdown(generate_xray(store, root=repo))
    idx = md.splitlines().index(_banner_line(md))
    head = "\n".join(md.splitlines()[idx : idx + 8]).lower()
    for forbidden in (
        "production-ready",
        "guaranteed",
        "certified",
        "approved",
        "the agent lied",
    ):
        assert forbidden not in head
