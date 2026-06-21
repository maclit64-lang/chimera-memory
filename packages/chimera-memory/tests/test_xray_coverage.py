"""Evidence Coverage Warnings (L-003B).

Advisory: did the settled evidence obviously target what changed? Conservative —
fires only when source changed, settled commands exist, and none target the
changed source. Never says "untested"; never asserts correctness.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from chimera_memory.cli import main
from chimera_memory.storage import MemoryStore
from chimera_memory.xray import (
    EVIDENCE_GATE_POLICIES,
    _is_source_file,
    evaluate_evidence_gate,
    evidence_coverage_warnings,
    generate_xray,
    render_markdown,
    render_pr_comment,
)

_FORBIDDEN = (
    "untested",
    "not tested",
    "code is wrong",
    "code is unsafe",
    "production-ready",
    "approved",
    "certified",
    "guaranteed",
    "malicious",
    "the agent lied",
)


# ── source-file classification ────────────────────────────────────────────

@pytest.mark.parametrize(
    "path,is_source",
    [
        ("pkg/app.py", True),
        ("src/ui/Button.tsx", True),
        ("svc/main.go", True),
        ("lib/x.rs", True),
        ("tests/test_app.py", False),
        ("pkg/app_test.py", False),
        ("ui/Button.test.ts", False),
        ("docs/guide.md", False),
        ("README.md", False),
        ("config.yaml", False),
        ("pyproject.toml", False),
        ("uv.lock", False),
        ("docs/conf.py", False),
    ],
)
def test_is_source_file(path: str, is_source: bool) -> None:
    assert _is_source_file(path) is is_source


# ── targeting heuristic (constructed settled claims) ──────────────────────

def _claim(scope: str, commands: list[dict]) -> dict:
    return {
        "claim_id": "c1",
        "scope_path": scope,
        "intent": "change",
        "settlement": {"status": "VALIDATED", "commands": commands},
    }


def _cmd(command: list[str], role: str = "falsifier") -> dict:
    return {"command": command, "role": role, "outcome": "PASS", "exit_code": 0, "stdout_excerpt": ""}


def _codes(warnings: list) -> set[str]:
    return {w.code for w in warnings}


def test_source_change_lint_only_warns() -> None:
    w = evidence_coverage_warnings([_claim("pkg", [_cmd(["ruff", "check", "."])])], ["pkg/app.py"])
    assert "NO_TARGETED_EVIDENCE_FOR_CHANGED_SOURCE" in _codes(w)


def test_source_change_generic_global_test_warns() -> None:
    w = evidence_coverage_warnings([_claim("pkg", [_cmd(["pytest"])])], ["pkg/app.py"])
    assert "NO_TARGETED_EVIDENCE_FOR_CHANGED_SOURCE" in _codes(w)


def test_targeted_test_path_no_warning() -> None:
    w = evidence_coverage_warnings(
        [_claim("pkg", [_cmd(["pytest", "tests/test_app.py::test_it"])])], ["pkg/app.py"]
    )
    assert w == []


def test_command_names_changed_file_no_warning() -> None:
    w = evidence_coverage_warnings([_claim("pkg", [_cmd(["mypy", "pkg/app.py"])])], ["pkg/app.py"])
    assert w == []


def test_docs_only_change_no_warning() -> None:
    w = evidence_coverage_warnings([_claim("pkg", [_cmd(["ruff", "check", "."])])], ["docs/guide.md"])
    assert w == []


def test_test_only_change_no_warning() -> None:
    w = evidence_coverage_warnings(
        [_claim("pkg", [_cmd(["ruff", "check", "."])])], ["tests/test_app.py"]
    )
    assert w == []


def test_no_command_evidence_no_warning() -> None:
    # No commands => evidence-dark/unsettled logic handles it, not coverage.
    assert evidence_coverage_warnings([_claim("pkg", [])], ["pkg/app.py"]) == []


def test_warning_text_has_no_forbidden_language() -> None:
    w = evidence_coverage_warnings([_claim("pkg", [_cmd(["ruff", "check", "."])])], ["pkg/app.py"])
    blob = " ".join(f"{x.title} {x.explanation} {x.hint}" for x in w).lower()
    assert blob
    for phrase in _FORBIDDEN:
        assert phrase not in blob


# ── integration via generate_xray / render ────────────────────────────────

def _git(p: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=p, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t.dev")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "app.py").write_text("def f():\n    return 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _append_lint_only(store: MemoryStore) -> None:
    store.append_claim_lock(
        {
            "claim_id": "c1",
            "intent": "tidy",
            "scope_path": "pkg",
            "predicted_outcome": "all pass",
            "falsifiers": [{"command": ["ruff", "check", "."]}],
            "must_not_break": [],
            "settlement": {
                "status": "VALIDATED",
                "settled_at": "2026-06-21T00:00:00+00:00",
                "commands": [_cmd(["ruff", "check", "."])],
                "changed_files": ["pkg/app.py"],
                "scope_drift_files": [],
            },
        }
    )


def test_markdown_section_appears(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    store.initialize()
    (repo / "pkg" / "app.py").write_text("def f():\n    return 2\n")
    _append_lint_only(store)
    md = render_markdown(generate_xray(store, root=repo))
    assert "## Evidence Coverage Warnings" in md
    assert "No obvious targeted evidence" in md
    assert "untested" not in md.lower()


def test_markdown_section_absent_when_targeted(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    store.initialize()
    (repo / "pkg" / "app.py").write_text("def f():\n    return 2\n")
    store.append_claim_lock(
        {
            "claim_id": "c1",
            "intent": "fix",
            "scope_path": "pkg",
            "falsifiers": [{"command": ["pytest", "pkg/app.py"]}],
            "must_not_break": [],
            "settlement": {
                "status": "VALIDATED",
                "commands": [_cmd(["pytest", "pkg/app.py"])],
                "changed_files": ["pkg/app.py"],
                "scope_drift_files": [],
            },
        }
    )
    md = render_markdown(generate_xray(store, root=repo))
    assert "## Evidence Coverage Warnings" not in md


def test_pr_comment_and_json_additive(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    store.initialize()
    (repo / "pkg" / "app.py").write_text("def f():\n    return 2\n")
    _append_lint_only(store)
    result = generate_xray(store, root=repo)
    assert "evidence_coverage_warnings" in result
    assert "evidence_coverage_warnings" in result["counts"]
    # existing fields remain
    for k in ("evidence_quality_warnings", "test_integrity_warnings", "verdict_label", "counts"):
        assert k in result
    comment = render_pr_comment(result)
    assert "Evidence coverage warnings:" in comment
    assert "scores evidence quality, not code correctness" in comment.lower()


# ── gate integration ──────────────────────────────────────────────────────

def _gate_result(coverage: int) -> dict:
    return {
        "verdict_label": "REVIEW REQUIRED",
        "counts": {
            "contradicted": 0,
            "unsettled": 0,
            "scope_drift": 0,
            "evidence_dark_source": 0,
            "evidence_quality_warnings": 0,
            "test_integrity_warnings": 0,
            "evidence_coverage_warnings": coverage,
        },
    }


def test_gate_warnings_includes_coverage() -> None:
    assert not evaluate_evidence_gate(_gate_result(1), fail_on="warnings").passed
    assert evaluate_evidence_gate(_gate_result(0), fail_on="warnings").passed


def test_gate_never_passes_with_coverage() -> None:
    assert evaluate_evidence_gate(_gate_result(3), fail_on="never").passed


def test_gate_specific_coverage_policy() -> None:
    assert "evidence-coverage-warnings" in EVIDENCE_GATE_POLICIES
    assert not evaluate_evidence_gate(_gate_result(1), fail_on="evidence-coverage-warnings").passed
    assert evaluate_evidence_gate(_gate_result(0), fail_on="evidence-coverage-warnings").passed


def test_cli_gate_fails_on_coverage_and_keeps_receipt(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    store.initialize()
    (repo / "pkg" / "app.py").write_text("def f():\n    return 2\n")
    _append_lint_only(store)
    rc = main(["xray", "generate", "--output", "PR_EVIDENCE.md", "--fail-on", "warnings"])
    assert rc == 2
    assert (repo / "PR_EVIDENCE.md").exists()
