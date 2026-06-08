"""Tests for v0.26 prompt-derived claim auto-lock."""
from __future__ import annotations

import json
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest

from chimera_memory.hooks import (
    attempt_prompt_auto_lock,
    derive_intent_from_prompt,
    extract_prompt_from_hook_input,
    format_prompt_submit_output,
    load_hooks_config,
)
from chimera_memory.cli import main

_PASS = [sys.executable, "-c", "import sys; sys.exit(0)"]
_PASS_JSON = json.dumps([_PASS])


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


# ── derive_intent_from_prompt ─────────────────────────────────────────────────
def test_derive_intent_preserves_meaningful_text() -> None:
    assert derive_intent_from_prompt("Fix xray reviewer focus regression") == \
        "Fix xray reviewer focus regression"


def test_derive_intent_strips_leading_whitespace() -> None:
    assert derive_intent_from_prompt("  fix xray  ") == "fix xray"


def test_derive_intent_collapses_internal_whitespace() -> None:
    text = "fix   xray\n\nreviewer  focus"
    assert "  " not in derive_intent_from_prompt(text)
    assert "\n" not in derive_intent_from_prompt(text)


def test_derive_intent_removes_please_prefix() -> None:
    result = derive_intent_from_prompt("Please fix the xray bug")
    assert not result.lower().startswith("please")
    assert "xray" in result


def test_derive_intent_removes_can_you_prefix() -> None:
    result = derive_intent_from_prompt("Can you update the hook to lock claims")
    assert not result.lower().startswith("can you")


def test_derive_intent_truncates_long_prompt() -> None:
    long = "a" * 400
    result = derive_intent_from_prompt(long)
    assert len(result) <= 305  # max + suffix


def test_derive_intent_returns_empty_for_empty_input() -> None:
    assert derive_intent_from_prompt("") == ""
    assert derive_intent_from_prompt("   ") == ""


# ── extract_prompt_from_hook_input ────────────────────────────────────────────
def test_extract_prompt_field() -> None:
    raw = json.dumps({"prompt": "fix xray bug"})
    assert extract_prompt_from_hook_input(raw) == "fix xray bug"


def test_extract_user_prompt_field() -> None:
    raw = json.dumps({"user_prompt": "update hook"})
    assert extract_prompt_from_hook_input(raw) == "update hook"


def test_extract_messages_shape() -> None:
    raw = json.dumps({
        "messages": [
            {"role": "assistant", "content": "sure"},
            {"role": "user", "content": "fix the regression"},
        ]
    })
    assert "regression" in extract_prompt_from_hook_input(raw)


def test_extract_raw_text_fallback() -> None:
    assert extract_prompt_from_hook_input("fix xray bug") == "fix xray bug"


def test_extract_empty_returns_empty() -> None:
    assert extract_prompt_from_hook_input("") == ""
    assert extract_prompt_from_hook_input("{}") == ""


def test_extract_malformed_json_returns_raw() -> None:
    result = extract_prompt_from_hook_input("not { valid json")
    assert result  # doesn't crash, returns something


# ── attempt_prompt_auto_lock ──────────────────────────────────────────────────
def test_auto_lock_refuses_without_falsifiers(repo: Path, monkeypatch) -> None:
    monkeypatch.delenv("CHIMERA_FALSIFIERS_JSON", raising=False)
    monkeypatch.delenv("CHIMERA_INTENT", raising=False)
    result = attempt_prompt_auto_lock(
        "fix xray bug",
        env={"CHIMERA_SCOPE_PATH": "src"},
        root=repo,
    )
    assert result["locked"] is False
    assert result["errors"]
    assert "falsifier" in " ".join(result["errors"]).lower()


def test_auto_lock_locks_with_falsifiers(repo: Path) -> None:
    result = attempt_prompt_auto_lock(
        "fix xray bug",
        env={
            "CHIMERA_SCOPE_PATH": "src",
            "CHIMERA_FALSIFIERS_JSON": _PASS_JSON,
        },
        root=repo,
    )
    assert result["locked"] is True
    assert result["claim_id"] and result["claim_id"].startswith("clm_")


def test_auto_lock_uses_prompt_derived_intent(repo: Path) -> None:
    result = attempt_prompt_auto_lock(
        "fix the xray reviewer focus",
        env={"CHIMERA_FALSIFIERS_JSON": _PASS_JSON},
        root=repo,
    )
    assert result["locked"] is True
    assert "xray" in result["intent"].lower()


def test_chimera_intent_overrides_prompt(repo: Path) -> None:
    result = attempt_prompt_auto_lock(
        "do something generic",
        env={
            "CHIMERA_INTENT": "explicit intent wins",
            "CHIMERA_FALSIFIERS_JSON": _PASS_JSON,
        },
        root=repo,
    )
    assert result["intent"] == "explicit intent wins"


def test_auto_lock_skip_env(repo: Path) -> None:
    result = attempt_prompt_auto_lock(
        "fix bug",
        env={
            "CHIMERA_SKIP_AUTOLOCK": "1",
            "CHIMERA_FALSIFIERS_JSON": _PASS_JSON,
        },
        root=repo,
    )
    assert result["attempted"] is False
    assert result["locked"] is False


def test_auto_lock_dry_run_no_ledger(repo: Path) -> None:
    result = attempt_prompt_auto_lock(
        "fix bug",
        env={"CHIMERA_FALSIFIERS_JSON": _PASS_JSON},
        root=repo,
        dry_run=True,
    )
    assert result["dry_run"] is True
    assert result["locked"] is False
    assert not (repo / ".chimera-memory" / "claim_locks.jsonl").exists()


def test_auto_lock_does_not_duplicate_existing_locked(repo: Path) -> None:
    # Lock once
    result1 = attempt_prompt_auto_lock(
        "fix bug",
        env={"CHIMERA_FALSIFIERS_JSON": _PASS_JSON},
        root=repo,
    )
    assert result1["locked"] is True
    # Second prompt — should NOT create another claim
    result2 = attempt_prompt_auto_lock(
        "fix another thing",
        env={"CHIMERA_FALSIFIERS_JSON": _PASS_JSON},
        root=repo,
    )
    assert result2["attempted"] is False
    assert result1["claim_id"] in (result2.get("fallback_message") or "")


def test_auto_lock_every_prompt_override(repo: Path) -> None:
    # Lock once
    attempt_prompt_auto_lock(
        "fix bug",
        env={"CHIMERA_FALSIFIERS_JSON": _PASS_JSON},
        root=repo,
    )
    # Force second lock
    result = attempt_prompt_auto_lock(
        "fix another",
        env={
            "CHIMERA_FALSIFIERS_JSON": _PASS_JSON,
            "CHIMERA_HOOK_AUTOLOCK_EVERY_PROMPT": "1",
        },
        root=repo,
    )
    assert result["locked"] is True


def test_auto_lock_result_is_json_serializable(repo: Path) -> None:
    result = attempt_prompt_auto_lock(
        "fix bug",
        env={"CHIMERA_FALSIFIERS_JSON": _PASS_JSON},
        root=repo,
    )
    json.dumps(result)


# ── .chimera/hooks.toml config ────────────────────────────────────────────────
def test_load_hooks_config_returns_empty_when_missing(repo: Path) -> None:
    assert load_hooks_config(repo) == {}


def test_load_hooks_config_reads_claude_hooks_section(repo: Path) -> None:
    config_dir = repo / ".chimera"
    config_dir.mkdir()
    (config_dir / "hooks.toml").write_text(
        '[claude_hooks]\nscope_path = "packages/cart"\n'
        "falsifiers = [[\"pytest\", \"tests/\"]]\n"
    )
    cfg = load_hooks_config(repo)
    assert cfg["scope_path"] == "packages/cart"
    assert cfg["falsifiers"] == [["pytest", "tests/"]]


def test_auto_lock_uses_config_falsifiers(repo: Path) -> None:
    config_dir = repo / ".chimera"
    config_dir.mkdir()
    (config_dir / "hooks.toml").write_text(
        f'[claude_hooks]\nscope_path = "src"\n'
        f"falsifiers = {json.dumps([_PASS])}\n"
    )
    result = attempt_prompt_auto_lock(
        "fix bug from config",
        env={},  # no env vars
        root=repo,
    )
    assert result["locked"] is True


def test_env_falsifiers_override_config(repo: Path) -> None:
    config_dir = repo / ".chimera"
    config_dir.mkdir()
    fail_cmd = [sys.executable, "-c", "import sys;sys.exit(1)"]
    (config_dir / "hooks.toml").write_text(
        f'[claude_hooks]\nfalsifiers = {json.dumps([fail_cmd])}\n'
    )
    # env provides _PASS, should override config FAIL
    result = attempt_prompt_auto_lock(
        "fix bug",
        env={"CHIMERA_FALSIFIERS_JSON": _PASS_JSON},
        root=repo,
    )
    # would be locked (env wins), then settled with PASS
    assert result["locked"] is True


# ── format_prompt_submit_output ───────────────────────────────────────────────
def test_format_locked_includes_claim_id(repo: Path) -> None:
    result = attempt_prompt_auto_lock(
        "fix bug",
        env={"CHIMERA_FALSIFIERS_JSON": _PASS_JSON},
        root=repo,
    )
    output = format_prompt_submit_output(result)
    assert result["claim_id"] in output


def test_format_no_lock_explains_reason(repo: Path) -> None:
    result = attempt_prompt_auto_lock(
        "fix bug",
        env={},
        root=repo,
    )
    output = format_prompt_submit_output(result)
    assert output.strip()  # non-empty explanation
    assert "falsifier" in output.lower() or "chimera" in output.lower()


# ── CLI: hooks prompt-submit ──────────────────────────────────────────────────
def test_cli_prompt_submit_help(capsys) -> None:
    try:
        main(["hooks", "prompt-submit", "--help"])
    except SystemExit:
        pass
    assert "prompt" in capsys.readouterr().out.lower()


def test_cli_prompt_submit_with_json(repo: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("CHIMERA_FALSIFIERS_JSON", _PASS_JSON)
    payload = json.dumps({"prompt": "fix the xray bug"})
    monkeypatch.setattr("sys.stdin", StringIO(payload))
    rc = main(["hooks", "prompt-submit", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert "locked" in data


def test_cli_prompt_submit_no_falsifiers_exits_zero(repo: Path, monkeypatch) -> None:
    monkeypatch.delenv("CHIMERA_FALSIFIERS_JSON", raising=False)
    payload = json.dumps({"prompt": "fix xray"})
    monkeypatch.setattr("sys.stdin", StringIO(payload))
    # must exit 0 — never block Claude
    assert main(["hooks", "prompt-submit"]) == 0


def test_cli_prompt_submit_malformed_stdin_exits_zero(repo: Path, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdin", StringIO("not json at all"))
    assert main(["hooks", "prompt-submit"]) == 0
