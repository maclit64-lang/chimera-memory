"""Tests for the local MCP tool layer (v0.24)."""
from __future__ import annotations

import json
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest

from chimera_memory.mcp_server import (
    ToolPermissions,
    call_tool,
    list_tools,
    serve_mcp,
)
from chimera_memory.cli import main

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


def _ro() -> ToolPermissions:
    return ToolPermissions()


def _rw() -> ToolPermissions:
    return ToolPermissions(allow_write=True)


def _rx() -> ToolPermissions:
    return ToolPermissions(allow_write=True, allow_execute=True)


# ── permission model ─────────────────────────────────────────────────────────
def test_read_only_exposes_validate_show_list() -> None:
    tools = {t["name"] for t in list_tools(_ro())}
    assert "chimera_claim_validate" in tools
    assert "chimera_claim_show" in tools
    assert "chimera_claim_list" in tools


def test_read_only_hides_write_tools() -> None:
    tools = {t["name"] for t in list_tools(_ro())}
    assert "chimera_claim_lock_auto" not in tools
    assert "chimera_xray_generate" not in tools


def test_read_only_hides_execute_tools() -> None:
    tools = {t["name"] for t in list_tools(_ro())}
    assert "chimera_claim_settle" not in tools


def test_allow_write_exposes_lock_and_xray() -> None:
    tools = {t["name"] for t in list_tools(_rw())}
    assert "chimera_claim_lock_auto" in tools
    assert "chimera_xray_generate" in tools


def test_allow_write_hides_settle() -> None:
    tools = {t["name"] for t in list_tools(_rw())}
    assert "chimera_claim_settle" not in tools


def test_allow_execute_exposes_settle() -> None:
    tools = {t["name"] for t in list_tools(_rx())}
    assert "chimera_claim_settle" in tools


# ── permission gating on call_tool ─────────────────────────────────────────
def test_call_lock_auto_rejected_in_read_only(repo: Path) -> None:
    result = call_tool(
        "chimera_claim_lock_auto",
        {"intent": "fix x", "falsifiers": [_PASS]},
        perms=_ro(), root=repo,
    )
    assert "error" in result
    assert "--allow-write" in result["error"]


def test_call_settle_rejected_without_execute(repo: Path) -> None:
    result = call_tool(
        "chimera_claim_settle",
        {"claim_id": "clm_fake"},
        perms=_rw(), root=repo,
    )
    assert "error" in result
    assert "--allow-execute" in result["error"]


def test_call_unknown_tool_returns_error(repo: Path) -> None:
    result = call_tool("does_not_exist", {}, perms=_ro(), root=repo)
    assert "error" in result


# ── validate tool ───────────────────────────────────────────────────────────
def test_tool_validate_clean_spec(repo: Path) -> None:
    result = call_tool(
        "chimera_claim_validate",
        {"intent": "fix x", "scope_path": "src", "falsifiers": [_PASS]},
        perms=_ro(), root=repo,
    )
    assert result["ok"] is True
    assert result["errors"] == []


def test_tool_validate_catches_missing_falsifier(repo: Path) -> None:
    result = call_tool(
        "chimera_claim_validate",
        {"intent": "fix x", "scope_path": "src", "falsifiers": []},
        perms=_ro(), root=repo,
    )
    assert result["ok"] is False
    assert result["errors"]


def test_tool_validate_does_not_write_ledger(repo: Path) -> None:
    call_tool(
        "chimera_claim_validate",
        {"intent": "fix x", "falsifiers": [_PASS]},
        perms=_ro(), root=repo,
    )
    assert not (repo / ".chimera-memory" / "claim_locks.jsonl").exists()


# ── lock_auto tool ──────────────────────────────────────────────────────────
def test_tool_lock_auto_dry_run_no_ledger(repo: Path) -> None:
    result = call_tool(
        "chimera_claim_lock_auto",
        {"intent": "fix x", "scope_path": "src", "falsifiers": [_PASS], "dry_run": True},
        perms=_rw(), root=repo,
    )
    assert result["dry_run"] is True
    assert result["claim_id"] is None
    assert not (repo / ".chimera-memory" / "claim_locks.jsonl").exists()


def test_tool_lock_auto_creates_claim(repo: Path) -> None:
    result = call_tool(
        "chimera_claim_lock_auto",
        {"intent": "fix x", "scope_path": "src", "falsifiers": [_PASS]},
        perms=_rw(), root=repo,
    )
    assert result["claim_id"] is not None
    assert result["claim_id"].startswith("clm_")
    assert result["status"] == "LOCKED"
    assert result["dry_run"] is False


def test_tool_lock_auto_stores_warnings(repo: Path) -> None:
    # no scope → BROAD_SCOPE_PATH warning
    result = call_tool(
        "chimera_claim_lock_auto",
        {"intent": "fix x", "falsifiers": [_PASS]},
        perms=_rw(), root=repo,
    )
    assert "BROAD_SCOPE_PATH" in " ".join(result["warnings"])


def test_tool_lock_auto_result_is_json_serializable(repo: Path) -> None:
    result = call_tool(
        "chimera_claim_lock_auto",
        {"intent": "fix x", "scope_path": "src", "falsifiers": [_PASS]},
        perms=_rw(), root=repo,
    )
    json.dumps(result)  # must not raise


# ── show/list tools ─────────────────────────────────────────────────────────
def test_tool_claim_list_returns_empty_on_fresh_repo(repo: Path) -> None:
    result = call_tool("chimera_claim_list", {}, perms=_ro(), root=repo)
    assert "claims" in result
    assert isinstance(result["claims"], list)


def test_tool_claim_show_returns_none_for_missing(repo: Path) -> None:
    result = call_tool(
        "chimera_claim_show", {"claim_id": "clm_fake"}, perms=_ro(), root=repo
    )
    assert result["claim"] is None


def test_tool_claim_show_after_lock(repo: Path) -> None:
    lock = call_tool(
        "chimera_claim_lock_auto",
        {"intent": "fix x", "scope_path": "src", "falsifiers": [_PASS]},
        perms=_rw(), root=repo,
    )
    show = call_tool(
        "chimera_claim_show", {"claim_id": lock["claim_id"]}, perms=_ro(), root=repo
    )
    assert show["claim"]["claim_id"] == lock["claim_id"]


def test_tool_claim_list_after_lock(repo: Path) -> None:
    call_tool(
        "chimera_claim_lock_auto",
        {"intent": "fix x", "scope_path": "src", "falsifiers": [_PASS]},
        perms=_rw(), root=repo,
    )
    result = call_tool("chimera_claim_list", {"limit": 10}, perms=_ro(), root=repo)
    assert result["count"] >= 1
    assert any(c["intent"] == "fix x" for c in result["claims"])


# ── settle tool ──────────────────────────────────────────────────────────────
def test_tool_settle_validated(repo: Path) -> None:
    lock = call_tool(
        "chimera_claim_lock_auto",
        {"intent": "fix x", "scope_path": "src", "falsifiers": [_PASS]},
        perms=_rw(), root=repo,
    )
    settle = call_tool(
        "chimera_claim_settle", {"claim_id": lock["claim_id"]},
        perms=_rx(), root=repo,
    )
    assert settle["settlement_status"] in ("VALIDATED", "SCOPE_DRIFT")
    assert "commands" in settle
    assert settle["commands"]


def test_tool_settle_contradicted_on_fail(repo: Path) -> None:
    fail_cmd = [sys.executable, "-c", "import sys;sys.exit(1)"]
    lock = call_tool(
        "chimera_claim_lock_auto",
        {"intent": "fix x", "scope_path": "src", "falsifiers": [fail_cmd]},
        perms=_rw(), root=repo,
    )
    settle = call_tool(
        "chimera_claim_settle", {"claim_id": lock["claim_id"]},
        perms=_rx(), root=repo,
    )
    assert settle["settlement_status"] == "CONTRADICTED"


# ── xray tool ────────────────────────────────────────────────────────────────
def test_tool_xray_returns_ok(repo: Path) -> None:
    result = call_tool(
        "chimera_xray_generate", {"base": "HEAD", "head": "HEAD"},
        perms=_rw(), root=repo,
    )
    assert result["ok"] is True
    assert "verdict" in result


def test_tool_xray_writes_file(repo: Path) -> None:
    out = repo / "PR_EVIDENCE.md"
    call_tool(
        "chimera_xray_generate",
        {"base": "HEAD", "head": "HEAD", "output_path": str(out)},
        perms=_rw(), root=repo,
    )
    assert out.exists()
    text = out.read_text()
    assert "PR Evidence" in text
    assert "Non-Claims" in text


def test_tool_xray_result_is_json_serializable(repo: Path) -> None:
    result = call_tool(
        "chimera_xray_generate", {}, perms=_rw(), root=repo
    )
    json.dumps(result)


# ── tool descriptions honesty ─────────────────────────────────────────────
def test_settle_description_mentions_runs_commands() -> None:
    from chimera_memory.mcp_server import _TOOLS
    settle = next(t for t in _TOOLS if t["name"] == "chimera_claim_settle")
    desc = settle["description"].lower()
    assert "run" in desc or "command" in desc or "execute" in desc


def test_validate_description_says_no_mutation() -> None:
    from chimera_memory.mcp_server import _TOOLS
    v = next(t for t in _TOOLS if t["name"] == "chimera_claim_validate")
    desc = v["description"].lower()
    assert "not" in desc or "no " in desc or "does not" in desc


# ── tool output has no private paths ──────────────────────────────────────
def test_tool_outputs_no_private_chimera_memory_paths(repo: Path) -> None:
    result = call_tool(
        "chimera_claim_list", {"limit": 5}, perms=_ro(), root=repo
    )
    assert ".chimera-memory" not in json.dumps(result)


# ── CLI smoke: mcp serve --help ────────────────────────────────────────────
def test_cli_mcp_serve_help_exists(capsys) -> None:
    try:
        main(["mcp", "serve", "--help"])
    except SystemExit:
        pass
    out = capsys.readouterr().out
    assert "stdio" in out.lower() or "mcp" in out.lower()
    assert "--allow-write" in out
    assert "--allow-execute" in out


def test_cli_mcp_in_top_level_help(capsys) -> None:
    try:
        main(["--help"])
    except SystemExit:
        pass
    out = capsys.readouterr().out
    assert "mcp" in out


# ── MCP protocol smoke ────────────────────────────────────────────────────
def test_mcp_protocol_initialize_and_list_tools(repo: Path, monkeypatch) -> None:
    """Full protocol smoke via serve_mcp with mocked stdio."""
    initialize = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    list_req = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    stdin_data = initialize + "\n" + list_req + "\n"

    output_lines: list[str] = []

    def fake_send(obj: dict) -> None:
        output_lines.append(json.dumps(obj))

    import chimera_memory.mcp_server as _ms
    monkeypatch.setattr(_ms, "_send", fake_send)

    fake_stdin = StringIO(stdin_data)
    monkeypatch.setattr("sys.stdin", fake_stdin)

    perms = ToolPermissions()
    serve_mcp(perms, root=repo)

    assert len(output_lines) >= 2
    init_resp = json.loads(output_lines[0])
    assert init_resp["result"]["protocolVersion"] == "2024-11-05"
    list_resp = json.loads(output_lines[1])
    tool_names = {t["name"] for t in list_resp["result"]["tools"]}
    assert "chimera_claim_validate" in tool_names
    assert "chimera_claim_lock_auto" not in tool_names  # read-only mode


def test_mcp_protocol_call_validate(repo: Path, monkeypatch) -> None:
    initialize = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    call = json.dumps({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {
            "name": "chimera_claim_validate",
            "arguments": {
                "intent": "fix x",
                "scope_path": "src",
                "falsifiers": [_PASS],
            },
        },
    })
    output_lines: list[str] = []
    import chimera_memory.mcp_server as _ms
    monkeypatch.setattr(_ms, "_send", lambda obj: output_lines.append(json.dumps(obj)))
    monkeypatch.setattr("sys.stdin", StringIO(initialize + "\n" + call + "\n"))
    serve_mcp(ToolPermissions(), root=repo)
    call_resp = json.loads(output_lines[1])
    result = json.loads(call_resp["result"]["content"][0]["text"])
    assert result["ok"] is True
