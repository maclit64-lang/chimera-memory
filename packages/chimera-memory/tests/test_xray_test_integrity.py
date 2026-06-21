"""Test Integrity Warnings (L-004).

Advisory warnings that flag when a diff appears to weaken the test suite
(added skip/xfail, focus-only markers, deleted test files). They are review
prompts derived from the diff; they never claim the code is wrong or correct.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from chimera_memory.storage import MemoryStore
from chimera_memory.xray import (
    _is_test_file,
    detect_test_integrity_warnings,
    generate_xray,
    render_markdown,
    render_pr_comment,
)

_FORBIDDEN = (
    "code is correct",
    "code is safe",
    "production-ready",
    "approved",
    "certified",
    "guaranteed",
    "the agent lied",
    "malicious",
)


@pytest.mark.parametrize(
    "path,is_test",
    [
        ("tests/test_a.py", True),
        ("pkg/tests/test_b.py", True),
        ("test_foo.py", True),
        ("foo_test.py", True),
        ("ui/Button.test.tsx", True),
        ("ui/Button.spec.ts", True),
        ("api/handler.test.js", True),
        ("src/app.py", False),
        ("README.md", False),
        ("docs/testing.md", False),
    ],
)
def test_is_test_file(path: str, is_test: bool) -> None:
    assert _is_test_file(path) is is_test


def _git(p: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=p, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t.dev")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text(
        "def test_one():\n    assert add(1, 2) == 3\n"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "README.md").write_text("# project\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _store(repo: Path) -> MemoryStore:
    store = MemoryStore.from_paths(root=repo)
    store.initialize()
    return store


def _codes(result: dict) -> set[str]:
    return {w["code"] for w in result["test_integrity_warnings"]}


def test_skip_added_warns(repo: Path) -> None:
    (repo / "tests" / "test_a.py").write_text(
        "import pytest\n\n\n@pytest.mark.skip(reason='flaky')\ndef test_one():\n"
        "    assert add(1, 2) == 3\n"
    )
    result = generate_xray(_store(repo), root=repo)
    assert "TEST_SKIP_ADDED" in _codes(result)
    md = render_markdown(result)
    assert "## Test Integrity Warnings" in md
    assert "test_a.py" in md


def test_xfail_added_warns(repo: Path) -> None:
    (repo / "tests" / "test_a.py").write_text(
        "import pytest\n\n\n@pytest.mark.xfail\ndef test_one():\n    assert add(1, 2) == 3\n"
    )
    assert "TEST_XFAIL_ADDED" in _codes(generate_xray(_store(repo), root=repo))


def test_only_focus_added_warns(repo: Path) -> None:
    # New untracked TS test file with a focus-only marker.
    (repo / "ui").mkdir()
    (repo / "ui" / "button.test.ts").write_text(
        "it.only('renders', () => { expect(1).toBe(1); });\n"
    )
    assert "ONLY_FOCUS_ADDED" in _codes(generate_xray(_store(repo), root=repo))


def test_test_file_deleted_warns(repo: Path) -> None:
    (repo / "tests" / "test_a.py").unlink()
    result = generate_xray(_store(repo), root=repo)
    assert "TEST_FILE_DELETED" in _codes(result)
    assert "test_a.py" in render_markdown(result)


def test_skip_in_non_test_file_not_flagged(repo: Path) -> None:
    (repo / "src" / "app.py").write_text(
        "def add(a, b):\n    # pytest.mark.skip mentioned in a comment\n    return a + b\n"
    )
    (repo / "README.md").write_text("# project\nWe use @pytest.mark.skip in some tests.\n")
    assert generate_xray(_store(repo), root=repo)["test_integrity_warnings"] == []


def test_removed_skip_not_flagged(repo: Path) -> None:
    # Commit a test that already has a skip, then REMOVE the skip.
    (repo / "tests" / "test_a.py").write_text(
        "import pytest\n\n\n@pytest.mark.skip\ndef test_one():\n    assert add(1, 2) == 3\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "add skip")
    (repo / "tests" / "test_a.py").write_text(
        "def test_one():\n    assert add(1, 2) == 3\n"
    )
    assert "TEST_SKIP_ADDED" not in _codes(generate_xray(_store(repo), root=repo))


def test_pr_comment_compact_count(repo: Path) -> None:
    (repo / "tests" / "test_a.py").write_text(
        "import pytest\n\n\n@pytest.mark.skip\ndef test_one():\n    assert add(1, 2) == 3\n"
    )
    comment = render_pr_comment(generate_xray(_store(repo), root=repo))
    assert "Test integrity warnings:" in comment
    assert "scores evidence quality, not code correctness" in comment.lower()


def test_no_section_when_no_warnings(repo: Path) -> None:
    (repo / "src" / "app.py").write_text("def add(a, b):\n    return a + b + 0\n")
    md = render_markdown(generate_xray(_store(repo), root=repo))
    assert "## Test Integrity Warnings" not in md


def test_json_additive(repo: Path) -> None:
    result = generate_xray(_store(repo), root=repo)
    assert "test_integrity_warnings" in result
    assert "test_integrity_warnings" in result["counts"]
    # L-003 and existing keys remain.
    for k in ("evidence_quality_warnings", "verdict", "verdict_label", "counts"):
        assert k in result


def test_no_forbidden_language(repo: Path) -> None:
    (repo / "tests" / "test_a.py").write_text(
        "import pytest\n\n\n@pytest.mark.skip\ndef test_one():\n    assert add(1, 2) == 3\n"
    )
    result = generate_xray(_store(repo), root=repo)
    warnings = result["test_integrity_warnings"]
    assert warnings
    blob = " ".join(
        " ".join(w[k] for k in ("title", "explanation", "hint")) for w in warnings
    ).lower()
    for phrase in _FORBIDDEN:
        assert phrase not in blob
    assert "do not prove the code is wrong or correct" in render_markdown(result).lower()


def test_direct_api_range_mode(repo: Path) -> None:
    """test_integrity_warnings works in commit-range mode too."""
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    (repo / "tests" / "test_a.py").write_text(
        "import pytest\n\n\n@pytest.mark.skip\ndef test_one():\n    assert add(1, 2) == 3\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "weaken")
    warnings = detect_test_integrity_warnings(repo, base=base, head="HEAD")
    assert any(w.code == "TEST_SKIP_ADDED" for w in warnings)
