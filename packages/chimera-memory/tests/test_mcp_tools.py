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
from chimera_memory.storage import MemoryStore
from chimera_memory.tool_notes import add_tool_note, build_tool_note

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


# ── Stage 5: tool-notes advisory (read-only MCP tool) ────────────────────────

_TN_FORBIDDEN = (
    "safe to merge", "production ready", "production-ready", "certified",
    "approved", "guaranteed", "proves correctness", "proves safety",
    "trusted", "proof-carrying", "proof", "optimal", "guaranteed faster",
)


def _seed_notes(root: Path) -> None:
    store = MemoryStore.from_paths(root=root)
    add_tool_note(store, build_tool_note(
        task_kind="large-repo-forensics", tool_name="parallel-agents",
        workflow_name="unit-card-specialist-fanout", lesson="Use manifests first.",
        tags=("repo-forensics", "orchestration"),
    ))
    add_tool_note(store, build_tool_note(
        task_kind="quick-fix", tool_name="single-agent",
        workflow_name="direct-edit", tags=("small",),
    ))


def test_tool_notes_suggest_listed_read_only() -> None:
    tools = {t["name"] for t in list_tools(_ro())}
    assert "chimera_tool_notes_suggest" in tools


def test_tool_notes_suggest_schema_exposes_filters() -> None:
    t = next(t for t in list_tools(_ro()) if t["name"] == "chimera_tool_notes_suggest")
    props = set(t["inputSchema"]["properties"])
    assert {"task_kind", "tool_name", "workflow_name", "tag"} <= props
    assert t["inputSchema"]["required"] == []
    assert "_permission" not in t


def test_tool_notes_suggest_by_task_kind(tmp_path: Path) -> None:
    _seed_notes(tmp_path)
    r = call_tool("chimera_tool_notes_suggest", {"task_kind": "large-repo-forensics"},
                  perms=_ro(), root=tmp_path)
    assert r["schema_version"] == 1
    assert set(r) == {"schema_version", "advisory", "filters", "suggestions"}
    assert set(r["filters"]) == {"task_kind", "tool_name", "workflow_name", "tag"}
    assert len(r["suggestions"]) == 1
    assert r["suggestions"][0]["tool_name"] == "parallel-agents"


def test_tool_notes_suggest_by_tag_tool_workflow(tmp_path: Path) -> None:
    _seed_notes(tmp_path)

    def count(args: dict) -> int:
        return len(call_tool("chimera_tool_notes_suggest", args, perms=_ro(),
                             root=tmp_path)["suggestions"])

    assert count({"tag": "small"}) == 1
    assert count({"tool_name": "parallel-agents"}) == 1
    assert count({"workflow_name": "direct-edit"}) == 1


def test_tool_notes_suggest_no_match_is_empty(tmp_path: Path) -> None:
    _seed_notes(tmp_path)
    r = call_tool("chimera_tool_notes_suggest", {"task_kind": "nope"}, perms=_ro(), root=tmp_path)
    assert r["suggestions"] == []
    assert set(r) == {"schema_version", "advisory", "filters", "suggestions"}


def test_tool_notes_suggest_is_read_only(tmp_path: Path) -> None:
    _seed_notes(tmp_path)
    mem = tmp_path / ".chimera-memory"
    before = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    call_tool("chimera_tool_notes_suggest", {"task_kind": "large-repo-forensics"},
              perms=_ro(), root=tmp_path)
    call_tool("chimera_tool_notes_suggest", {}, perms=_ro(), root=tmp_path)
    after = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    assert before == after


def test_tool_notes_suggest_does_not_create_store(tmp_path: Path) -> None:
    r = call_tool("chimera_tool_notes_suggest", {"task_kind": "x"}, perms=_ro(), root=tmp_path)
    assert r["suggestions"] == []
    assert not (tmp_path / ".chimera-memory").exists()


def test_tool_notes_suggest_works_without_write_execute_flags(tmp_path: Path) -> None:
    _seed_notes(tmp_path)
    r = call_tool("chimera_tool_notes_suggest", {}, perms=ToolPermissions(), root=tmp_path)
    assert "error" not in r
    assert len(r["suggestions"]) == 2


def test_existing_write_execute_permissions_unchanged(tmp_path: Path) -> None:
    ro_names = {t["name"] for t in list_tools(_ro())}
    assert "chimera_tool_notes_suggest" in ro_names
    assert "chimera_claim_lock_auto" not in ro_names  # still write-gated
    assert "chimera_claim_settle" not in ro_names      # still execute-gated
    err = call_tool("chimera_claim_lock_auto", {"intent": "x", "falsifiers": [["true"]]},
                    perms=_ro(), root=tmp_path)
    assert "error" in err and "allow-write" in err["error"]


def test_tool_notes_suggest_no_forbidden_phrases(tmp_path: Path) -> None:
    _seed_notes(tmp_path)
    t = next(t for t in list_tools(_ro()) if t["name"] == "chimera_tool_notes_suggest")
    r = call_tool("chimera_tool_notes_suggest", {"task_kind": "large-repo-forensics"},
                  perms=_ro(), root=tmp_path)
    blob = (t["description"] + json.dumps(r)).lower()
    for phrase in _TN_FORBIDDEN:
        assert phrase not in blob, f"overclaim phrase leaked: {phrase!r}"


# ── Stage 6: write-gated tool-note add ───────────────────────────────────────

def test_tool_note_add_is_write_classified() -> None:
    ro_names = {t["name"] for t in list_tools(_ro())}
    rw_names = {t["name"] for t in list_tools(_rw())}
    assert "chimera_tool_note_add" not in ro_names   # hidden under read-only
    assert "chimera_tool_note_add" in rw_names        # visible with --allow-write
    t = next(t for t in list_tools(_rw()) if t["name"] == "chimera_tool_note_add")
    assert t["inputSchema"]["required"] == ["task_kind", "tool_name", "lesson"]
    assert "_permission" not in t


def test_tool_note_add_blocked_under_read_only(tmp_path: Path) -> None:
    err = call_tool("chimera_tool_note_add",
                    {"task_kind": "k", "tool_name": "t", "lesson": "l"},
                    perms=_ro(), root=tmp_path)
    assert "error" in err and "allow-write" in err["error"]
    assert not (tmp_path / ".chimera-memory").exists()  # blocked before any write


def test_tool_note_add_with_write_adds_note(tmp_path: Path) -> None:
    res = call_tool("chimera_tool_note_add", {
        "task_kind": "large-repo-forensics", "tool_name": "parallel-agents",
        "workflow_name": "unit-card-specialist-fanout", "lesson": "Use manifests first.",
        "tags": ["repo-forensics", "orchestration"],
    }, perms=_rw(), root=tmp_path)
    assert set(res) == {"schema_version", "tool_note", "written_to"}
    assert res["written_to"] == "tool_notes.jsonl"
    assert res["tool_note"]["note_id"].startswith("tn_")
    assert res["tool_note"]["tags"] == ["repo-forensics", "orchestration"]  # round-trip


def test_added_note_visible_via_suggest(tmp_path: Path) -> None:
    call_tool("chimera_tool_note_add", {"task_kind": "k", "tool_name": "t", "lesson": "l"},
              perms=_rw(), root=tmp_path)
    sg = call_tool("chimera_tool_notes_suggest", {"task_kind": "k"}, perms=_ro(), root=tmp_path)
    assert len(sg["suggestions"]) == 1


def test_added_note_visible_via_cli_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    call_tool("chimera_tool_note_add", {"task_kind": "k", "tool_name": "t", "lesson": "l"},
              perms=_rw(), root=tmp_path)
    code = main(["tool-notes", "list", "--json", "--memory-dir", str(tmp_path / ".chimera-memory")])
    out = capsys.readouterr().out
    assert code == 0
    assert len(json.loads(out)["tool_notes"]) == 1


def test_tool_note_add_rejects_missing_required(tmp_path: Path) -> None:
    for args in (
        {"tool_name": "t", "lesson": "l"},      # no task_kind
        {"task_kind": "k", "lesson": "l"},       # no tool_name
        {"task_kind": "k", "tool_name": "t"},    # no lesson
    ):
        r = call_tool("chimera_tool_note_add", args, perms=_rw(), root=tmp_path)
        assert "error" in r and "missing required" in r["error"]
    assert not (tmp_path / ".chimera-memory").exists()  # invalid input never writes


def test_tool_note_add_writes_only_tool_notes_file(tmp_path: Path) -> None:
    call_tool("chimera_tool_note_add", {"task_kind": "k", "tool_name": "t", "lesson": "l"},
              perms=_rw(), root=tmp_path)
    mem = tmp_path / ".chimera-memory"
    files = sorted(p.name for p in mem.iterdir() if p.is_file())
    assert files == ["tool_notes.jsonl"]
    for ledger in ("claims.jsonl", "outcomes.jsonl", "scores.jsonl",
                   "sessions.jsonl", "integrity.jsonl", "index.sqlite"):
        assert not (mem / ledger).exists()


def test_suggest_stays_read_only_alongside_write_tool(tmp_path: Path) -> None:
    r = call_tool("chimera_tool_notes_suggest", {}, perms=_ro(), root=tmp_path)
    assert "error" not in r
    assert "chimera_tool_notes_suggest" in {t["name"] for t in list_tools(_ro())}


def test_existing_write_execute_gating_unchanged_stage6() -> None:
    ro_names = {t["name"] for t in list_tools(_ro())}
    assert "chimera_claim_lock_auto" not in ro_names
    assert "chimera_xray_generate" not in ro_names
    assert "chimera_claim_settle" not in ro_names
    # write alone must not expose execute tools
    rw_names = {t["name"] for t in list_tools(_rw())}
    assert "chimera_claim_settle" not in rw_names


def test_tool_note_add_no_forbidden_phrases(tmp_path: Path) -> None:
    t = next(t for t in list_tools(_rw()) if t["name"] == "chimera_tool_note_add")
    res = call_tool("chimera_tool_note_add",
                    {"task_kind": "k", "tool_name": "t", "lesson": "l", "tags": ["x"]},
                    perms=_rw(), root=tmp_path)
    blob = (t["description"] + json.dumps(res)).lower()
    for phrase in _TN_FORBIDDEN:
        assert phrase not in blob, f"overclaim phrase leaked: {phrase!r}"


# ── v1 closeout: MCP show + suggest limit ────────────────────────────────────

def test_tool_note_show_listed_read_only() -> None:
    assert "chimera_tool_note_show" in {t["name"] for t in list_tools(_ro())}


def test_mcp_show_found_and_missing(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    note = build_tool_note(task_kind="k", tool_name="t", workflow_name="w", lesson="l")
    add_tool_note(store, note)
    found = call_tool("chimera_tool_note_show", {"note_id": note.note_id}, perms=_ro(), root=tmp_path)
    assert found["found"] is True
    assert found["tool_note"]["note_id"] == note.note_id
    missing = call_tool("chimera_tool_note_show", {"note_id": "tn_nope"}, perms=_ro(), root=tmp_path)
    assert missing == {"schema_version": 1, "tool_note": None, "found": False}


def test_mcp_show_does_not_create_store(tmp_path: Path) -> None:
    r = call_tool("chimera_tool_note_show", {"note_id": "tn_x"}, perms=_ro(), root=tmp_path)
    assert r["found"] is False
    assert not (tmp_path / ".chimera-memory").exists()


def test_mcp_suggest_limit(tmp_path: Path) -> None:
    _seed_notes(tmp_path)  # two notes
    r = call_tool("chimera_tool_notes_suggest", {"limit": 1}, perms=_ro(), root=tmp_path)
    assert len(r["suggestions"]) == 1
    r0 = call_tool("chimera_tool_notes_suggest", {"limit": 0}, perms=_ro(), root=tmp_path)
    assert r0["suggestions"] == []


# ── tool activity + candidate lessons (MCP) ──────────────────────────────────

def test_tool_activity_add_is_write_classified() -> None:
    assert "chimera_tool_activity_add" not in {t["name"] for t in list_tools(_ro())}
    assert "chimera_tool_activity_add" in {t["name"] for t in list_tools(_rw())}


def test_tool_note_candidates_listed_read_only() -> None:
    assert "chimera_tool_note_candidates" in {t["name"] for t in list_tools(_ro())}


def test_mcp_activity_add_blocked_read_only(tmp_path: Path) -> None:
    err = call_tool("chimera_tool_activity_add",
                    {"task_kind": "k", "tool_name": "t", "summary": "s"},
                    perms=_ro(), root=tmp_path)
    assert "error" in err and "allow-write" in err["error"]
    assert not (tmp_path / ".chimera-memory").exists()


def test_mcp_activity_add_requires_fields(tmp_path: Path) -> None:
    r = call_tool("chimera_tool_activity_add", {"task_kind": "k"}, perms=_rw(), root=tmp_path)
    assert "error" in r and "missing required" in r["error"]
    assert not (tmp_path / ".chimera-memory").exists()


def test_mcp_activity_add_writes_only_activity_file_then_candidates(tmp_path: Path) -> None:
    res = call_tool("chimera_tool_activity_add", {
        "task_kind": "large-repo-forensics", "tool_name": "parallel-agents",
        "workflow_name": "unit-card-specialist-fanout", "summary": "did X.",
        "tags": ["repo-forensics"], "duration_seconds": 12094, "cost_units": 55.51,
    }, perms=_rw(), root=tmp_path)
    assert set(res) == {"schema_version", "tool_activity", "written_to"}
    assert res["written_to"] == "tool_activity.jsonl"
    files = sorted(p.name for p in (tmp_path / ".chimera-memory").iterdir() if p.is_file())
    assert files == ["tool_activity.jsonl"]
    c = call_tool("chimera_tool_note_candidates", {"task_kind": "large-repo-forensics"},
                  perms=_ro(), root=tmp_path)
    assert set(c) == {"schema_version", "advisory", "filters", "candidates"}
    assert len(c["candidates"]) == 1
    assert c["candidates"][0]["lesson"] == "did X."


def test_mcp_candidates_does_not_create_store(tmp_path: Path) -> None:
    c = call_tool("chimera_tool_note_candidates", {"task_kind": "x"}, perms=_ro(), root=tmp_path)
    assert c["candidates"] == []
    assert not (tmp_path / ".chimera-memory").exists()


def test_mcp_activity_no_forbidden_phrases(tmp_path: Path) -> None:
    ta = next(t for t in list_tools(_rw()) if t["name"] == "chimera_tool_activity_add")
    tc = next(t for t in list_tools(_ro()) if t["name"] == "chimera_tool_note_candidates")
    r = call_tool("chimera_tool_activity_add", {"task_kind": "k", "tool_name": "t", "summary": "s"},
                  perms=_rw(), root=tmp_path)
    c = call_tool("chimera_tool_note_candidates", {}, perms=_ro(), root=tmp_path)
    blob = (ta["description"] + tc["description"] + json.dumps(r) + json.dumps(c)).lower()
    for phrase in _TN_FORBIDDEN:
        assert phrase not in blob, f"overclaim phrase leaked: {phrase!r}"


# ── candidate read improvements (filters / limit / show) ─────────────────────

def _seed_two_activities(tmp_path: Path) -> None:
    from chimera_memory.storage import MemoryStore
    from chimera_memory.tool_activity import add_tool_activity, build_tool_activity
    store = MemoryStore.from_paths(root=tmp_path)
    add_tool_activity(store, build_tool_activity(
        task_kind="large-repo-forensics", tool_name="parallel-agents",
        workflow_name="unit-card-specialist-fanout", summary="did A", tags=("repo-forensics",)))
    add_tool_activity(store, build_tool_activity(
        task_kind="quick-fix", tool_name="single-agent",
        workflow_name="direct-edit", summary="did B", tags=("small",)))


def test_mcp_candidates_supports_filters_and_limit(tmp_path: Path) -> None:
    _seed_two_activities(tmp_path)

    def count(args: dict[str, object]) -> int:
        return len(call_tool("chimera_tool_note_candidates", args, perms=_ro(),
                             root=tmp_path)["candidates"])

    assert count({}) == 2
    assert count({"tool_name": "single-agent"}) == 1
    assert count({"workflow_name": "unit-card-specialist-fanout"}) == 1
    assert count({"tag": "repo-forensics"}) == 1
    assert count({"task_kind": "large-repo-forensics", "tag": "small"}) == 0  # AND
    assert count({"limit": 1}) == 1
    assert count({"limit": 0}) == 0
    c = call_tool("chimera_tool_note_candidates", {"tool_name": "single-agent", "limit": 5},
                  perms=_ro(), root=tmp_path)
    assert c["filters"] == {"task_kind": None, "tool_name": "single-agent",
                            "workflow_name": None, "tag": None, "limit": 5}


def test_mcp_candidate_show_listed_read_only() -> None:
    assert "chimera_tool_note_candidate_show" in {t["name"] for t in list_tools(_ro())}


def test_mcp_candidate_show_found_and_missing(tmp_path: Path) -> None:
    _seed_two_activities(tmp_path)
    cid = call_tool("chimera_tool_note_candidates", {"task_kind": "quick-fix"},
                    perms=_ro(), root=tmp_path)["candidates"][0]["candidate_id"]
    found = call_tool("chimera_tool_note_candidate_show", {"candidate_id": cid},
                      perms=_ro(), root=tmp_path)
    assert set(found) == {"schema_version", "candidate", "found"}
    assert found["found"] is True
    assert found["candidate"]["candidate_id"] == cid
    missing = call_tool("chimera_tool_note_candidate_show", {"candidate_id": "cand_nope"},
                        perms=_ro(), root=tmp_path)
    assert missing == {"schema_version": 1, "candidate": None, "found": False}


def test_mcp_candidate_show_does_not_create_store(tmp_path: Path) -> None:
    r = call_tool("chimera_tool_note_candidate_show", {"candidate_id": "cand_x"},
                  perms=_ro(), root=tmp_path)
    assert r["found"] is False
    assert not (tmp_path / ".chimera-memory").exists()


def test_mcp_candidate_show_no_forbidden_phrases(tmp_path: Path) -> None:
    t = next(x for x in list_tools(_ro()) if x["name"] == "chimera_tool_note_candidate_show")
    r = call_tool("chimera_tool_note_candidate_show", {"candidate_id": "cand_x"},
                  perms=_ro(), root=tmp_path)
    blob = (t["description"] + json.dumps(r)).lower()
    for phrase in _TN_FORBIDDEN:
        assert phrase not in blob, f"overclaim phrase leaked: {phrase!r}"


# ── work packet (read-only MCP tool) ─────────────────────────────────────────

def test_mcp_work_packet_listed_read_only() -> None:
    assert "chimera_work_packet" in {t["name"] for t in list_tools(_ro())}


def test_mcp_work_packet_returns_packet(tmp_path: Path) -> None:
    from chimera_memory.storage import MemoryStore
    from chimera_memory.tool_activity import add_tool_activity, build_tool_activity
    from chimera_memory.tool_notes import add_tool_note, build_tool_note
    store = MemoryStore.from_paths(root=tmp_path)
    add_tool_note(store, build_tool_note(
        task_kind="large-repo-forensics", tool_name="pa", workflow_name="wf",
        lesson="L", tags=("repo-forensics",)))
    add_tool_activity(store, build_tool_activity(
        task_kind="large-repo-forensics", tool_name="pa", workflow_name="wf",
        summary="S", tags=("repo-forensics",)))
    d = call_tool("chimera_work_packet",
                  {"task_kind": "large-repo-forensics", "tag": "repo-forensics",
                   "limit_candidates": 5}, perms=_ro(), root=tmp_path)
    assert d["schema_version"] == 1
    assert d["artifact"] == "chimera_work_packet"
    assert set(d["summary"]) == {
        "event_count", "settled_claim_count", "shown_claim_count", "open_or_unresolved_count",
        "next_inspection_target_count", "tool_note_count", "candidate_count",
    }
    assert len(d["tool_notes"]) == 1
    assert len(d["candidate_tool_lessons"]) == 1


def test_mcp_work_packet_does_not_create_store(tmp_path: Path) -> None:
    d = call_tool("chimera_work_packet", {}, perms=_ro(), root=tmp_path)
    assert d["summary"]["tool_note_count"] == 0
    assert not (tmp_path / ".chimera-memory").exists()


def test_mcp_work_packet_no_forbidden_phrases(tmp_path: Path) -> None:
    t = next(x for x in list_tools(_ro()) if x["name"] == "chimera_work_packet")
    d = call_tool("chimera_work_packet", {}, perms=_ro(), root=tmp_path)
    blob = (t["description"] + json.dumps(d)).lower()
    for phrase in _TN_FORBIDDEN:
        assert phrase not in blob, f"overclaim phrase leaked: {phrase!r}"


# ── work packet review thread (read-only MCP tools) ──────────────────────────

def _seed_thread(tmp_path: Path) -> Path:
    from datetime import UTC, datetime, timedelta

    from chimera_memory.storage import MemoryStore
    from chimera_memory.tool_notes import add_tool_note, build_tool_note
    from chimera_memory.work_packet import add_thread_snapshot, build_work_packet
    store = MemoryStore.from_paths(root=tmp_path)
    add_tool_note(store, build_tool_note(task_kind="k", tool_name="t", workflow_name="w",
                                         lesson="L"))
    td = tmp_path / "thread"
    t0 = datetime(2026, 6, 25, 10, 0, 0, tzinfo=UTC)
    add_thread_snapshot(build_work_packet(store, generated_at=t0.isoformat()),
                        thread_dir=td, store_label="ws", now=t0, label="first")
    add_tool_note(store, build_tool_note(task_kind="k2", tool_name="t2", lesson="L2"))
    t1 = t0 + timedelta(seconds=5)
    add_thread_snapshot(build_work_packet(store, generated_at=t1.isoformat()),
                        thread_dir=td, store_label="ws", now=t1, label="second")
    return td


def test_mcp_thread_tools_listed_read_only() -> None:
    names = {t["name"] for t in list_tools(_ro())}
    assert "chimera_work_packet_thread_list" in names
    assert "chimera_work_packet_thread_inspect" in names
    assert "chimera_work_packet_thread_diff_latest" in names


def test_mcp_thread_list_inspect_diff(tmp_path: Path) -> None:
    td = _seed_thread(tmp_path)
    lst = call_tool("chimera_work_packet_thread_list", {"thread_dir": str(td)},
                    perms=_ro(), root=tmp_path)
    assert lst["artifact"] == "chimera_work_packet_thread"
    assert lst["snapshot_count"] == 2
    ins = call_tool("chimera_work_packet_thread_inspect", {"thread_dir": str(td)},
                    perms=_ro(), root=tmp_path)
    assert ins["valid"] is True
    diff = call_tool("chimera_work_packet_thread_diff_latest", {"thread_dir": str(td)},
                     perms=_ro(), root=tmp_path)
    assert diff["artifact"] == "chimera_work_packet_diff"
    assert diff["summary_delta"]["tool_note_count"] == 1


def test_mcp_thread_list_missing_returns_error(tmp_path: Path) -> None:
    r = call_tool("chimera_work_packet_thread_list", {"thread_dir": str(tmp_path / "nope")},
                  perms=_ro(), root=tmp_path)
    assert "error" in r


def test_mcp_thread_reads_do_not_create_store_or_mutate(tmp_path: Path) -> None:
    td = _seed_thread(tmp_path)
    mem = tmp_path / ".chimera-memory"
    store_snap = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    thread_snap = sorted((str(p.relative_to(td)), p.stat().st_size)
                         for p in td.rglob("*") if p.is_file())
    for name in ("chimera_work_packet_thread_list", "chimera_work_packet_thread_inspect",
                 "chimera_work_packet_thread_diff_latest"):
        call_tool(name, {"thread_dir": str(td)}, perms=_ro(), root=tmp_path)
    assert {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()} == store_snap
    assert sorted((str(p.relative_to(td)), p.stat().st_size)
                  for p in td.rglob("*") if p.is_file()) == thread_snap
    # an empty root is not turned into a store by a thread read
    empty = tmp_path / "empty"
    empty.mkdir()
    call_tool("chimera_work_packet_thread_inspect", {"thread_dir": str(empty / "t")},
              perms=_ro(), root=empty)
    assert not (empty / ".chimera-memory").exists()


def test_mcp_thread_tools_no_forbidden_phrases(tmp_path: Path) -> None:
    td = _seed_thread(tmp_path)
    blob = ""
    for name in ("chimera_work_packet_thread_list", "chimera_work_packet_thread_inspect",
                 "chimera_work_packet_thread_diff_latest"):
        t = next(x for x in list_tools(_ro()) if x["name"] == name)
        r = call_tool(name, {"thread_dir": str(td)}, perms=_ro(), root=tmp_path)
        blob += t["description"] + json.dumps(r)
    low = blob.lower()
    for phrase in _TN_FORBIDDEN:
        assert phrase not in low, f"overclaim phrase leaked: {phrase!r}"


# ── branch primer (read-only MCP tool) ───────────────────────────────────────

def _seed_primer_thread(tmp_path: Path) -> Path:
    from datetime import UTC, datetime, timedelta

    from chimera_memory.storage import MemoryStore
    from chimera_memory.tool_notes import add_tool_note, build_tool_note
    from chimera_memory.work_packet import add_thread_snapshot, build_work_packet
    store = MemoryStore.from_paths(root=tmp_path)
    add_tool_note(store, build_tool_note(task_kind="k", tool_name="t", workflow_name="w",
                                         lesson="L"))
    td = tmp_path / "rt"
    t0 = datetime(2026, 6, 25, 10, 0, 0, tzinfo=UTC)
    add_thread_snapshot(build_work_packet(store, generated_at=t0.isoformat()),
                        thread_dir=td, store_label="ws", now=t0, label="first")
    add_tool_note(store, build_tool_note(task_kind="k2", tool_name="t2", lesson="L2"))
    t1 = t0 + timedelta(seconds=5)
    add_thread_snapshot(build_work_packet(store, generated_at=t1.isoformat()),
                        thread_dir=td, store_label="ws", now=t1, label="second")
    return td


def test_mcp_branch_primer_listed_read_only() -> None:
    assert "chimera_branch_primer" in {t["name"] for t in list_tools(_ro())}


def test_mcp_branch_primer_returns_primer(tmp_path: Path) -> None:
    _seed_primer_thread(tmp_path)
    d = call_tool("chimera_branch_primer", {"thread_dir": "rt"}, perms=_ro(), root=tmp_path)
    assert d["schema_version"] == 1
    assert d["artifact"] == "chimera_branch_primer"
    assert set(d["summary"]) == {
        "shown_claim_count", "open_or_unresolved_count", "next_inspection_target_count",
        "tool_note_count", "candidate_count", "thread_snapshot_count",
    }
    assert d["summary"]["thread_snapshot_count"] == 2
    assert d["latest_thread_delta"]["artifact"] == "chimera_work_packet_diff"


def test_mcp_branch_primer_invalid_thread_returns_error(tmp_path: Path) -> None:
    r = call_tool("chimera_branch_primer", {"thread_dir": "nope"}, perms=_ro(), root=tmp_path)
    assert "error" in r


def test_mcp_branch_primer_no_store_creation_or_mutation(tmp_path: Path) -> None:
    td = _seed_primer_thread(tmp_path)
    mem = tmp_path / ".chimera-memory"
    store_snap = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    thread_snap = sorted((str(p.relative_to(td)), p.stat().st_size)
                         for p in td.rglob("*") if p.is_file())
    call_tool("chimera_branch_primer", {"thread_dir": "rt"}, perms=_ro(), root=tmp_path)
    assert {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()} == store_snap
    assert sorted((str(p.relative_to(td)), p.stat().st_size)
                  for p in td.rglob("*") if p.is_file()) == thread_snap
    empty = tmp_path / "empty"
    empty.mkdir()
    call_tool("chimera_branch_primer", {}, perms=_ro(), root=empty)
    assert not (empty / ".chimera-memory").exists()


def test_mcp_branch_primer_no_forbidden_phrases(tmp_path: Path) -> None:
    _seed_primer_thread(tmp_path)
    t = next(x for x in list_tools(_ro()) if x["name"] == "chimera_branch_primer")
    r = call_tool("chimera_branch_primer", {"thread_dir": "rt"}, perms=_ro(), root=tmp_path)
    blob = (t["description"] + json.dumps(r)).lower()
    for phrase in _TN_FORBIDDEN:
        assert phrase not in blob, f"overclaim phrase leaked: {phrase!r}"
