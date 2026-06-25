"""Tests for the Agent Work Session v0 (event-sourced local lifecycle envelope)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from chimera_memory.cli import main
from chimera_memory.work_session import (
    build_session_event,
    make_session_id,
    project_sessions,
)

_FORBIDDEN = (
    "safe to merge", "production ready", "production-ready", "certified",
    "approved", "guaranteed", "proves correctness", "proves safety",
    "trusted", "proof-carrying", "proof", "optimal", "guaranteed faster",
)
_SESSION_KEYS = {
    "schema_version", "session_id", "status", "brief_id", "thread_dir", "kickoff_pack_dir",
    "snapshot_ids", "artifact_refs", "tags", "event_count", "created_at", "updated_at",
}


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


def _brief(capsys: pytest.CaptureFixture[str], mem: Path, *extra: str) -> str:
    code, out = _run(capsys, "work-brief", "add", "--title", "T", "--objective", "O",
                     "--task-kind", "memory-feature", "--tag", "v0.29", "--memory-dir", str(mem),
                     *extra)
    assert code == 0
    return out.strip()


# --- module: events + projection --------------------------------------------

def test_session_id_shape() -> None:
    sid = make_session_id(created_at="2026-06-25T10:00:00+00:00", brief_id="brief_x")
    assert sid.startswith("sess_") and len(sid.split("_")) == 2 and len(sid.split("_")[1]) == 16


def test_build_event_rejects_bad_kind_and_status() -> None:
    with pytest.raises(ValueError):
        build_session_event(session_id="sess_x", event_kind="bogus")
    with pytest.raises(ValueError):
        build_session_event(session_id="sess_x", event_kind="closed", status="passed")


def test_projection_folds_start_attach_close() -> None:
    sid = "sess_x"
    events = [
        build_session_event(session_id=sid, event_kind="started", brief_id="brief_x",
                            thread_dir="rt", kickoff_pack_dir="kp", tags=("v0.29",),
                            created_at="2026-01-01T00:00:00Z"),
        build_session_event(session_id=sid, event_kind="snapshot_attached", thread_dir="rt",
                            snapshot_id="wp_1", created_at="2026-01-01T00:00:01Z"),
        build_session_event(session_id=sid, event_kind="artifact_attached",
                            artifact_refs=("PR_EVIDENCE.md",), created_at="2026-01-01T00:00:02Z"),
        build_session_event(session_id=sid, event_kind="closed", status="blocked",
                            created_at="2026-01-01T00:00:03Z"),
    ]
    [s] = project_sessions(events)
    assert s.status == "blocked"
    assert s.brief_id == "brief_x" and s.thread_dir == "rt" and s.kickoff_pack_dir == "kp"
    assert s.snapshot_ids == ("wp_1",) and s.artifact_refs == ("PR_EVIDENCE.md",)
    assert s.tags == ("v0.29",) and s.event_count == 4
    assert s.created_at == "2026-01-01T00:00:00Z" and s.updated_at == "2026-01-01T00:00:03Z"


# --- CLI: start -------------------------------------------------------------

def test_start_writes_only_events_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = tmp_path / ".chimera-memory"
    bid = _brief(capsys, mem)
    code, out = _run(capsys, "work-session", "start", "--brief", bid, "--tag", "v0.29",
                     "--memory-dir", str(mem))
    assert code == 0
    sid = out.strip()
    assert sid.startswith("sess_")
    files = sorted(p.name for p in mem.iterdir() if p.is_file())
    assert files == ["work_briefs.jsonl", "work_session_events.jsonl"]


def test_start_requires_valid_brief(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = tmp_path / ".chimera-memory"
    mem.mkdir()
    code, _ = _run(capsys, "work-session", "start", "--memory-dir", str(mem))
    assert code == 2  # no --brief
    code, _ = _run(capsys, "work-session", "start", "--brief", "brief_nope",
                   "--memory-dir", str(mem))
    assert code == 2  # unknown brief


def test_start_kickoff_pack_writes_pack_and_event(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"
    bid = _brief(capsys, mem)
    pack = tmp_path / "kickoff-pack"
    code, out = _run(capsys, "work-session", "start", "--brief", bid,
                     "--kickoff-pack-dir", str(pack), "--memory-dir", str(mem))
    assert code == 0
    assert (pack / "manifest.json").exists()
    assert (pack / "WORK_BRIEF.md").exists()  # brief-aware pack
    # store gained only the session events file (plus the brief written earlier)
    files = sorted(p.name for p in mem.iterdir() if p.is_file())
    assert files == ["work_briefs.jsonl", "work_session_events.jsonl"]


# --- CLI: list / show -------------------------------------------------------

def test_list_text_json_and_filters(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = tmp_path / ".chimera-memory"
    bid = _brief(capsys, mem)
    _, out = _run(capsys, "work-session", "start", "--brief", bid, "--tag", "v0.29",
                  "--memory-dir", str(mem))
    sid = out.strip()
    code, out = _run(capsys, "work-session", "list", "--memory-dir", str(mem))
    assert code == 0 and sid in out
    _, out = _run(capsys, "work-session", "list", "--json", "--memory-dir", str(mem))
    d = json.loads(out)
    assert d["schema_version"] == 1 and len(d["sessions"]) == 1
    assert set(d["sessions"][0]) == _SESSION_KEYS

    def count(*args: str) -> int:
        _, o = _run(capsys, "work-session", "list", "--json", *args, "--memory-dir", str(mem))
        return len(json.loads(o)["sessions"])

    assert count("--status", "open") == 1
    assert count("--status", "closed") == 0
    assert count("--tag", "v0.29") == 1
    assert count("--limit", "0") == 0


def test_show_found_missing_json_markdown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"
    bid = _brief(capsys, mem)
    _, out = _run(capsys, "work-session", "start", "--brief", bid, "--memory-dir", str(mem))
    sid = out.strip()
    _, out = _run(capsys, "work-session", "show", sid, "--json", "--memory-dir", str(mem))
    d = json.loads(out)
    assert d["session"]["session_id"] == sid and len(d["events"]) == 1
    _, out = _run(capsys, "work-session", "show", "sess_nope", "--json", "--memory-dir", str(mem))
    d = json.loads(out)
    assert d["session"] is None and d["events"] == []
    _, out = _run(capsys, "work-session", "show", sid, "--markdown", "--memory-dir", str(mem))
    for h in ("# Chimera Agent Work Session", "## Session", "## Attached snapshots",
              "## Attached artifacts", "## Events"):
        assert h in out, h


# --- CLI: attach / close ----------------------------------------------------

def test_attach_snapshot_validates(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = tmp_path / ".chimera-memory"
    bid = _brief(capsys, mem)
    _, out = _run(capsys, "work-session", "start", "--brief", bid, "--memory-dir", str(mem))
    sid = out.strip()
    td = tmp_path / "review-thread"
    _run(capsys, "work-packet", "thread", "add", "--thread-dir", str(td),
         "--memory-dir", str(mem))
    snap = json.loads((td / "index.json").read_text())["snapshots"][0]["snapshot_id"]
    code, _ = _run(capsys, "work-session", "attach-snapshot", sid, "--thread-dir", str(td),
                   "--snapshot-id", snap, "--memory-dir", str(mem))
    assert code == 0
    code, _ = _run(capsys, "work-session", "attach-snapshot", sid, "--thread-dir", str(td),
                   "--snapshot-id", "wp_nope", "--memory-dir", str(mem))
    assert code == 2
    _, out = _run(capsys, "work-session", "show", sid, "--json", "--memory-dir", str(mem))
    assert json.loads(out)["session"]["snapshot_ids"] == [snap]


def test_attach_artifact_and_close_neutral(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"
    bid = _brief(capsys, mem)
    _, out = _run(capsys, "work-session", "start", "--brief", bid, "--memory-dir", str(mem))
    sid = out.strip()
    code, _ = _run(capsys, "work-session", "attach-artifact", sid, "--artifact-ref",
                   "PR_EVIDENCE.md", "--memory-dir", str(mem))
    assert code == 0
    code, _ = _run(capsys, "work-session", "close", sid, "--status", "blocked",
                   "--note", "creds", "--memory-dir", str(mem))
    assert code == 0
    code, _ = _run(capsys, "work-session", "close", sid, "--status", "passed",
                   "--memory-dir", str(mem))
    assert code == 2  # non-neutral status rejected
    _, out = _run(capsys, "work-session", "show", sid, "--json", "--memory-dir", str(mem))
    s = json.loads(out)["session"]
    assert s["status"] == "blocked" and s["artifact_refs"] == ["PR_EVIDENCE.md"]


def test_missing_session_attach_close_exit2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"
    mem.mkdir()
    code, _ = _run(capsys, "work-session", "attach-artifact", "sess_nope",
                   "--artifact-ref", "x", "--memory-dir", str(mem))
    assert code == 2
    code, _ = _run(capsys, "work-session", "close", "sess_nope", "--memory-dir", str(mem))
    assert code == 2


def test_list_show_no_store_creation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = tmp_path / ".chimera-memory"  # never created
    code, out = _run(capsys, "work-session", "list", "--json", "--memory-dir", str(mem))
    assert code == 0 and json.loads(out)["sessions"] == []
    code, out = _run(capsys, "work-session", "show", "sess_x", "--json", "--memory-dir", str(mem))
    assert code == 0 and json.loads(out)["session"] is None
    assert not mem.exists()


def test_no_forbidden_phrases(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = tmp_path / ".chimera-memory"
    bid = _brief(capsys, mem)
    _, out = _run(capsys, "work-session", "start", "--brief", bid, "--memory-dir", str(mem))
    sid = out.strip()
    blob = ""
    for argv in (("work-session", "list"), ("work-session", "list", "--json"),
                 ("work-session", "show", sid), ("work-session", "show", sid, "--json")):
        _, o = _run(capsys, *argv, "--memory-dir", str(mem))
        blob += o
    for argv in (("work-session", "--help"), ("work-session", "start", "--help"),
                 ("work-session", "close", "--help")):
        _, o = _run(capsys, *argv)
        blob += o
    blob += (Path(__file__).resolve().parents[3] / "docs" / "work-session.md").read_text(
        encoding="utf-8")
    low = blob.lower()
    for phrase in _FORBIDDEN:
        assert phrase not in low, f"overclaim phrase leaked: {phrase!r}"
