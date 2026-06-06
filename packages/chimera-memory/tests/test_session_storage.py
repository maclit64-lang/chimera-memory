"""Slice 1: storage primitives for sessions (append-only sessions.jsonl)."""
from __future__ import annotations

from pathlib import Path

from chimera_memory.session import (
    AttributionConfidence,
    IdentitySource,
    Session,
)
from chimera_memory.storage import MemoryStore


def _session(sid: str, started_at: str, **overrides: object) -> Session:
    base = dict(
        session_id=sid,
        repo_path="/tmp/repo",
        branch="main",
        task_label="t",
        attribution_confidence=AttributionConfidence.UNKNOWN,
        identity_source=IdentitySource.UNKNOWN,
        started_at=started_at,
    )
    base.update(overrides)
    return Session(**base)


def test_sessions_path_is_inside_memory_dir(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    assert store.sessions_path == tmp_path / "sessions.jsonl"


def test_append_session_event_creates_file(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    s = _session("sess-1", "2026-06-03T20:00:00+00:00")
    store.append_session_event({"event": "start", "session": s.to_dict()})
    assert store.sessions_path.exists()


def test_read_session_events_round_trips(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    s = _session("sess-1", "2026-06-03T20:00:00+00:00")
    store.append_session_event({"event": "start", "session": s.to_dict()})
    events = store.read_session_events()
    assert len(events) == 1
    assert events[0]["event"] == "start"
    assert events[0]["session"]["session_id"] == "sess-1"


def test_current_session_returns_latest_open(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    s1 = _session("sess-1", "2026-06-03T20:00:00+00:00")
    s2 = _session("sess-2", "2026-06-03T20:01:00+00:00")
    store.append_session_event({"event": "start", "session": s1.to_dict()})
    store.append_session_event({"event": "start", "session": s2.to_dict()})
    current = store.current_session()
    assert current is not None
    assert current["session_id"] == "sess-2"


def test_current_session_returns_none_when_all_closed(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    s = _session("sess-1", "2026-06-03T20:00:00+00:00")
    store.append_session_event({"event": "start", "session": s.to_dict()})
    closed = Session.from_dict({
        **s.to_dict(),
        "ended_at": "2026-06-03T20:05:00+00:00",
        "final_status": "passed",
    })
    store.append_session_event({"event": "end", "session": closed.to_dict()})
    assert store.current_session() is None


def test_get_session_finds_by_id(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    s = _session("sess-1", "2026-06-03T20:00:00+00:00")
    store.append_session_event({"event": "start", "session": s.to_dict()})
    found = store.get_session("sess-1")
    assert found is not None
    assert found["session_id"] == "sess-1"


def test_get_session_returns_none_if_missing(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    assert store.get_session("sess-nope") is None


def test_list_sessions_returns_closed_only_in_reverse_chrono(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    s1 = _session("sess-1", "2026-06-03T20:00:00+00:00")
    s2 = _session("sess-2", "2026-06-03T20:01:00+00:00")
    # sess-1 fully closes
    store.append_session_event({"event": "start", "session": s1.to_dict()})
    closed1 = Session.from_dict({
        **s1.to_dict(),
        "ended_at": "2026-06-03T20:05:00+00:00",
        "final_status": "passed",
    })
    store.append_session_event({"event": "end", "session": closed1.to_dict()})
    # sess-2 fully closes
    store.append_session_event({"event": "start", "session": s2.to_dict()})
    closed2 = Session.from_dict({
        **s2.to_dict(),
        "ended_at": "2026-06-03T20:06:00+00:00",
        "final_status": "failed",
    })
    store.append_session_event({"event": "end", "session": closed2.to_dict()})
    sessions = store.list_sessions()
    assert [s["session_id"] for s in sessions] == ["sess-2", "sess-1"]


def test_list_sessions_excludes_open(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    s1 = _session("sess-1", "2026-06-03T20:00:00+00:00")
    s2 = _session("sess-2", "2026-06-03T20:01:00+00:00")
    store.append_session_event({"event": "start", "session": s1.to_dict()})
    closed1 = Session.from_dict({
        **s1.to_dict(),
        "ended_at": "2026-06-03T20:05:00+00:00",
        "final_status": "passed",
    })
    store.append_session_event({"event": "end", "session": closed1.to_dict()})
    # sess-2 is open
    store.append_session_event({"event": "start", "session": s2.to_dict()})
    sessions = store.list_sessions()
    assert [s["session_id"] for s in sessions] == ["sess-1"]


def test_initialize_does_not_create_sessions_file(tmp_path: Path) -> None:
    # Sessions are created lazily by append_session_event, not by init
    store = MemoryStore(tmp_path)
    store.initialize()
    assert not store.sessions_path.exists()
