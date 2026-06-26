"""Tests for the Consequence Observation Ledger v0 (v0.32)."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

from chimera_memory.cli import main
from chimera_memory.consequence_observation import (
    append_new_observations,
    read_consequence_observations,
    scan_observations,
)
from chimera_memory.harness_run import HarnessRun, append_harness_run
from chimera_memory.storage import MemoryStore
from chimera_memory.work_brief import add_work_brief, build_work_brief
from chimera_memory.work_session import append_session_event, build_session_event, make_session_id

_PY = sys.executable
_FORBIDDEN_SUB = (
    "safe to merge", "production ready", "production-ready", "certified", "approved",
    "guaranteed", "proves correctness", "proves safety", "trusted", "proof-carrying",
    "proof", "optimal", "guaranteed faster",
)
# v0.32 widens the membrane with risk / severity / priority / score / unsafe / blocked.
_FORBIDDEN_WORDS = (
    "healthy", "unhealthy", "pass", "fail", "ready", "not ready", "success", "failure",
    "risk", "severity", "priority", "score", "unsafe", "blocked",
)


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


def _assert_no_forbidden(text: str) -> None:
    low = text.lower()
    for phrase in _FORBIDDEN_SUB:
        assert phrase not in low, f"overclaim phrase leaked: {phrase!r}"
    for word in _FORBIDDEN_WORDS:
        assert not re.search(r"\b" + re.escape(word) + r"\b", low), f"forbidden word: {word!r}"


def _store_fingerprint(root: Path, name: str) -> str | None:
    p = root / ".chimera-memory" / name
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def _seed(root: Path, *, checks: tuple[str, ...] = ()) -> tuple[str, str]:
    store = MemoryStore.from_paths(root=root)
    brief = build_work_brief(
        title="C", objective="O", task_kind="consequence-observation",
        checks=checks, scope_paths=("src/",), tags=("v0.32",),
    )
    add_work_brief(store, brief)
    sid = make_session_id(created_at="2026-06-26T10:00:00+00:00", brief_id=brief.brief_id)
    append_session_event(store, build_session_event(
        session_id=sid, event_kind="started", brief_id=brief.brief_id, tags=("v0.32",),
        created_at="2026-06-26T10:00:00+00:00"))
    return sid, brief.brief_id


def _append_run(
    store: MemoryStore, *, command: str, created_at: str, sid: str | None,
    exit_code: int | None = 0, output_truncated: bool = False,
    redaction_applied: bool = False, check_label: str | None = None,
    tags: tuple[str, ...] = ("v0.32",),
) -> str:
    from chimera_memory.harness_run import make_run_id
    rid = make_run_id(created_at=created_at, command=command, mode="recorded")
    append_harness_run(store, HarnessRun(
        schema_version=1, run_id=rid, created_at=created_at, started_at=None, ended_at=None,
        duration_ms=None, mode="recorded", command=command, cwd=None, exit_code=exit_code,
        status="completed", stdout_preview="", stderr_preview="", stdout_sha256=None,
        stderr_sha256=None, redaction_applied=redaction_applied,
        output_truncated=output_truncated, artifact_refs=(), work_session_id=sid,
        brief_id=None, check_label=check_label, note=None, tags=tags, source="cli",
    ))
    return rid


def _kinds(observations: list) -> set[str]:
    return {o.observation_kind for o in observations}


# --- scan write / dry-run / no-mutation / no-exec / dedupe -------------------

def test_scan_writes_observations_explicitly(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    candidates = scan_observations(store, generated_at="T", work_session_id=sid)
    appended = append_new_observations(store, candidates)
    assert len(appended) >= 1
    assert (tmp_path / ".chimera-memory" / "consequence_observations.jsonl").exists()
    assert "session_without_harness_runs" in _kinds(read_consequence_observations(store))


def test_scan_dry_run_does_not_write(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sid, bid = _seed(tmp_path)
    mem = str(tmp_path / ".chimera-memory")
    code, out = _run(capsys, "consequence", "scan", "--work-session", sid,
                     "--dry-run", "--json", "--memory-dir", mem)
    assert code == 0
    d = json.loads(out)
    assert d["dry_run"] is True and d["scanned_count"] >= 1 and d["recorded_count"] == 0
    assert not (tmp_path / ".chimera-memory" / "consequence_observations.jsonl").exists()


def test_scan_does_not_mutate_harness_or_session_stores(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    _append_run(store, command="pytest", created_at="T1", sid=sid, exit_code=7)
    h_before = _store_fingerprint(tmp_path, "harness_runs.jsonl")
    e_before = _store_fingerprint(tmp_path, "work_session_events.jsonl")
    append_new_observations(store, scan_observations(store, generated_at="T", work_session_id=sid))
    assert _store_fingerprint(tmp_path, "harness_runs.jsonl") == h_before
    assert _store_fingerprint(tmp_path, "work_session_events.jsonl") == e_before


def test_scan_does_not_execute_commands(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    sentinel = tmp_path / "SENTINEL"
    _append_run(store, command=f"touch {sentinel}", created_at="T1", sid=sid, exit_code=0)
    append_new_observations(store, scan_observations(store, generated_at="T", work_session_id=sid))
    assert not sentinel.exists()


def test_scan_deduplicates_deterministically(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    first = append_new_observations(
        store, scan_observations(store, generated_at="T", work_session_id=sid))
    second = append_new_observations(
        store, scan_observations(store, generated_at="LATER", work_session_id=sid))
    assert len(first) >= 1
    assert second == []  # nothing new on re-scan
    assert len(read_consequence_observations(store)) == len(first)


# --- each rule ----------------------------------------------------------------

def test_rule_session_without_harness_runs(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path, checks=("pytest -q",))
    store = MemoryStore.from_paths(root=tmp_path)
    obs = scan_observations(store, generated_at="T", work_session_id=sid)
    a = [o for o in obs if o.observation_kind == "session_without_harness_runs"]
    assert len(a) == 1
    assert a[0].subject == {"type": "work_session", "id": sid}
    assert a[0].suggested_checks == ("pytest -q",)  # from the brief
    assert "src/" in a[0].affected_paths


def test_rule_nonzero_exit(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    rid = _append_run(store, command="pytest", created_at="T1", sid=sid, exit_code=7,
                      check_label="suite")
    obs = scan_observations(store, generated_at="T", work_session_id=sid)
    b = [o for o in obs if o.observation_kind == "harness_run_nonzero_exit_code_observed"]
    assert len(b) == 1 and b[0].evidence_refs == (rid,)
    assert b[0].suggested_checks == ("suite",)
    assert "fail" not in b[0].note.lower()


def test_rule_output_truncated(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    _append_run(store, command="big", created_at="T1", sid=sid, exit_code=0,
                output_truncated=True)
    obs = scan_observations(store, generated_at="T", work_session_id=sid)
    assert "harness_run_output_truncated" in _kinds(obs)


def test_rule_preview_redacted(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    _append_run(store, command="secret", created_at="T1", sid=sid, exit_code=0,
                redaction_applied=True)
    obs = scan_observations(store, generated_at="T", work_session_id=sid)
    assert "harness_run_preview_redacted" in _kinds(obs)


def test_rule_reported_check_without_matching_run(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    # a run that does NOT match the reported check label/command
    _append_run(store, command="ruff", created_at="T1", sid=sid, exit_code=0, check_label="lint")
    append_session_event(store, build_session_event(
        session_id=sid, event_kind="check_reported", check="pytest -q", created_at="T2"))
    obs = scan_observations(store, generated_at="T", work_session_id=sid)
    f = [o for o in obs if o.observation_kind == "reported_check_without_matching_harness_run"]
    assert len(f) == 1 and f[0].suggested_checks == ("pytest -q",)


def test_rule_reported_check_matched_does_not_fire(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    _append_run(store, command="pytest -q", created_at="T1", sid=sid, exit_code=0,
                check_label="pytest -q")
    append_session_event(store, build_session_event(
        session_id=sid, event_kind="check_reported", check="pytest -q", created_at="T2"))
    obs = scan_observations(store, generated_at="T", work_session_id=sid)
    assert "reported_check_without_matching_harness_run" not in _kinds(obs)


# --- list / show filters ------------------------------------------------------

def _record_for(tmp_path: Path) -> str:
    sid, bid = _seed(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    append_new_observations(store, scan_observations(store, generated_at="T", work_session_id=sid))
    return sid


def test_list_filters_and_limit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sid = _record_for(tmp_path)
    mem = str(tmp_path / ".chimera-memory")
    code, out = _run(capsys, "consequence", "list", "--work-session", sid, "--json",
                     "--memory-dir", mem)
    assert code == 0 and json.loads(out)["count"] >= 1
    # kind filter
    _, out = _run(capsys, "consequence", "list", "--kind", "session_without_harness_runs",
                  "--json", "--memory-dir", mem)
    assert all(o["observation_kind"] == "session_without_harness_runs"
               for o in json.loads(out)["consequence_observations"])
    # non-matching brief filter
    _, out = _run(capsys, "consequence", "list", "--brief", "brief_none", "--json",
                  "--memory-dir", mem)
    assert json.loads(out)["consequence_observations"] == []
    # tag + limit
    _, out = _run(capsys, "consequence", "list", "--tag", "v0.32", "--limit", "1", "--json",
                  "--memory-dir", mem)
    assert len(json.loads(out)["consequence_observations"]) <= 1


def test_show_json_and_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sid = _record_for(tmp_path)
    mem = str(tmp_path / ".chimera-memory")
    _, out = _run(capsys, "consequence", "list", "--work-session", sid, "--json",
                  "--memory-dir", mem)
    oid = json.loads(out)["consequence_observations"][0]["observation_id"]
    code, jout = _run(capsys, "consequence", "show", oid, "--json", "--memory-dir", mem)
    assert code == 0 and json.loads(jout)["observation_id"] == oid
    code, tout = _run(capsys, "consequence", "show", oid, "--memory-dir", mem)
    assert code == 0 and "Observation" in tout and oid in tout
    # unknown id
    code, _ = _run(capsys, "consequence", "show", "co_nope", "--memory-dir", mem)
    assert code == 2


def test_list_show_do_not_create_store(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    mem = str(empty / ".chimera-memory")
    code, out = _run(capsys, "consequence", "list", "--json", "--memory-dir", mem)
    assert code == 0 and json.loads(out)["count"] == 0
    assert not (empty / ".chimera-memory").exists()


# --- work-session consequences ------------------------------------------------

def test_work_session_consequences_read_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sid = _record_for(tmp_path)
    mem = str(tmp_path / ".chimera-memory")
    before = _store_fingerprint(tmp_path, "work_session_events.jsonl")
    code, out = _run(capsys, "work-session", "consequences", sid, "--json", "--memory-dir", mem)
    assert code == 0 and json.loads(out)["count"] >= 1
    assert _store_fingerprint(tmp_path, "work_session_events.jsonl") == before


# --- closeout / rollup / work-packet integration ------------------------------

def test_closeout_includes_recorded_observations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sid = _record_for(tmp_path)
    mem = str(tmp_path / ".chimera-memory")
    _, out = _run(capsys, "work-session", "closeout", sid, "--json", "--memory-dir", mem)
    assert len(json.loads(out)["consequence_observations"]) >= 1


def test_rollup_includes_counts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _record_for(tmp_path)
    mem = str(tmp_path / ".chimera-memory")
    _, out = _run(capsys, "work-session", "rollup", "--json", "--memory-dir", mem)
    d = json.loads(out)
    assert d["summary"]["consequence_observation_count"] >= 1
    assert "recent_consequence_observations" in d


def test_work_packet_includes_observations_and_no_auto_scan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sid, bid = _seed(tmp_path)
    mem = str(tmp_path / ".chimera-memory")
    # Before any scan: work-packet must NOT auto-scan (count 0).
    _, out = _run(capsys, "work-packet", "--session", sid, "--json", "--memory-dir", mem)
    assert json.loads(out)["summary"]["consequence_observation_count"] == 0
    assert not (tmp_path / ".chimera-memory" / "consequence_observations.jsonl").exists()
    # After explicit scan: work-packet includes the already-recorded observation.
    _run(capsys, "consequence", "scan", "--work-session", sid, "--memory-dir", mem)
    _, out = _run(capsys, "work-packet", "--session", sid, "--json", "--memory-dir", mem)
    d = json.loads(out)
    assert d["summary"]["consequence_observation_count"] >= 1
    assert len(d["consequence_observations"]) >= 1


# --- MCP read-only ------------------------------------------------------------

def test_mcp_consequence_tools_read_only_and_no_scan() -> None:
    from chimera_memory.mcp_server import ToolPermissions, list_tools
    ro = {t["name"] for t in list_tools(ToolPermissions(allow_write=False, allow_execute=False))}
    assert "chimera_consequence_observation_list" in ro
    assert "chimera_consequence_observation_show" in ro
    rw = {t["name"] for t in list_tools(ToolPermissions(allow_write=True, allow_execute=True))}
    # scan is never exposed through MCP, even with all permissions
    assert not any("consequence" in n and "scan" in n for n in rw)


def test_mcp_consequence_list_show_results(tmp_path: Path) -> None:
    from chimera_memory.mcp_server import ToolPermissions, call_tool
    sid = _record_for(tmp_path)
    perms = ToolPermissions(allow_write=False, allow_execute=False)
    listed = call_tool("chimera_consequence_observation_list",
                       {"work_session_id": sid}, perms=perms, root=tmp_path)
    assert listed["count"] >= 1
    oid = listed["consequence_observations"][0]["observation_id"]
    shown = call_tool("chimera_consequence_observation_show",
                      {"observation_id": oid}, perms=perms, root=tmp_path)
    assert shown["observation_id"] == oid


def test_mcp_consequence_tools_create_no_store(tmp_path: Path) -> None:
    from chimera_memory.mcp_server import ToolPermissions, call_tool
    clean = tmp_path / "clean"
    clean.mkdir()
    perms = ToolPermissions(allow_write=False, allow_execute=False)
    call_tool("chimera_consequence_observation_list", {}, perms=perms, root=clean)
    assert not (clean / ".chimera-memory").exists()


# --- anti-overclaim -----------------------------------------------------------

def test_no_forbidden_wording_in_generated_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sid, bid = _seed(tmp_path, checks=("pytest -q",))
    store = MemoryStore.from_paths(root=tmp_path)
    _append_run(store, command="pytest", created_at="T1", sid=sid, exit_code=7,
                output_truncated=True, redaction_applied=True, check_label="suite")
    mem = str(tmp_path / ".chimera-memory")
    _run(capsys, "consequence", "scan", "--work-session", sid, "--memory-dir", mem)
    # scan json + list md + show md
    _, scan_json = _run(capsys, "consequence", "scan", "--work-session", sid, "--json",
                        "--memory-dir", mem)
    _assert_no_forbidden(scan_json)
    _, list_md = _run(capsys, "consequence", "list", "--work-session", sid, "--memory-dir", mem)
    _assert_no_forbidden(list_md)
    _, list_json = _run(capsys, "consequence", "list", "--work-session", sid, "--json",
                        "--memory-dir", mem)
    obs = json.loads(list_json)["consequence_observations"]
    oid = obs[0]["observation_id"]
    _, show_md = _run(capsys, "consequence", "show", oid, "--memory-dir", mem)
    _assert_no_forbidden(show_md)


def test_doc_has_no_forbidden_wording() -> None:
    doc = Path(__file__).resolve().parents[3] / "docs" / "consequence-observations.md"
    if doc.exists():
        _assert_no_forbidden(doc.read_text(encoding="utf-8"))
