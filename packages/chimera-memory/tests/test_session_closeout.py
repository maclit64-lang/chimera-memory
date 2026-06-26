"""Tests for the Agent Session Closeout v0 (advisory end-of-session summary)."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from chimera_memory.cli import main
from chimera_memory.session_closeout import build_session_closeout, render_session_closeout_markdown
from chimera_memory.storage import MemoryStore
from chimera_memory.work_brief import add_work_brief, build_work_brief
from chimera_memory.work_packet import add_thread_snapshot, build_work_packet, read_thread_index
from chimera_memory.work_session import (
    append_session_event,
    build_session_event,
    make_session_id,
)

_FORBIDDEN = (
    "safe to merge", "production ready", "production-ready", "certified",
    "approved", "guaranteed", "proves correctness", "proves safety",
    "trusted", "proof-carrying", "proof", "optimal", "guaranteed faster",
)
_CLOSEOUT_KEYS = {
    "schema_version", "artifact", "advisory", "generated_at", "session", "work_brief",
    "snapshot_delta", "reported_checks", "done_observations", "carryover",
    "attached_artifacts", "harness_runs", "consequence_observations",
    "suggested_review_targets",
}
_T0 = datetime(2026, 6, 25, 10, 0, 0, tzinfo=UTC)


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


def _seed_started(root: Path, *, thread_dir: str | None = None) -> str:
    store = MemoryStore.from_paths(root=root)
    brief = build_work_brief(title="Closeout", objective="Do it.", task_kind="memory-feature")
    add_work_brief(store, brief)
    sid = make_session_id(created_at=_T0.isoformat(), brief_id=brief.brief_id)
    append_session_event(store, build_session_event(
        session_id=sid, event_kind="started", brief_id=brief.brief_id,
        thread_dir=thread_dir, created_at=_T0.isoformat()))
    return sid


def _attach_n_snapshots(root: Path, sid: str, n: int) -> str:
    store = MemoryStore.from_paths(root=root)
    td = root / "review-thread"
    for i in range(n):
        add_thread_snapshot(build_work_packet(store, generated_at=f"t{i}"), thread_dir=td,
                            store_label="ws", now=_T0 + timedelta(seconds=i + 1), label=f"s{i}")
        if i == 0:  # add a tool note between snapshots so the delta is non-trivial
            from chimera_memory.tool_notes import add_tool_note, build_tool_note
            add_tool_note(store, build_tool_note(task_kind="k", tool_name="t", lesson="L"))
        sid_snap = read_thread_index(td)["snapshots"][i]["snapshot_id"]  # type: ignore[index]
        append_session_event(store, build_session_event(
            session_id=sid, event_kind="snapshot_attached", thread_dir=str(td),
            snapshot_id=sid_snap, created_at=(_T0 + timedelta(seconds=i + 1)).isoformat()))
    return str(td)


# --- module: build + snapshot delta -----------------------------------------

def test_build_closeout_schema(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    sid = _seed_started(tmp_path)
    append_session_event(store, build_session_event(
        session_id=sid, event_kind="check_reported", check="pytest",
        created_at="2026-06-25T10:00:03+00:00"))
    co = build_session_closeout(store, sid, generated_at="T")
    assert co is not None
    assert set(co) == _CLOSEOUT_KEYS
    assert co["artifact"] == "chimera_agent_session_closeout"
    assert len(co["reported_checks"]) == 1
    assert co["work_brief"]["title"] == "Closeout"


def test_build_closeout_missing_session(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    assert build_session_closeout(store, "sess_nope", generated_at="T") is None


def test_snapshot_delta_first_vs_latest(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    sid = _seed_started(tmp_path, thread_dir=str(tmp_path / "review-thread"))
    _attach_n_snapshots(tmp_path, sid, 2)
    co = build_session_closeout(store, sid, generated_at="T")
    assert co is not None
    delta = co["snapshot_delta"]
    assert delta["mode"] == "first-vs-latest"
    assert delta["diff"]["artifact"] == "chimera_work_packet_diff"
    assert delta["diff"]["summary_delta"]["tool_note_count"] == 1


def test_snapshot_delta_single(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    sid = _seed_started(tmp_path, thread_dir=str(tmp_path / "review-thread"))
    _attach_n_snapshots(tmp_path, sid, 1)
    co = build_session_closeout(store, sid, generated_at="T")
    assert co is not None and co["snapshot_delta"]["mode"] == "single"


def test_snapshot_delta_none(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    sid = _seed_started(tmp_path)
    co = build_session_closeout(store, sid, generated_at="T")
    assert co is not None and co["snapshot_delta"] is None


def test_render_markdown_sections(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    sid = _seed_started(tmp_path)
    co = build_session_closeout(store, sid, generated_at="T")
    md = render_session_closeout_markdown(co)  # type: ignore[arg-type]
    for h in ("# Chimera Agent Session Closeout", "## Session", "## Original work brief",
              "## Snapshot delta", "## Reported checks", "## Done criteria observations",
              "## Attached artifacts", "## Carryover for next agent",
              "## Suggested review targets"):
        assert h in md, h


# --- CLI: report-* + closeout -----------------------------------------------

def test_report_commands_append_neutral_events(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"
    sid = _seed_started(tmp_path)
    code, _ = _run(capsys, "work-session", "report-check", sid, "--check", "pytest",
                   "--memory-dir", str(mem))
    assert code == 0
    code, _ = _run(capsys, "work-session", "report-done", sid, "--done", "green",
                   "--status", "reported", "--memory-dir", str(mem))
    assert code == 0
    code, _ = _run(capsys, "work-session", "report-done", sid, "--done", "x", "--status",
                   "closed", "--memory-dir", str(mem))
    assert code == 2  # non-DONE status rejected
    code, _ = _run(capsys, "work-session", "note-carryover", sid, "--carryover", "token missing",
                   "--tag", "release-blocker", "--memory-dir", str(mem))
    assert code == 0
    _, out = _run(capsys, "work-session", "closeout", sid, "--json", "--memory-dir", str(mem))
    d = json.loads(out)
    assert len(d["reported_checks"]) == 1 and len(d["done_observations"]) == 1
    assert len(d["carryover"]) == 1


def test_closeout_missing_session_exit2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = tmp_path / ".chimera-memory"
    mem.mkdir()
    code, _ = _run(capsys, "work-session", "closeout", "sess_nope", "--memory-dir", str(mem))
    assert code == 2


def test_closeout_read_only_no_store_creation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"
    sid = _seed_started(tmp_path)
    before = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    _run(capsys, "work-session", "closeout", sid, "--json", "--memory-dir", str(mem))
    _run(capsys, "work-session", "closeout", sid, "--markdown", "--memory-dir", str(mem))
    after = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    assert before == after


def test_closeout_output_writes_only_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"
    sid = _seed_started(tmp_path)
    out_file = tmp_path / "SESSION_CLOSEOUT.md"
    before = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    code, out = _run(capsys, "work-session", "closeout", sid, "--output", str(out_file),
                     "--memory-dir", str(mem))
    assert code == 0 and out_file.exists()
    assert "# Chimera Agent Session Closeout" in out_file.read_text(encoding="utf-8")
    after = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    assert before == after


# --- CLI: closeout bundle ---------------------------------------------------

def test_closeout_bundle_files_and_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import hashlib
    mem = tmp_path / ".chimera-memory"
    sid = _seed_started(tmp_path, thread_dir=str(tmp_path / "review-thread"))
    _attach_n_snapshots(tmp_path, sid, 2)
    out = tmp_path / "closeout-pack"
    code, _ = _run(capsys, "work-session", "closeout-bundle", sid, "--output-dir", str(out),
                   "--memory-dir", str(mem))
    assert code == 0
    names = sorted(p.name for p in out.iterdir())
    for required in ("SESSION_CLOSEOUT.md", "session-closeout.json", "SESSION.md", "session.json",
                     "WORK_BRIEF.md", "work-brief.json", "manifest.json", "README.md",
                     "snapshot-diff.json"):
        assert required in names, required
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifact"] == "chimera_agent_session_closeout_bundle"
    for entry in manifest["files"]:
        data = (out / entry["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        assert len(data) == entry["bytes"]


def test_closeout_bundle_refuses_non_empty_without_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"
    sid = _seed_started(tmp_path)
    out = tmp_path / "pack"
    code, _ = _run(capsys, "work-session", "closeout-bundle", sid, "--output-dir", str(out),
                   "--memory-dir", str(mem))
    assert code == 0
    code, _ = _run(capsys, "work-session", "closeout-bundle", sid, "--output-dir", str(out),
                   "--memory-dir", str(mem))
    assert code == 2
    code, _ = _run(capsys, "work-session", "closeout-bundle", sid, "--output-dir", str(out),
                   "--force", "--memory-dir", str(mem))
    assert code == 0


def test_no_forbidden_phrases(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = tmp_path / ".chimera-memory"
    sid = _seed_started(tmp_path)
    _run(capsys, "work-session", "report-check", sid, "--check", "pytest", "--memory-dir", str(mem))
    blob = ""
    _, out = _run(capsys, "work-session", "closeout", sid, "--memory-dir", str(mem))
    blob += out
    _, out = _run(capsys, "work-session", "closeout", sid, "--json", "--memory-dir", str(mem))
    blob += out
    for argv in (("work-session", "closeout", "--help"),
                 ("work-session", "report-done", "--help")):
        _, out = _run(capsys, *argv)
        blob += out
    blob += (Path(__file__).resolve().parents[3] / "docs" / "work-session.md").read_text(
        encoding="utf-8")
    low = blob.lower()
    for phrase in _FORBIDDEN:
        assert phrase not in low, f"overclaim phrase leaked: {phrase!r}"
