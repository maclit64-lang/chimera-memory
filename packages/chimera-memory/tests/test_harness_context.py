"""Tests for Harness Lite v1 context + packet integration."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

from chimera_memory.cli import main
from chimera_memory.harness_run import (
    append_harness_run,
    build_executed_run,
    build_recorded_run,
    project_harness_candidates,
    read_harness_runs,
)
from chimera_memory.storage import MemoryStore
from chimera_memory.work_brief import add_work_brief, build_work_brief
from chimera_memory.work_session import append_session_event, build_session_event, make_session_id

_PY = sys.executable
_FORBIDDEN_SUB = (
    "safe to merge", "production ready", "production-ready", "certified", "approved",
    "guaranteed", "proves correctness", "proves safety", "trusted", "proof-carrying",
    "proof", "optimal", "guaranteed faster",
)
_FORBIDDEN_WORDS = ("healthy", "unhealthy", "pass", "fail", "ready", "not ready",
                    "success", "failure")


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


def _assert_no_forbidden(text: str) -> None:
    low = text.lower()
    for phrase in _FORBIDDEN_SUB:
        assert phrase not in low, f"overclaim phrase leaked: {phrase!r}"
    for word in _FORBIDDEN_WORDS:
        assert not re.search(r"\b" + re.escape(word) + r"\b", low), f"forbidden word: {word!r}"


def _seed_session(root: Path) -> str:
    store = MemoryStore.from_paths(root=root)
    brief = build_work_brief(title="H", objective="O", task_kind="harness-lite", tags=("v0.30",))
    add_work_brief(store, brief)
    sid = make_session_id(created_at="2026-06-26T10:00:00+00:00", brief_id=brief.brief_id)
    append_session_event(store, build_session_event(
        session_id=sid, event_kind="started", brief_id=brief.brief_id, tags=("v0.30",),
        created_at="2026-06-26T10:00:00+00:00"))
    return sid


# --- Branch Primer + Kickoff Pack --------------------------------------------

def test_primer_includes_harness_runs_and_first_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sid = _seed_session(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    append_harness_run(store, build_recorded_run(
        command="uv run pytest", generated_at="T", exit_code=0, work_session_id=sid,
        check_label="suite"))
    mem = tmp_path / ".chimera-memory"
    code, out = _run(capsys, "branch-primer", "--work-session", sid, "--json",
                     "--memory-dir", str(mem))
    d = json.loads(out)
    assert code == 0
    assert len(d["harness_runs"]) == 1
    assert any("harness list --work-session" in x for x in d["suggested_first_read"])
    md = _run(capsys, "branch-primer", "--work-session", sid, "--memory-dir", str(mem))[1]
    assert "## Harness run observations" in md


def test_primer_read_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sid = _seed_session(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    append_harness_run(store, build_recorded_run(
        command="c", generated_at="T", exit_code=0, work_session_id=sid))
    mem = tmp_path / ".chimera-memory"
    before = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    _run(capsys, "branch-primer", "--work-session", sid, "--json", "--memory-dir", str(mem))
    after = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    assert before == after


def test_kickoff_pack_includes_harness_and_hashes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sid = _seed_session(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    append_harness_run(store, build_recorded_run(
        command="uv run pytest", generated_at="T", exit_code=0, work_session_id=sid,
        check_label="suite"))
    mem = tmp_path / ".chimera-memory"
    out = tmp_path / "kickoff"
    code, _ = _run(capsys, "branch-primer", "bundle", "--output-dir", str(out),
                   "--work-session", sid, "--memory-dir", str(mem))
    assert code == 0
    names = {p.name for p in out.iterdir()}
    assert {"HARNESS_RUNS.md", "harness-runs.json"} <= names
    manifest = json.loads((out / "manifest.json").read_text())
    for entry in manifest["files"]:
        data = (out / entry["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    assert "stdout_preview" not in (out / "HARNESS_RUNS.md").read_text()


# --- Work Packet -------------------------------------------------------------

def test_work_packet_harness_runs_and_counts(tmp_path: Path) -> None:
    sid = _seed_session(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    append_harness_run(store, build_recorded_run(
        command="c", generated_at="T", exit_code=0, work_session_id=sid))
    append_harness_run(store, build_executed_run(
        command=f"{_PY} -c \"print('x')\"", generated_at="T", work_session_id=sid))
    from chimera_memory.work_packet import build_work_packet
    p = build_work_packet(store, generated_at="T", session_id=sid)
    d = p.to_dict()
    assert len(d["harness_runs"]) == 2
    assert d["summary"]["harness_run_count"] == 2
    assert d["summary"]["executed_harness_run_count"] == 1
    assert d["summary"]["recorded_harness_run_count"] == 1


def test_work_packet_session_narrows_harness(tmp_path: Path) -> None:
    sid = _seed_session(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    append_harness_run(store, build_recorded_run(
        command="own", generated_at="T", exit_code=0, work_session_id=sid))
    append_harness_run(store, build_recorded_run(
        command="other", generated_at="T", exit_code=0, work_session_id="sess_other"))
    from chimera_memory.work_packet import build_work_packet
    p = build_work_packet(store, generated_at="T", session_id=sid)
    assert {r["command"] for r in p.to_dict()["harness_runs"]} == {"own"}


def test_work_packet_limit_harness_runs_after_filter(tmp_path: Path) -> None:
    sid = _seed_session(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    for i in range(3):
        append_harness_run(store, build_recorded_run(
            command=f"c{i}", generated_at=f"T{i}", exit_code=0, work_session_id=sid))
    from chimera_memory.work_packet import build_work_packet
    p = build_work_packet(store, generated_at="T", session_id=sid, limit_harness_runs=1)
    assert len(p.to_dict()["harness_runs"]) == 1


def test_work_packet_diff_harness_runs(tmp_path: Path) -> None:
    sid = _seed_session(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    from chimera_memory.work_packet import build_work_packet, diff_packets
    append_harness_run(store, build_recorded_run(
        command="a", generated_at="T0", exit_code=0, work_session_id=sid))
    old = build_work_packet(store, generated_at="T", session_id=sid).to_dict()
    append_harness_run(store, build_recorded_run(
        command="b", generated_at="T1", exit_code=0, work_session_id=sid))
    new = build_work_packet(store, generated_at="T", session_id=sid).to_dict()
    diff = diff_packets(old, new, old_path="a", new_path="b")
    assert "harness_runs" in diff
    assert len(diff["harness_runs"]["added"]) == 1
    assert diff["harness_runs"]["removed"] == []
    assert diff["summary_delta"]["harness_run_count"] == 1


# --- harness candidates ------------------------------------------------------

def test_harness_candidates_contract(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    append_harness_run(store, build_recorded_run(
        command="uv run pytest", generated_at="T", exit_code=7, work_session_id="sess_x",
        check_label="suite", note="Re-run the failing target.", tags=("v0.30",)))
    cands = project_harness_candidates(read_harness_runs(store))
    assert len(cands) == 1
    c = cands[0]
    assert set(c) == {
        "schema_version", "candidate_id", "source_run_ids", "task_kind", "tool_name",
        "workflow_name", "lesson", "evidence", "caveat", "tags",
    }
    assert c["tool_name"] == "harness"
    assert c["lesson"] == "Re-run the failing target."  # verbatim from note


def test_harness_candidates_conservative_no_trigger(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    # exit 0, no note/truncation/redaction, but has check_label -> no candidate
    append_harness_run(store, build_recorded_run(
        command="c", generated_at="T", exit_code=0, work_session_id="s", check_label="ok"))
    assert project_harness_candidates(read_harness_runs(store)) == []


def test_cli_harness_candidates_read_only_no_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"  # never created
    code, out = _run(capsys, "harness", "candidates", "--json", "--memory-dir", str(mem))
    assert code == 0 and json.loads(out)["count"] == 0
    assert not mem.exists()


def test_cli_harness_candidates_advisory_wording(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    append_harness_run(store, build_recorded_run(
        command="c", generated_at="T", exit_code=3, work_session_id="s", check_label="x",
        note="inspect output"))
    mem = tmp_path / ".chimera-memory"
    code, out = _run(capsys, "harness", "candidates", "--memory-dir", str(mem))
    assert code == 0 and "review before saving" in out.lower()


# --- Context Doctor refinement -----------------------------------------------

def test_doctor_harness_run_with_redacted_preview(tmp_path: Path) -> None:
    _seed_session(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    append_harness_run(store, build_executed_run(
        command=f"{_PY} -c \"print('a'*40)\"", generated_at="T", work_session_id="s"))
    from chimera_memory.context_doctor import build_context_doctor
    kinds = {f["kind"] for f in build_context_doctor(store, generated_at="T")["findings"]}
    assert "harness_run_with_redacted_preview" in kinds


# --- no forbidden wording ----------------------------------------------------

def test_no_forbidden_phrases(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sid = _seed_session(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    append_harness_run(store, build_recorded_run(
        command="uv run pytest", generated_at="T", exit_code=7, work_session_id=sid,
        check_label="suite", note="Re-run the failing target.", tags=("v0.30",)))
    mem = tmp_path / ".chimera-memory"
    blob = ""
    blob += _run(capsys, "branch-primer", "--work-session", sid, "--memory-dir", str(mem))[1]
    blob += _run(capsys, "work-packet", "--session", sid, "--memory-dir", str(mem))[1]
    blob += _run(capsys, "harness", "candidates", "--work-session", sid, "--memory-dir", str(mem))[1]
    for argv in (("harness", "candidates", "--help"), ("work-packet", "--help")):
        blob += _run(capsys, *argv)[1]
    blob += (Path(__file__).resolve().parents[3] / "docs" / "harness-lite.md").read_text(
        encoding="utf-8")
    _assert_no_forbidden(blob)
