"""Tests for claim contract validation (v0.22.1)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from chimera_memory.claim_lock import (
    ClaimSpec,
    lock_claim,
    validate_claim_spec,
    WARNING_BROAD_COMMAND,
    WARNING_MISSING_MUST_NOT_BREAK,
    WARNING_BROAD_SCOPE,
)
from chimera_memory.cli import main
from chimera_memory.storage import MemoryStore

_PASS = [sys.executable, "-c", "import sys; sys.exit(0)"]


def _git(tmp_path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t.dev")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _spec(**kw) -> ClaimSpec:
    return ClaimSpec(
        intent=kw.get("intent", "fix x"),
        scope_path=kw.get("scope_path", "src"),
        predicted_outcome=kw.get("predicted_outcome", "all pass"),
        falsifiers=kw.get("falsifiers", [list(_PASS)]),
        must_not_break=kw.get("must_not_break", [list(_PASS)]),
    )


# ── valid explicit claim ────────────────────────────────────────────────────
def test_validate_valid_explicit_claim(repo: Path) -> None:
    result = validate_claim_spec(_spec(), root=repo)
    assert result["valid"] is True
    assert result["errors"] == []


def test_validate_valid_no_warnings_for_explicit_paths(repo: Path) -> None:
    spec = ClaimSpec(
        intent="fix x",
        scope_path="src",
        falsifiers=[["uv", "run", "pytest", "src/tests/test_x.py"]],
        must_not_break=[["uv", "run", "mypy", "src"]],
    )
    result = validate_claim_spec(spec, root=repo)
    assert result["valid"] is True
    broad = [w for w in result["warnings"] if WARNING_BROAD_COMMAND in w]
    assert not broad, f"unexpected BROAD_COMMAND warnings: {broad}"


# ── hard errors ─────────────────────────────────────────────────────────────
def test_validate_rejects_empty_intent(repo: Path) -> None:
    spec = _spec(intent="  ")
    result = validate_claim_spec(spec, root=repo)
    assert result["valid"] is False
    assert any("intent" in e for e in result["errors"])


def test_validate_rejects_no_falsifiers(repo: Path) -> None:
    spec = _spec(falsifiers=[])
    result = validate_claim_spec(spec, root=repo)
    assert result["valid"] is False
    assert any("falsifier" in e for e in result["errors"])


def test_validate_json_schema(repo: Path) -> None:
    result = validate_claim_spec(_spec(), root=repo)
    for key in ("valid", "errors", "warnings"):
        assert key in result
    json.dumps(result)  # must be JSON serialisable


def test_validate_does_not_write_ledger(repo: Path) -> None:
    validate_claim_spec(_spec(), root=repo, check_git_state=False)
    assert not (repo / ".chimera-memory" / "claim_locks.jsonl").exists()


# ── broad-command warnings ───────────────────────────────────────────────────
@pytest.mark.parametrize("cmd", [
    ["mypy"],
    ["uv", "run", "mypy"],
    ["python", "-m", "mypy"],
    ["ruff"],
    ["ruff", "check"],
    ["uv", "run", "ruff"],
    ["uv", "run", "ruff", "check"],
    ["pytest"],
    ["uv", "run", "pytest"],
    ["python", "-m", "pytest"],
])
def test_validate_warns_on_broad_command(repo: Path, cmd: list[str]) -> None:
    spec = _spec(falsifiers=[cmd])
    result = validate_claim_spec(spec, root=repo, check_git_state=False)
    assert result["valid"] is True  # warning, not error
    assert any(WARNING_BROAD_COMMAND in w for w in result["warnings"])


def test_validate_warns_missing_must_not_break(repo: Path) -> None:
    spec = _spec(must_not_break=[])
    result = validate_claim_spec(spec, root=repo, check_git_state=False)
    assert result["valid"] is True
    assert any(WARNING_MISSING_MUST_NOT_BREAK in w for w in result["warnings"])


def test_validate_warns_broad_scope_path(repo: Path) -> None:
    spec = _spec(scope_path=".")
    result = validate_claim_spec(spec, root=repo, check_git_state=False)
    assert result["valid"] is True
    assert any(WARNING_BROAD_SCOPE in w for w in result["warnings"])


# ── lock stores warnings ────────────────────────────────────────────────────
def test_lock_stores_broad_command_warnings(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    spec = _spec(falsifiers=[["pytest"]])
    record = lock_claim(store, spec, root=repo)
    warnings = record["quality"]["warnings"]
    assert any(WARNING_BROAD_COMMAND in w for w in warnings)


def test_lock_json_includes_warnings(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    spec = _spec(falsifiers=[["uv", "run", "pytest"]])
    record = lock_claim(store, spec, root=repo)
    assert isinstance(record["quality"]["warnings"], list)
    assert any(WARNING_BROAD_COMMAND in w for w in record["quality"]["warnings"])


def test_lock_explicit_claim_no_broad_warnings(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    spec = ClaimSpec(
        intent="fix x",
        scope_path="src",
        falsifiers=[["uv", "run", "pytest", "src/tests/"]],
        must_not_break=[["uv", "run", "mypy", "src"]],
    )
    record = lock_claim(store, spec, root=repo)
    broad = [w for w in record["quality"]["warnings"] if WARNING_BROAD_COMMAND in w]
    assert not broad


# ── CLI: claim validate ──────────────────────────────────────────────────────
def test_cli_claim_validate_valid(repo: Path) -> None:
    toml = repo / "claim.toml"
    toml.write_text(
        'intent = "fix x"\nscope_path = "src"\n'
        f'[[falsifiers]]\ncommand = {json.dumps(_PASS)}\n'
        f'[[must_not_break]]\ncommand = {json.dumps(_PASS)}\n'
    )
    assert main(["claim", "validate", "--from-file", str(toml)]) == 0


def test_cli_claim_validate_json(repo: Path, capsys) -> None:
    toml = repo / "claim.toml"
    toml.write_text(
        'intent = "fix x"\nscope_path = "src"\n'
        f'[[falsifiers]]\ncommand = {json.dumps(_PASS)}\n'
    )
    rc = main(["claim", "validate", "--from-file", str(toml), "--json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert data["valid"] is True
    assert "errors" in data
    assert "warnings" in data


def test_cli_claim_validate_rejects_string_command(repo: Path) -> None:
    toml = repo / "claim.toml"
    toml.write_text(
        'intent = "fix x"\nscope_path = "src"\n'
        '[[falsifiers]]\ncommand = "pytest tests/"\n'
    )
    assert main(["claim", "validate", "--from-file", str(toml)]) != 0


def test_cli_claim_validate_warns_on_broad(repo: Path, capsys) -> None:
    toml = repo / "claim.toml"
    toml.write_text(
        'intent = "fix x"\nscope_path = "src"\n'
        '[[falsifiers]]\ncommand = ["pytest"]\n'
    )
    rc = main(["claim", "validate", "--from-file", str(toml)])
    out = capsys.readouterr().out
    assert rc == 0  # warning, not error
    assert "warning" in out.lower() or "broad" in out.lower()


def test_cli_claim_validate_does_not_write_ledger(repo: Path) -> None:
    toml = repo / "claim.toml"
    toml.write_text(
        'intent = "fix x"\nscope_path = "src"\n'
        f'[[falsifiers]]\ncommand = {json.dumps(_PASS)}\n'
    )
    main(["claim", "validate", "--from-file", str(toml)])
    assert not (repo / ".chimera-memory" / "claim_locks.jsonl").exists()


def test_cli_claim_validate_rejects_missing_falsifier(repo: Path) -> None:
    toml = repo / "claim.toml"
    toml.write_text('intent = "fix x"\nscope_path = "src"\n')
    assert main(["claim", "validate", "--from-file", str(toml)]) == 1
