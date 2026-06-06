"""Tests for preflight git scope parsing edge cases."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from chimera_memory.preflight import (
    build_preflight,
    format_preflight_text,
    infer_scopes_from_git,
)
from chimera_memory.storage import MemoryStore

# ---------------------------------------------------------------------------
# infer_scopes_from_git unit tests
# ---------------------------------------------------------------------------


def _mock_git_output(lines: list[str]):
    """Context manager that mocks subprocess.run output for git status."""
    from unittest.mock import MagicMock

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "\n".join(lines) + "\n"
    mock_result.stderr = ""
    return patch("subprocess.run", return_value=mock_result)


def test_modified_file(tmp_path: Path) -> None:
    with _mock_git_output([" M packages/chimera-memory/src/foo.py"]):
        changed, scopes = infer_scopes_from_git(tmp_path)
    assert "packages/chimera-memory/src/foo.py" in changed
    assert "packages/chimera-memory" in scopes


def test_deleted_file_still_infers_scope(tmp_path: Path) -> None:
    with _mock_git_output([" D packages/chimera-memory/src/deleted.py"]):
        changed, scopes = infer_scopes_from_git(tmp_path)
    assert "packages/chimera-memory/src/deleted.py" in changed
    assert "packages/chimera-memory" in scopes


def test_renamed_file_uses_new_path(tmp_path: Path) -> None:
    with _mock_git_output(["R  old_name.py -> packages/chimera-memory/src/new_name.py"]):
        changed, scopes = infer_scopes_from_git(tmp_path)
    assert "packages/chimera-memory/src/new_name.py" in changed
    assert "packages/chimera-memory" in scopes


def test_untracked_excluded_by_default(tmp_path: Path) -> None:
    with _mock_git_output(["?? new_untracked_file.py"]):
        changed, scopes = infer_scopes_from_git(tmp_path)
    assert changed == []
    assert scopes == []


def test_untracked_included_with_flag(tmp_path: Path) -> None:
    with _mock_git_output(["?? packages/chimera-memory/src/new_file.py"]):
        changed, scopes = infer_scopes_from_git(tmp_path, include_untracked=True)
    assert "packages/chimera-memory/src/new_file.py" in changed
    assert "packages/chimera-memory" in scopes


def test_no_changes_returns_empty(tmp_path: Path) -> None:
    with _mock_git_output([]):
        changed, scopes = infer_scopes_from_git(tmp_path)
    assert changed == []
    assert scopes == []


def test_docs_only_change_infers_docs_scope(tmp_path: Path) -> None:
    with _mock_git_output([" M docs/strategy/some-doc.md"]):
        changed, scopes = infer_scopes_from_git(tmp_path)
    assert "docs" in scopes
    assert "packages/chimera-memory" not in scopes


def test_mixed_docs_and_package_shows_both(tmp_path: Path) -> None:
    with _mock_git_output([
        " M docs/strategy/some-doc.md",
        " M packages/chimera-memory/src/foo.py",
    ]):
        changed, scopes = infer_scopes_from_git(tmp_path)
    assert "docs" in scopes
    assert "packages/chimera-memory" in scopes


def test_chimera_memory_types_does_not_match_chimera_memory(tmp_path: Path) -> None:
    """packages/chimera-memory-types must not produce packages/chimera-memory scope."""
    with _mock_git_output([" M packages/chimera-memory-types/src/chimera_memory_types/foo.py"]):
        changed, scopes = infer_scopes_from_git(tmp_path)
    assert "packages/chimera-memory-types" in scopes
    assert "packages/chimera-memory" not in scopes


def test_unknown_top_level_uses_fallback_scope(tmp_path: Path) -> None:
    with _mock_git_output([" M some_unknown_dir/file.py"]):
        changed, scopes = infer_scopes_from_git(tmp_path)
    assert "some_unknown_dir" in scopes


def test_not_a_git_repo_returns_empty(tmp_path: Path) -> None:
    """Running in a non-git dir returns empty lists, not an exception."""
    # tmp_path is not a git repo
    changed, scopes = infer_scopes_from_git(tmp_path)
    assert changed == []
    assert scopes == []


def test_git_not_installed_returns_empty(tmp_path: Path) -> None:
    with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
        changed, scopes = infer_scopes_from_git(tmp_path)
    assert changed == []
    assert scopes == []


# ---------------------------------------------------------------------------
# format_preflight_text output tests
# ---------------------------------------------------------------------------


def _empty_store(tmp_path: Path) -> MemoryStore:
    store = MemoryStore(tmp_path / ".chimera-memory")
    store.ensure()
    return store


def test_text_includes_source_field(tmp_path: Path) -> None:
    store = _empty_store(tmp_path)
    report = build_preflight(store, scope_paths=["packages/chimera-memory"])
    text = format_preflight_text(report)
    assert "Source:" in text


def test_text_includes_recommended_checks(tmp_path: Path) -> None:
    store = _empty_store(tmp_path)
    report = build_preflight(store, scope_paths=["packages/chimera-memory"])
    text = format_preflight_text(report)
    assert "pytest" in text or "Recommended" in text


def test_text_no_changes_message_for_git_source_no_files(tmp_path: Path) -> None:
    """When source=none, text says no changes detected."""
    store = _empty_store(tmp_path)
    with _mock_git_output([]):
        report = build_preflight(store, from_git=True)
    text = format_preflight_text(report)
    assert "No git changes" in text or "none" in report.source.lower()


def test_text_advisory_disclaimer(tmp_path: Path) -> None:
    store = _empty_store(tmp_path)
    report = build_preflight(store)
    text = format_preflight_text(report)
    assert "advisory" in text.lower()
    assert "routing" in text.lower()
