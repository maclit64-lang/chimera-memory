"""Tests for the agent-seam auto-lock primitive (v0.23)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from chimera_memory.claim_lock import (
    ClaimError,
    build_claim_spec_from_auto_inputs,
    WARNING_BROAD_SCOPE,
    WARNING_AUTO_FROM_CHECKS,
    WARNING_MISSING_TARGETED_FALSIFIER,
)
from chimera_memory.cli import main
from chimera_memory.storage import MemoryStore

_PASS_CMD = [sys.executable, "-c", "import sys; sys.exit(0)"]
_PASS_JSON = json.dumps([_PASS_CMD])
_MNB_JSON = json.dumps([[sys.executable, "-c", "pass"]])


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


# ── build_claim_spec_from_auto_inputs ────────────────────────────────────────
def test_auto_reads_chimera_intent(repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHIMERA_INTENT", "fix x")
    monkeypatch.setenv("CHIMERA_SCOPE_PATH", "src")
    monkeypatch.setenv("CHIMERA_FALSIFIERS_JSON", _PASS_JSON)
    spec, _ = build_claim_spec_from_auto_inputs(root=repo)
    assert spec.intent == "fix x"


def test_auto_reads_chimera_scope_path(repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHIMERA_INTENT", "fix x")
    monkeypatch.setenv("CHIMERA_SCOPE_PATH", "packages/cart")
    monkeypatch.setenv("CHIMERA_FALSIFIERS_JSON", _PASS_JSON)
    spec, _ = build_claim_spec_from_auto_inputs(root=repo)
    assert spec.scope_path == "packages/cart"


def test_auto_reads_chimera_falsifiers_json(repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHIMERA_INTENT", "fix x")
    monkeypatch.setenv("CHIMERA_FALSIFIERS_JSON", _PASS_JSON)
    spec, _ = build_claim_spec_from_auto_inputs(root=repo)
    assert spec.falsifiers == [_PASS_CMD]


def test_auto_reads_chimera_must_not_break_json(repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHIMERA_INTENT", "fix x")
    monkeypatch.setenv("CHIMERA_FALSIFIERS_JSON", _PASS_JSON)
    monkeypatch.setenv("CHIMERA_MUST_NOT_BREAK_JSON", _MNB_JSON)
    spec, _ = build_claim_spec_from_auto_inputs(root=repo)
    assert len(spec.must_not_break) == 1


def test_auto_flag_overrides_env_intent(repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHIMERA_INTENT", "env intent")
    monkeypatch.setenv("CHIMERA_FALSIFIERS_JSON", _PASS_JSON)
    spec, _ = build_claim_spec_from_auto_inputs(intent="flag intent", root=repo)
    assert spec.intent == "flag intent"


def test_auto_flag_overrides_env_scope(repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHIMERA_INTENT", "fix x")
    monkeypatch.setenv("CHIMERA_SCOPE_PATH", "env/scope")
    monkeypatch.setenv("CHIMERA_FALSIFIERS_JSON", _PASS_JSON)
    spec, _ = build_claim_spec_from_auto_inputs(scope_path="flag/scope", root=repo)
    assert spec.scope_path == "flag/scope"


def test_auto_fails_when_intent_missing(repo: Path, monkeypatch) -> None:
    monkeypatch.delenv("CHIMERA_INTENT", raising=False)
    monkeypatch.setenv("CHIMERA_FALSIFIERS_JSON", _PASS_JSON)
    with pytest.raises(ClaimError, match="intent"):
        build_claim_spec_from_auto_inputs(root=repo)


def test_auto_fails_on_invalid_falsifiers_json(repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHIMERA_INTENT", "fix x")
    monkeypatch.setenv("CHIMERA_FALSIFIERS_JSON", "not-json")
    with pytest.raises(ClaimError, match="invalid JSON"):
        build_claim_spec_from_auto_inputs(root=repo)


def test_auto_fails_on_non_list_command_in_falsifiers(repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHIMERA_INTENT", "fix x")
    monkeypatch.setenv("CHIMERA_FALSIFIERS_JSON", '["pytest tests/"]')
    with pytest.raises(ClaimError):
        build_claim_spec_from_auto_inputs(root=repo)


def test_auto_fails_when_no_falsifier_source(repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHIMERA_INTENT", "fix x")
    monkeypatch.delenv("CHIMERA_FALSIFIERS_JSON", raising=False)
    with pytest.raises(ClaimError, match="No falsifier source"):
        build_claim_spec_from_auto_inputs(root=repo)


def test_auto_fallback_scope_is_dot_with_warning(repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHIMERA_INTENT", "fix x")
    monkeypatch.setenv("CHIMERA_FALSIFIERS_JSON", _PASS_JSON)
    monkeypatch.delenv("CHIMERA_SCOPE_PATH", raising=False)
    spec, _ = build_claim_spec_from_auto_inputs(root=repo)
    assert spec.scope_path == "."


def test_auto_extra_meta_includes_generated_spec(repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHIMERA_INTENT", "fix x")
    monkeypatch.setenv("CHIMERA_SCOPE_PATH", "src")
    monkeypatch.setenv("CHIMERA_FALSIFIERS_JSON", _PASS_JSON)
    _, meta = build_claim_spec_from_auto_inputs(root=repo)
    assert meta["auto_lock"] is True
    assert "generated_spec" in meta
    assert meta["generated_spec"]["intent"] == "fix x"


def test_auto_from_checks_config(repo: Path, monkeypatch) -> None:
    (repo / "chimera-memory.checks.toml").write_text(
        f'[[checks]]\nname = "test"\ncommand = {json.dumps(_PASS_CMD)}\n'
    )
    monkeypatch.setenv("CHIMERA_INTENT", "fix x")
    monkeypatch.delenv("CHIMERA_FALSIFIERS_JSON", raising=False)
    spec, meta = build_claim_spec_from_auto_inputs(root=repo, from_checks=True)
    assert spec.falsifiers == [_PASS_CMD]
    assert any(WARNING_AUTO_FROM_CHECKS in w for w in meta["extra_warnings"])
    assert any(WARNING_MISSING_TARGETED_FALSIFIER in w for w in meta["extra_warnings"])


# ── CLI: claim lock --auto ───────────────────────────────────────────────────
def test_cli_auto_lock_creates_claim(repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHIMERA_INTENT", "fix x")
    monkeypatch.setenv("CHIMERA_SCOPE_PATH", "src")
    monkeypatch.setenv("CHIMERA_FALSIFIERS_JSON", _PASS_JSON)
    rc = main(["claim", "lock", "--auto"])
    assert rc == 0


def test_cli_auto_lock_json_output(repo: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("CHIMERA_INTENT", "fix x")
    monkeypatch.setenv("CHIMERA_SCOPE_PATH", "src")
    monkeypatch.setenv("CHIMERA_FALSIFIERS_JSON", _PASS_JSON)
    rc = main(["claim", "lock", "--auto", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["auto_lock"] is True
    assert data["claim_id"].startswith("clm_")
    assert data["status"] == "LOCKED"
    assert "generated_spec" in data
    assert "validation" in data
    assert "attribution" in data


def test_cli_auto_lock_stores_validation_warnings(repo: Path, monkeypatch, capsys) -> None:
    # broad scope → BROAD_SCOPE_PATH warning
    monkeypatch.setenv("CHIMERA_INTENT", "fix x")
    monkeypatch.delenv("CHIMERA_SCOPE_PATH", raising=False)
    monkeypatch.setenv("CHIMERA_FALSIFIERS_JSON", _PASS_JSON)
    rc = main(["claim", "lock", "--auto", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    warnings = data["validation"]["warnings"]
    assert any(WARNING_BROAD_SCOPE in w for w in warnings)


def test_cli_auto_lock_dry_run_no_ledger(repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHIMERA_INTENT", "fix x")
    monkeypatch.setenv("CHIMERA_SCOPE_PATH", "src")
    monkeypatch.setenv("CHIMERA_FALSIFIERS_JSON", _PASS_JSON)
    main(["claim", "lock", "--auto", "--dry-run"])
    assert not (repo / ".chimera-memory" / "claim_locks.jsonl").exists()


def test_cli_auto_lock_dry_run_json(repo: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("CHIMERA_INTENT", "fix x")
    monkeypatch.setenv("CHIMERA_SCOPE_PATH", "src")
    monkeypatch.setenv("CHIMERA_FALSIFIERS_JSON", _PASS_JSON)
    rc = main(["claim", "lock", "--auto", "--dry-run", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["dry_run"] is True
    assert data["claim_id"] is None
    assert data["status"] == "DRY_RUN"


def test_cli_auto_lock_fails_missing_intent(repo: Path, monkeypatch) -> None:
    monkeypatch.delenv("CHIMERA_INTENT", raising=False)
    monkeypatch.setenv("CHIMERA_FALSIFIERS_JSON", _PASS_JSON)
    rc = main(["claim", "lock", "--auto"])
    assert rc != 0


def test_cli_auto_lock_flag_intent_overrides_env(repo: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("CHIMERA_INTENT", "env intent")
    monkeypatch.setenv("CHIMERA_SCOPE_PATH", "src")
    monkeypatch.setenv("CHIMERA_FALSIFIERS_JSON", _PASS_JSON)
    rc = main(["claim", "lock", "--auto", "--intent", "flag intent", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["generated_spec"]["intent"] == "flag intent"


def test_cli_auto_lock_save_spec(repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHIMERA_INTENT", "fix x")
    monkeypatch.setenv("CHIMERA_SCOPE_PATH", "src")
    monkeypatch.setenv("CHIMERA_FALSIFIERS_JSON", _PASS_JSON)
    save_path = repo / "generated.toml"
    rc = main(["claim", "lock", "--auto", "--save-spec", str(save_path)])
    assert rc == 0
    assert save_path.exists()
    content = save_path.read_text()
    assert "fix x" in content


# ── regression: file-based lock unchanged ────────────────────────────────────
def test_file_based_lock_unchanged(repo: Path) -> None:
    toml = repo / "claim.toml"
    toml.write_text(
        'intent = "file lock"\nscope_path = "src"\n'
        f'[[falsifiers]]\ncommand = {json.dumps(_PASS_CMD)}\n'
    )
    assert main(["claim", "lock", "--from-file", str(toml)]) == 0
    store = MemoryStore.from_paths(root=repo)
    locks = store.latest_claim_locks()
    assert any(c["intent"] == "file lock" for c in locks)


# ── regression: validate and settlement unchanged ────────────────────────────
def test_validate_unchanged(repo: Path) -> None:
    toml = repo / "claim.toml"
    toml.write_text(
        'intent = "x"\nscope_path = "src"\n'
        f'[[falsifiers]]\ncommand = {json.dumps(_PASS_CMD)}\n'
    )
    assert main(["claim", "validate", "--from-file", str(toml)]) == 0


def test_auto_lock_session_inheritance(repo: Path, monkeypatch) -> None:
    """Session id/agent/model are inherited when a session is active."""
    monkeypatch.setenv("CHIMERA_INTENT", "fix x")
    monkeypatch.setenv("CHIMERA_SCOPE_PATH", "src")
    monkeypatch.setenv("CHIMERA_FALSIFIERS_JSON", _PASS_JSON)
    monkeypatch.setenv("AGENT_NAME", "kiro")
    main(["claim", "lock", "--auto"])
    store = MemoryStore.from_paths(root=repo)
    locks = store.latest_claim_locks()
    lock = next(c for c in locks if c["intent"] == "fix x")
    # attribution block must exist; agent_name should be kiro from env
    assert lock["attribution"]["agent_name"] == "kiro"


def test_auto_lock_unknown_attribution_allowed(repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHIMERA_INTENT", "fix x")
    monkeypatch.setenv("CHIMERA_SCOPE_PATH", "src")
    monkeypatch.setenv("CHIMERA_FALSIFIERS_JSON", _PASS_JSON)
    monkeypatch.delenv("AGENT_NAME", raising=False)
    monkeypatch.delenv("MODEL_NAME", raising=False)
    main(["claim", "lock", "--auto"])
    store = MemoryStore.from_paths(root=repo)
    lock = store.latest_claim_locks()[-1]
    assert lock["attribution"]["agent_name"] is None
    assert lock["attribution"]["attribution_confidence"] == "unknown"
