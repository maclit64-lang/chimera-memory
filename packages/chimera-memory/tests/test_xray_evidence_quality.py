"""Evidence Quality Warnings (L-003).

Warnings are advisory review prompts derived from already-stored settlement
evidence (command text, outcome, exit code, stdout excerpt). They never claim
code is correct/safe/wrong; they explain why evidence is weak.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from chimera_memory.storage import MemoryStore
from chimera_memory.xray import (
    EvidenceQualityWarning,
    _classify_command,
    _command_shows_zero_tests,
    evidence_quality_warnings,
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
    "the agent lied",
    "guaranteed",
)


# ── command classification ────────────────────────────────────────────────

@pytest.mark.parametrize(
    "cmd,expected",
    [
        (["pytest", "tests/"], "test"),
        (["uv", "run", "pytest", "-q"], "test"),
        (["python", "-m", "pytest", "tests/test_x.py::test_y"], "test"),
        (["go", "test", "./..."], "test"),
        (["cargo", "test"], "test"),
        (["ruff", "check", "."], "lint"),
        (["uv", "run", "ruff", "check", "src"], "lint"),
        (["black", "--check", "."], "lint"),
        (["mypy", "src"], "lint"),
        (["python", "-c", "import sys; sys.exit(0)"], "other"),
        (["./build.sh"], "other"),
    ],
)
def test_classify_command(cmd: list[str], expected: str) -> None:
    assert _classify_command(cmd) == expected


def test_command_shows_zero_tests() -> None:
    assert _command_shows_zero_tests("collected 0 items\n")
    assert _command_shows_zero_tests("no tests ran in 0.01s")
    assert not _command_shows_zero_tests("collected 5 items\n3 passed")
    assert not _command_shows_zero_tests(None)
    assert not _command_shows_zero_tests("")


# ── pure heuristic unit tests (constructed records) ───────────────────────

def _claim(scope: str, intent: str, commands: list[dict]) -> dict:
    return {
        "claim_id": "c1",
        "intent": intent,
        "scope_path": scope,
        "settlement": {"status": "VALIDATED", "commands": commands},
    }


def _cmd(command: list[str], outcome: str = "PASS", stdout: str = "", role: str = "falsifier") -> dict:
    return {
        "command": command,
        "role": role,
        "outcome": outcome,
        "exit_code": 0 if outcome == "PASS" else 1,
        "stdout_excerpt": stdout,
    }


def test_lint_only_warning_fires() -> None:
    claims = [_claim("pkg", "tidy imports", [_cmd(["ruff", "check", "pkg"])])]
    codes = {w.code for w in evidence_quality_warnings(claims, ["pkg/a.py"])}
    assert "LINT_ONLY_EVIDENCE" in codes


def test_zero_tests_collected_warning_fires() -> None:
    claims = [_claim("pkg", "add feature", [_cmd(["pytest", "pkg"], stdout="collected 0 items")])]
    codes = {w.code for w in evidence_quality_warnings(claims, ["pkg/a.py"])}
    assert "ZERO_TESTS_COLLECTED" in codes


def test_green_only_no_regression_warning_fires() -> None:
    claims = [_claim("pkg", "fix null deref crash", [_cmd(["python", "-c", "import sys; sys.exit(0)"])])]
    codes = {w.code for w in evidence_quality_warnings(claims, ["pkg/a.py"])}
    assert "GREEN_ONLY_EVIDENCE" in codes


def test_no_warning_for_targeted_passing_test() -> None:
    """False-positive guard: a real targeted test that collected tests => no warning."""
    claims = [
        _claim(
            "pkg",
            "fix null deref crash",
            [_cmd(["pytest", "pkg/tests/test_x.py::test_crash"], stdout="collected 1 item\n1 passed")],
        )
    ]
    assert evidence_quality_warnings(claims, ["pkg/a.py"]) == []


def test_no_warning_when_no_in_scope_change() -> None:
    claims = [_claim("pkg", "fix bug", [_cmd(["ruff", "check", "pkg"])])]
    # changed file is outside the claim scope => nothing to critique here
    assert evidence_quality_warnings(claims, ["other/z.py"]) == []


def test_warnings_dedupe_per_code() -> None:
    claims = [
        _claim("pkg", "fix bug", [_cmd(["ruff", "check", "pkg"])]),
        _claim("pkg", "fix bug2", [_cmd(["ruff", "check", "pkg"])]),
    ]
    codes = [w.code for w in evidence_quality_warnings(claims, ["pkg/a.py"])]
    assert codes.count("LINT_ONLY_EVIDENCE") == 1


def test_warning_dataclass_shape() -> None:
    w = EvidenceQualityWarning(
        code="X", title="t", severity="advisory", explanation="e", hint="h"
    )
    assert w.code == "X" and w.severity == "advisory"
    assert set(w.to_dict()) == {"code", "title", "severity", "explanation", "hint"}


# ── integration through generate_xray / render_* ──────────────────────────

def _git(p: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=p, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t.dev")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _append(store: MemoryStore, scope: str, intent: str, commands: list[dict]) -> None:
    store.append_claim_lock(
        {
            "claim_id": "c1",
            "intent": intent,
            "scope_path": scope,
            "predicted_outcome": "all pass",
            "falsifiers": [{"command": c["command"]} for c in commands if c["role"] == "falsifier"],
            "must_not_break": [],
            "settlement": {
                "status": "VALIDATED",
                "settled_at": "2026-06-21T00:00:00+00:00",
                "commands": commands,
                "changed_files": ["pkg/a.py"],
                "scope_drift_files": [],
            },
        }
    )


def test_markdown_section_appears_when_warning(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    store.initialize()
    (repo / "pkg" / "a.py").write_text("x = 2\n")
    _append(store, "pkg", "tidy imports", [_cmd(["ruff", "check", "pkg"])])
    md = render_markdown(generate_xray(store, root=repo))
    assert "## Evidence Quality Warnings" in md
    assert "Lint-only" in md


def test_markdown_section_absent_when_no_warning(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    store.initialize()
    (repo / "pkg" / "a.py").write_text("x = 2\n")
    _append(
        store,
        "pkg",
        "fix crash",
        [_cmd(["pytest", "pkg/tests/test_a.py::test_it"], stdout="collected 1 item\n1 passed")],
    )
    md = render_markdown(generate_xray(store, root=repo))
    assert "## Evidence Quality Warnings" not in md


def test_pr_comment_compact_warning_signal(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    store.initialize()
    (repo / "pkg" / "a.py").write_text("x = 2\n")
    _append(store, "pkg", "tidy imports", [_cmd(["ruff", "check", "pkg"])])
    comment = render_pr_comment(generate_xray(store, root=repo))
    assert "Evidence quality warnings:" in comment
    assert "scores evidence quality, not code correctness" in comment.lower()


def test_json_additive_keys_present(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    store.initialize()
    result = generate_xray(store, root=repo)
    # existing keys still present
    for k in ("verdict", "verdict_label", "counts", "settled_claims"):
        assert k in result
    # new additive key
    assert "evidence_quality_warnings" in result
    assert "evidence_quality_warnings" in result["counts"]


def test_no_forbidden_language_in_warning_output(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    store.initialize()
    (repo / "pkg" / "a.py").write_text("x = 2\n")
    _append(store, "pkg", "fix null deref", [_cmd(["ruff", "check", "pkg"])])
    result = generate_xray(store, root=repo)
    warnings = result["evidence_quality_warnings"]
    assert warnings, "expected at least one warning"
    # The warning text the feature emits must carry no affirmative overclaim.
    blob = " ".join(
        " ".join(w[k] for k in ("title", "explanation", "hint")) for w in warnings
    ).lower()
    for phrase in _FORBIDDEN:
        assert phrase not in blob
    md = render_markdown(result)
    assert "## Evidence Quality Warnings" in md
    # advisory framing is present (does not assert wrongness/correctness)
    assert "do not prove the code is wrong or correct" in md.lower()
