from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from chimera_memory.storage import MemoryStore
from chimera_memory.xray import generate_xray, render_pr_comment

_FORBIDDEN = (
    "production-ready",
    "guaranteed",
    "certified",
    "the agent lied",
    "merge is approved",
    "safe to merge",
)


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
    (tmp_path / "pkg" / "a.py").write_text("x = 2\n")  # uncommitted change
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_pr_comment_has_title_and_verdict(repo: Path) -> None:
    comment = render_pr_comment(generate_xray(MemoryStore.from_paths(root=repo), root=repo))
    assert "Chimera Memory Evidence Receipt" in comment
    assert "**Verdict:**" in comment


def test_pr_comment_states_honesty_rule(repo: Path) -> None:
    comment = render_pr_comment(generate_xray(MemoryStore.from_paths(root=repo), root=repo))
    assert "scores evidence quality, not code correctness" in comment.lower()


def test_pr_comment_reports_counts_from_existing_fields(repo: Path) -> None:
    comment = render_pr_comment(generate_xray(MemoryStore.from_paths(root=repo), root=repo))
    # Uses upstream fields, not invented ones.
    assert "Scope drift" in comment
    assert "Evidence-dark" in comment
    assert "Contradicted claims" in comment
    assert "Unsettled claims" in comment
    assert "PR_EVIDENCE.md" in comment


def test_pr_comment_uses_no_forbidden_language(repo: Path) -> None:
    comment = render_pr_comment(
        generate_xray(MemoryStore.from_paths(root=repo), root=repo)
    ).lower()
    for word in _FORBIDDEN:
        assert word not in comment


def test_pr_comment_present_absent_for_scope_drift(repo: Path) -> None:
    # No claim locked -> evidence-dark present, scope drift absent.
    comment = render_pr_comment(generate_xray(MemoryStore.from_paths(root=repo), root=repo))
    # The scope-drift line resolves to a clear present/absent token.
    drift_line = next(line for line in comment.splitlines() if "Scope drift" in line)
    assert ("absent" in drift_line.lower()) or ("present" in drift_line.lower())


def test_cli_xray_generate_pr_comment_format(repo: Path) -> None:
    """`xray generate --format pr-comment` prints the compact comment."""
    from chimera_memory.cli import main

    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["xray", "generate", "--format", "pr-comment"])
    out = buf.getvalue()
    assert rc == 0
    assert "Chimera Memory Evidence Receipt" in out
    assert "scores evidence quality, not code correctness" in out.lower()


def test_cli_xray_generate_markdown_still_default(repo: Path) -> None:
    """Default format is unchanged full markdown (back-compat)."""
    from chimera_memory.cli import main

    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["xray", "generate"])
    out = buf.getvalue()
    assert rc == 0
    assert "# PR Evidence — Merge X-Ray" in out
