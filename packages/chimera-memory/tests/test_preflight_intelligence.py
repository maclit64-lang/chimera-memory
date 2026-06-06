"""Tests for v0.6 preflight intelligence: known failures, lessons, hygiene, scope matching."""

from __future__ import annotations

import json
import sys

import pytest

from chimera_memory.cli import main
from chimera_memory.preflight import (
    _lesson_text,
    _scope_match_reason,
    build_preflight,
)
from chimera_memory.storage import MemoryStore


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _init_and_session(tmp_path):
    main(["init"])
    main(["session", "start", "--branch", "t", "--task-label", "t",
          "--agent", "a", "--model", "m", "--harness-id", "h"])


# ---------------------------------------------------------------------------
# Scope matching — path boundary correctness
# ---------------------------------------------------------------------------


def test_scope_match_exact():
    reason = _scope_match_reason(["packages/chimera-memory"], ["packages/chimera-memory"])
    assert reason == "exact"


def test_scope_match_parent():
    # filter scope is parent of claim scope
    reason = _scope_match_reason(["packages/chimera-memory/src"], ["packages/chimera-memory"])
    assert reason == "parent"


def test_scope_match_child():
    # claim scope is parent of filter scope
    reason = _scope_match_reason(["packages/chimera-memory"], ["packages/chimera-memory/src"])
    assert reason == "child"


def test_scope_match_no_false_positive_types(tmp_path):
    """packages/chimera-memory must NOT match packages/chimera-memory-types."""
    reason = _scope_match_reason(
        ["packages/chimera-memory-types"], ["packages/chimera-memory"]
    )
    assert reason is None


def test_scope_match_no_false_positive_reverse():
    reason = _scope_match_reason(
        ["packages/chimera-memory"], ["packages/chimera-memory-types"]
    )
    assert reason is None


def test_scope_match_none_when_no_scopes():
    assert _scope_match_reason(None, ["packages/chimera-memory"]) is None


def test_scope_match_none_when_no_filter():
    # empty filter = all match → handled by build_preflight, not match_reason
    assert _scope_match_reason(["packages/chimera-memory"], []) is None


# ---------------------------------------------------------------------------
# Lesson text helper
# ---------------------------------------------------------------------------


def test_lesson_text_mypy():
    txt = _lesson_text("mypy packages/foo/src", "organic_real", None)
    assert "type check" in txt.lower() or "mypy" in txt.lower()


def test_lesson_text_pytest_invocation_artifact():
    txt = _lesson_text("pytest packages/foo -m 'not slow'", "invocation_artifact", None)
    assert "shell" in txt.lower() or "quoting" in txt.lower() or "marker" in txt.lower()


def test_lesson_text_m2b_readiness():
    txt = _lesson_text("chimera-memory m2b-readiness --json", "organic_real", None)
    assert "m2b" in txt.lower() or "readiness" in txt.lower()


def test_lesson_text_fallback():
    txt = _lesson_text("some-unknown-tool --flag", "organic_real", None)
    assert len(txt) > 10


def test_lesson_text_never_empty():
    for cmd in ("mypy", "pytest", "ruff", "chimera-memory m2b-readiness", "unknown"):
        txt = _lesson_text(cmd, "organic_real", None)
        assert txt, f"lesson_text was empty for cmd={cmd!r}"


# ---------------------------------------------------------------------------
# PreflightReport schema
# ---------------------------------------------------------------------------


def test_preflight_report_schema_version_is_2(tmp_path, capsys):
    main(["init"])
    capsys.readouterr()
    main(["preflight", "--scope-path", str(tmp_path), "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    assert d["schema_version"] == 2


def test_preflight_json_has_intelligence_fields(tmp_path, capsys):
    main(["init"])
    capsys.readouterr()
    main(["preflight", "--scope-path", str(tmp_path), "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    for key in ("known_failures", "repair_loop_lessons", "hygiene_warnings",
                "failure_signatures", "preflight_intelligence_note"):
        assert key in d, f"missing field: {key}"


def test_preflight_json_existing_fields_still_present(tmp_path, capsys):
    main(["init"])
    capsys.readouterr()
    main(["preflight", "--scope-path", str(tmp_path), "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    for key in ("source", "filters", "matching_claim_count", "recent_failures",
                "repair_loops", "recommended_checks", "m2b_readiness_level"):
        assert key in d, f"v1 field missing: {key}"


def test_preflight_intelligence_note_no_scoring_claim(tmp_path, capsys):
    main(["init"])
    capsys.readouterr()
    main(["preflight", "--scope-path", str(tmp_path), "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    note = d["preflight_intelligence_note"].lower()
    assert "not m2b scoring" in note or "not" in note


# ---------------------------------------------------------------------------
# Empty ledger does not crash
# ---------------------------------------------------------------------------


def test_preflight_empty_ledger_no_crash(tmp_path, capsys):
    main(["init"])
    capsys.readouterr()
    result = main(["preflight", "--scope-path", str(tmp_path)])
    assert result == 0
    out = capsys.readouterr().out
    assert "Preflight" in out


def test_preflight_empty_ledger_known_failures_empty(tmp_path, capsys):
    main(["init"])
    capsys.readouterr()
    main(["preflight", "--scope-path", str(tmp_path), "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    assert d["known_failures"] == []
    assert d["hygiene_warnings"] == []


# ---------------------------------------------------------------------------
# Scope filtering: unrelated scopes excluded
# ---------------------------------------------------------------------------


def test_preflight_excludes_unrelated_scope(tmp_path, monkeypatch):
    """A failure with scope packages/chimera-memory-types must not appear
    in preflight for packages/chimera-memory."""
    monkeypatch.setenv("CHIMERA_DQ_NO_WRITE", "1")
    _init_and_session(tmp_path)
    # Record a failure in types scope
    main(["wrap", "--failure-origin", "organic_real",
          "--verification-scope", "package",
          "--scope-path", "packages/chimera-memory-types",
          "--", sys.executable, "-c", "import sys; sys.exit(1)"])
    monkeypatch.delenv("CHIMERA_DQ_NO_WRITE", raising=False)
    # But preflight for chimera-memory should not include it
    store = MemoryStore.from_paths(root=tmp_path)
    report = build_preflight(store, scope_paths=["packages/chimera-memory"])
    for kf in report.known_failures:
        assert "chimera-memory-types" not in " ".join(kf.scope_paths), \
            "chimera-memory-types failure leaked into chimera-memory preflight"


# ---------------------------------------------------------------------------
# Origin filtering
# ---------------------------------------------------------------------------


def test_preflight_test_first_contract_excluded(tmp_path, monkeypatch):
    """test_first_contract failures must not appear in known_failures."""
    _init_and_session(tmp_path)
    main(["wrap", "--failure-origin", "test_first_contract",
          "--verification-scope", "package",
          "--scope-path", str(tmp_path),
          "--", sys.executable, "-c", "import sys; sys.exit(1)"])
    store = MemoryStore.from_paths(root=tmp_path)
    report = build_preflight(store, scope_paths=[str(tmp_path)])
    for kf in report.known_failures:
        assert kf.effective_failure_origin != "test_first_contract"


def test_preflight_synthetic_excluded(tmp_path, monkeypatch):
    """synthetic failures must not appear in known_failures."""
    _init_and_session(tmp_path)
    main(["wrap", "--failure-origin", "synthetic",
          "--verification-scope", "package",
          "--scope-path", str(tmp_path),
          "--", sys.executable, "-c", "import sys; sys.exit(1)"])
    store = MemoryStore.from_paths(root=tmp_path)
    report = build_preflight(store, scope_paths=[str(tmp_path)])
    for kf in report.known_failures:
        assert kf.effective_failure_origin != "synthetic"


def test_preflight_invocation_artifact_in_hygiene_not_known(tmp_path, monkeypatch):
    """invocation_artifact goes to hygiene_warnings, not known_failures."""
    _init_and_session(tmp_path)
    main(["wrap", "--failure-origin", "invocation_artifact",
          "--verification-scope", "package",
          "--scope-path", str(tmp_path),
          "--", sys.executable, "-c", "import sys; sys.exit(1)"])
    store = MemoryStore.from_paths(root=tmp_path)
    report = build_preflight(store, scope_paths=[str(tmp_path)])
    for kf in report.known_failures:
        assert kf.effective_failure_origin != "invocation_artifact", \
            "invocation_artifact should not be in known_failures"


def test_preflight_organic_real_in_known_failures(tmp_path, monkeypatch):
    """organic_real failure in matching scope appears in known_failures."""
    _init_and_session(tmp_path)
    main(["wrap", "--failure-origin", "organic_real",
          "--verification-scope", "package",
          "--scope-path", str(tmp_path),
          "--", sys.executable, "-c", "import sys; sys.exit(1)"])
    store = MemoryStore.from_paths(root=tmp_path)
    report = build_preflight(store, scope_paths=[str(tmp_path)])
    assert len(report.known_failures) >= 1
    assert report.known_failures[0].effective_failure_origin == "organic_real"


def test_known_failure_lesson_non_empty(tmp_path, monkeypatch):
    _init_and_session(tmp_path)
    main(["wrap", "--failure-origin", "organic_real",
          "--verification-scope", "package",
          "--scope-path", str(tmp_path),
          "--", sys.executable, "-c", "import sys; sys.exit(1)"])
    store = MemoryStore.from_paths(root=tmp_path)
    report = build_preflight(store, scope_paths=[str(tmp_path)])
    for kf in report.known_failures:
        assert kf.lesson, "lesson must be non-empty"


# ---------------------------------------------------------------------------
# --from-git still works
# ---------------------------------------------------------------------------


def test_preflight_from_git_works(tmp_path, capsys):
    main(["init"])
    capsys.readouterr()
    result = main(["preflight", "--from-git"])
    assert result == 0


def test_recent_failures_excludes_test_first_contract(tmp_path, monkeypatch, capsys):
    """test_first_contract must not appear in recent_failures either."""
    _init_and_session(tmp_path)
    main(["wrap", "--failure-origin", "test_first_contract",
          "--verification-scope", "package",
          "--scope-path", str(tmp_path),
          "--", sys.executable, "-c", "import sys; sys.exit(1)"])
    capsys.readouterr()
    main(["preflight", "--scope-path", str(tmp_path), "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    for f in d.get("recent_failures", []):
        assert f["effective_failure_origin"] != "test_first_contract"


def test_recent_failures_excludes_synthetic(tmp_path, monkeypatch, capsys):
    """synthetic must not appear in recent_failures."""
    _init_and_session(tmp_path)
    main(["wrap", "--failure-origin", "synthetic",
          "--verification-scope", "package",
          "--scope-path", str(tmp_path),
          "--", sys.executable, "-c", "import sys; sys.exit(1)"])
    capsys.readouterr()
    main(["preflight", "--scope-path", str(tmp_path), "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    for f in d.get("recent_failures", []):
        assert f["effective_failure_origin"] != "synthetic"
