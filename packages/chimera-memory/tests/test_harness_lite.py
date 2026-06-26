"""Tests for Harness Lite v0 (local run-observation ledger)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from chimera_memory.cli import main
from chimera_memory.harness_run import (
    build_executed_run,
    build_recorded_run,
    read_harness_runs,
)
from chimera_memory.storage import MemoryStore
from chimera_memory.work_brief import add_work_brief, build_work_brief
from chimera_memory.work_session import append_session_event, build_session_event, make_session_id

_FORBIDDEN_SUB = (
    "safe to merge", "production ready", "production-ready", "certified", "approved",
    "guaranteed", "proves correctness", "proves safety", "trusted", "proof-carrying",
    "proof", "optimal", "guaranteed faster",
)
_FORBIDDEN_WORDS = ("healthy", "unhealthy", "pass", "fail", "ready", "not ready",
                    "success", "failure")
_PY = sys.executable


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


def _assert_no_forbidden(text: str) -> None:
    low = text.lower()
    for phrase in _FORBIDDEN_SUB:
        assert phrase not in low, f"overclaim phrase leaked: {phrase!r}"
    for word in _FORBIDDEN_WORDS:
        assert not re.search(r"\b" + re.escape(word) + r"\b", low), f"forbidden word: {word!r}"


def _seed_session(root: Path, *, tag: str = "v0.30") -> tuple[str, str]:
    store = MemoryStore.from_paths(root=root)
    brief = build_work_brief(title="H", objective="O", task_kind="harness-lite", tags=(tag,))
    add_work_brief(store, brief)
    sid = make_session_id(created_at="2026-06-26T10:00:00+00:00", brief_id=brief.brief_id)
    append_session_event(store, build_session_event(
        session_id=sid, event_kind="started", brief_id=brief.brief_id, tags=(tag,),
        created_at="2026-06-26T10:00:00+00:00"))
    return sid, brief.brief_id


# --- module: build / record / execute ---------------------------------------

def test_build_recorded_run_no_execution() -> None:
    r = build_recorded_run(command="uv run pytest", generated_at="T", exit_code=0)
    assert r.mode == "recorded"
    assert r.status == "completed"
    assert r.exit_code == 0
    assert r.stdout_sha256 is None


def test_build_executed_run_records_exit_code() -> None:
    r = build_executed_run(command=f"{_PY} -c \"print('hello')\"", generated_at="T")
    assert r.mode == "executed"
    assert r.exit_code == 0
    assert r.status == "completed"
    assert "hello" in r.stdout_preview
    assert r.stdout_sha256 is not None


def test_build_executed_run_nonzero_exit_recorded() -> None:
    r = build_executed_run(
        command=f"{_PY} -c \"import sys; print('oops'); sys.exit(7)\"", generated_at="T"
    )
    assert r.exit_code == 7
    assert r.status == "completed"


def test_executed_run_previews_are_bounded_and_hashed() -> None:
    r = build_executed_run(
        command=f"{_PY} -c \"print(('hello ')*2000)\"", generated_at="T", max_output_bytes=100
    )
    assert r.output_truncated is True
    assert len(r.stdout_preview.encode("utf-8")) <= 100
    assert r.stdout_sha256 is not None


def test_redaction_applied_on_secret_like_output() -> None:
    r = build_executed_run(command=f"{_PY} -c \"print('a'*40)\"", generated_at="T")
    assert r.redaction_applied is True
    assert "REDACTED" in r.stdout_preview


def test_output_truncated_false_for_small_output() -> None:
    r = build_executed_run(command=f"{_PY} -c \"print('hi')\"", generated_at="T")
    assert r.output_truncated is False


# --- CLI: record / run -------------------------------------------------------

def test_cli_record_writes_only_harness_jsonl(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"
    mem.mkdir()
    code, _ = _run(capsys, "harness", "record", "--command", "uv run pytest",
                   "--exit-code", "0", "--tag", "v0.30", "--memory-dir", str(mem))
    assert code == 0
    files = {p.name for p in mem.iterdir() if p.is_file()}
    assert files == {"harness_runs.jsonl"}


def test_cli_record_validates_work_session(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"
    mem.mkdir()
    code, _ = _run(capsys, "harness", "record", "--command", "x",
                   "--work-session", "sess_nope", "--memory-dir", str(mem))
    assert code == 2


def test_cli_record_populates_brief_id_from_session(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sid, brief_id = _seed_session(tmp_path)
    mem = tmp_path / ".chimera-memory"
    code, _ = _run(capsys, "harness", "record", "--command", "uv run pytest", "--exit-code", "0",
                   "--work-session", sid, "--memory-dir", str(mem))
    assert code == 0
    runs = read_harness_runs(MemoryStore.from_paths(memory_dir=mem))
    assert runs[0].work_session_id == sid
    assert runs[0].brief_id == brief_id


def test_cli_run_executes_and_records(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = tmp_path / ".chimera-memory"
    mem.mkdir()
    code, _ = _run(capsys, "harness", "run", "--command", f"{_PY} -c \"print('x')\"",
                   "--memory-dir", str(mem))
    assert code == 0
    runs = read_harness_runs(MemoryStore.from_paths(memory_dir=mem))
    assert runs[0].mode == "executed" and runs[0].exit_code == 0


def test_cli_run_nonzero_exit_chimera_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"
    mem.mkdir()
    code, _ = _run(capsys, "harness", "run", "--command",
                   f"{_PY} -c \"import sys; sys.exit(7)\"", "--memory-dir", str(mem))
    assert code == 0
    runs = read_harness_runs(MemoryStore.from_paths(memory_dir=mem))
    assert runs[0].exit_code == 7


# --- CLI: list / show --------------------------------------------------------

def test_cli_list_json_and_filters(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sid, brief_id = _seed_session(tmp_path)
    mem = tmp_path / ".chimera-memory"
    for tg in ("v0.30", "other"):
        _run(capsys, "harness", "record", "--command", "c", "--exit-code", "0",
             "--work-session", sid, "--tag", tg, "--memory-dir", str(mem))
    code, out = _run(capsys, "harness", "list", "--json", "--memory-dir", str(mem))
    assert code == 0 and json.loads(out)["count"] == 2
    assert json.loads(_run(capsys, "harness", "list", "--tag", "v0.30", "--json",
                           "--memory-dir", str(mem))[1])["count"] == 1
    assert json.loads(_run(capsys, "harness", "list", "--work-session", sid, "--json",
                           "--memory-dir", str(mem))[1])["count"] == 2
    assert json.loads(_run(capsys, "harness", "list", "--brief", brief_id, "--json",
                           "--memory-dir", str(mem))[1])["count"] == 2
    assert len(json.loads(_run(capsys, "harness", "list", "--limit", "1", "--json",
                               "--memory-dir", str(mem))[1])["harness_runs"]) == 1


def test_cli_show_found_missing_markdown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"
    mem.mkdir()
    _run(capsys, "harness", "record", "--command", "uv run pytest", "--exit-code", "0",
         "--memory-dir", str(mem))
    rid = json.loads(_run(capsys, "harness", "list", "--json",
                          "--memory-dir", str(mem))[1])["harness_runs"][0]["run_id"]
    code, out = _run(capsys, "harness", "show", rid, "--markdown", "--memory-dir", str(mem))
    assert code == 0 and "# Chimera Harness Run" in out and "exit code 0" in out
    assert _run(capsys, "harness", "show", "run_nope", "--memory-dir", str(mem))[0] == 2


def test_cli_list_show_do_not_create_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"
    assert _run(capsys, "harness", "list", "--json", "--memory-dir", str(mem))[0] == 0
    assert _run(capsys, "harness", "show", "run_x", "--memory-dir", str(mem))[0] == 2
    assert not mem.exists()


def test_cli_list_show_read_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = tmp_path / ".chimera-memory"
    mem.mkdir()
    _run(capsys, "harness", "record", "--command", "c", "--exit-code", "0",
         "--memory-dir", str(mem))
    before = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    rid = json.loads(_run(capsys, "harness", "list", "--json",
                          "--memory-dir", str(mem))[1])["harness_runs"][0]["run_id"]
    _run(capsys, "harness", "show", rid, "--memory-dir", str(mem))
    after = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    assert before == after


# --- integration: work-session runs / closeout / rollup / doctor -------------

def test_work_session_runs_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sid, _ = _seed_session(tmp_path)
    mem = tmp_path / ".chimera-memory"
    _run(capsys, "harness", "record", "--command", "c", "--exit-code", "0",
         "--work-session", sid, "--memory-dir", str(mem))
    code, out = _run(capsys, "work-session", "runs", sid, "--json", "--memory-dir", str(mem))
    assert code == 0 and json.loads(out)["count"] == 1
    assert _run(capsys, "work-session", "runs", "sess_nope", "--memory-dir", str(mem))[0] == 2


def test_closeout_includes_harness_runs(tmp_path: Path) -> None:
    sid, _ = _seed_session(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    from chimera_memory.harness_run import append_harness_run
    append_harness_run(store, build_recorded_run(
        command="uv run pytest", generated_at="T", exit_code=0, work_session_id=sid))
    from chimera_memory.session_closeout import (
        build_session_closeout,
        render_session_closeout_markdown,
    )
    co = build_session_closeout(store, sid, generated_at="T")
    assert co is not None
    assert "harness_runs" in co and len(co["harness_runs"]) == 1
    assert "## Harness runs" in render_session_closeout_markdown(co)


def test_rollup_counts_harness_runs(tmp_path: Path) -> None:
    sid, _ = _seed_session(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    from chimera_memory.harness_run import append_harness_run
    append_harness_run(store, build_recorded_run(
        command="c", generated_at="T", exit_code=0, work_session_id=sid))
    append_harness_run(store, build_executed_run(
        command=f"{_PY} -c \"print('x')\"", generated_at="T", work_session_id=sid))
    from chimera_memory.session_rollup import build_session_rollup
    s = build_session_rollup(store, generated_at="T")["summary"]
    assert s["harness_run_count"] == 2
    assert s["executed_run_count"] == 1
    assert s["recorded_run_count"] == 1


def test_doctor_session_without_harness_runs(tmp_path: Path) -> None:
    sid, _ = _seed_session(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    from chimera_memory.context_doctor import build_context_doctor
    kinds = {f["kind"] for f in build_context_doctor(store, generated_at="T")["findings"]}
    assert "session_without_harness_runs" in kinds


def test_doctor_harness_run_without_session_and_truncated(tmp_path: Path) -> None:
    _seed_session(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    from chimera_memory.harness_run import append_harness_run
    append_harness_run(store, build_recorded_run(command="orphan", generated_at="T", exit_code=0))
    append_harness_run(store, build_executed_run(
        command=f"{_PY} -c \"print(('hello ')*2000)\"", generated_at="T", max_output_bytes=50))
    from chimera_memory.context_doctor import build_context_doctor
    kinds = {f["kind"] for f in build_context_doctor(store, generated_at="T")["findings"]}
    assert "harness_run_without_session" in kinds
    assert "harness_run_output_truncated" in kinds


# --- no forbidden generated wording ------------------------------------------

def test_no_forbidden_phrases(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sid, _ = _seed_session(tmp_path)
    mem = tmp_path / ".chimera-memory"
    _run(capsys, "harness", "record", "--command", "uv run pytest", "--exit-code", "0",
         "--work-session", sid, "--memory-dir", str(mem))
    _run(capsys, "harness", "run", "--command", f"{_PY} -c \"import sys; sys.exit(3)\"",
         "--work-session", sid, "--memory-dir", str(mem))
    blob = ""
    rid = json.loads(_run(capsys, "harness", "list", "--json",
                          "--memory-dir", str(mem))[1])["harness_runs"][0]["run_id"]
    blob += _run(capsys, "harness", "show", rid, "--markdown", "--memory-dir", str(mem))[1]
    blob += _run(capsys, "harness", "list", "--memory-dir", str(mem))[1]
    for argv in (("harness", "--help"), ("harness", "record", "--help"),
                 ("harness", "run", "--help")):
        blob += _run(capsys, *argv)[1]
    blob += (Path(__file__).resolve().parents[3] / "docs" / "harness-lite.md").read_text(
        encoding="utf-8")
    _assert_no_forbidden(blob)
