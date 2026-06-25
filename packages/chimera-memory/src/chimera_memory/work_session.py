"""Chimera Agent Work Session v0 — a local task lifecycle envelope.

A Work Session links one agent task to the Work Brief that started it, the
kickoff context / review thread used, and the packet snapshots and artifacts
attached for review. It is **event-sourced**: events are appended to
``.chimera-memory/work_session_events.jsonl`` and folded into a read-only
session projection. It is a session envelope, not a verdict.

Statuses are neutral (``open`` / ``blocked`` / ``closed`` / ``unknown``). It is
advisory and local: never a correctness, safety, approval, merge, or
production-readiness signal, and not a form of verification or automation.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from chimera_memory.storage import MemoryStore

SCHEMA_VERSION = 1
STORE_FILE = "work_session_events.jsonl"

SESSION_ADVISORY = (
    "local task lifecycle context; not a correctness, safety, approval, merge, "
    "production-readiness, or speed guarantee"
)

EVENT_KINDS = frozenset({"started", "artifact_attached", "snapshot_attached", "closed"})
NEUTRAL_STATUSES = frozenset({"open", "blocked", "closed", "unknown"})


def _strs(value: Any) -> tuple[str, ...]:
    return tuple(str(v) for v in value if isinstance(v, str)) if isinstance(value, list) else ()


def _opt(value: Any) -> str | None:
    return str(value) if isinstance(value, str) else None


@dataclass(frozen=True)
class WorkSessionEvent:
    schema_version: int
    event_id: str
    created_at: str
    session_id: str
    event_kind: str
    brief_id: str | None
    thread_dir: str | None
    kickoff_pack_dir: str | None
    snapshot_id: str | None
    artifact_refs: tuple[str, ...]
    status: str | None
    note: str | None
    tags: tuple[str, ...]
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "created_at": self.created_at,
            "session_id": self.session_id,
            "event_kind": self.event_kind,
            "brief_id": self.brief_id,
            "thread_dir": self.thread_dir,
            "kickoff_pack_dir": self.kickoff_pack_dir,
            "snapshot_id": self.snapshot_id,
            "artifact_refs": list(self.artifact_refs),
            "status": self.status,
            "note": self.note,
            "tags": list(self.tags),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WorkSessionEvent:
        return cls(
            schema_version=int(d.get("schema_version", SCHEMA_VERSION)),
            event_id=str(d.get("event_id", "")),
            created_at=str(d.get("created_at", "")),
            session_id=str(d.get("session_id", "")),
            event_kind=str(d.get("event_kind", "")),
            brief_id=_opt(d.get("brief_id")),
            thread_dir=_opt(d.get("thread_dir")),
            kickoff_pack_dir=_opt(d.get("kickoff_pack_dir")),
            snapshot_id=_opt(d.get("snapshot_id")),
            artifact_refs=_strs(d.get("artifact_refs")),
            status=_opt(d.get("status")),
            note=_opt(d.get("note")),
            tags=_strs(d.get("tags")),
            source=str(d.get("source", "cli")),
        )


def make_session_id(*, created_at: str, brief_id: str) -> str:
    key = "\x1f".join([created_at, brief_id])
    return "sess_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def make_event_id(*, created_at: str, session_id: str, event_kind: str, detail: str = "") -> str:
    key = "\x1f".join([created_at, session_id, event_kind, detail])
    return "evt_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def build_session_event(
    *,
    session_id: str,
    event_kind: str,
    brief_id: str | None = None,
    thread_dir: str | None = None,
    kickoff_pack_dir: str | None = None,
    snapshot_id: str | None = None,
    artifact_refs: tuple[str, ...] = (),
    status: str | None = None,
    note: str | None = None,
    tags: tuple[str, ...] = (),
    source: str = "cli",
    created_at: str | None = None,
) -> WorkSessionEvent:
    if event_kind not in EVENT_KINDS:
        raise ValueError(f"unknown event_kind: {event_kind!r}")
    if status is not None and status not in NEUTRAL_STATUSES:
        raise ValueError(f"status must be one of {sorted(NEUTRAL_STATUSES)}, got {status!r}")
    ts = created_at if created_at is not None else datetime.now(UTC).isoformat()
    detail = snapshot_id or (artifact_refs[0] if artifact_refs else "") or (status or "")
    return WorkSessionEvent(
        schema_version=SCHEMA_VERSION,
        event_id=make_event_id(
            created_at=ts, session_id=session_id, event_kind=event_kind, detail=detail
        ),
        created_at=ts,
        session_id=session_id,
        event_kind=event_kind,
        brief_id=brief_id,
        thread_dir=thread_dir,
        kickoff_pack_dir=kickoff_pack_dir,
        snapshot_id=snapshot_id,
        artifact_refs=tuple(artifact_refs),
        status=status,
        note=note,
        tags=tuple(tags),
        source=source,
    )


def append_session_event(store: MemoryStore, event: WorkSessionEvent) -> None:
    """Append one session event. Explicit write; does NOT initialize the ledger."""
    store.ensure()
    store.append_jsonl(STORE_FILE, event.to_dict())


def read_session_events(store: MemoryStore) -> list[WorkSessionEvent]:
    """Read all session events (stored order). Read-only; never creates a store."""
    return [WorkSessionEvent.from_dict(d) for d in store.read_jsonl(STORE_FILE)]


@dataclass(frozen=True)
class WorkSession:
    schema_version: int
    session_id: str
    status: str
    brief_id: str | None
    thread_dir: str | None
    kickoff_pack_dir: str | None
    snapshot_ids: tuple[str, ...]
    artifact_refs: tuple[str, ...]
    tags: tuple[str, ...]
    event_count: int
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "status": self.status,
            "brief_id": self.brief_id,
            "thread_dir": self.thread_dir,
            "kickoff_pack_dir": self.kickoff_pack_dir,
            "snapshot_ids": list(self.snapshot_ids),
            "artifact_refs": list(self.artifact_refs),
            "tags": list(self.tags),
            "event_count": self.event_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class _Acc:
    status: str = "unknown"
    brief_id: str | None = None
    thread_dir: str | None = None
    kickoff_pack_dir: str | None = None
    snapshot_ids: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    event_count: int = 0
    created_at: str = ""
    updated_at: str = ""


def project_sessions(events: list[WorkSessionEvent]) -> list[WorkSession]:
    """Fold events into session projections (first-started order). Deterministic."""
    accs: dict[str, _Acc] = {}
    order: list[str] = []
    for ev in events:
        acc = accs.get(ev.session_id)
        if acc is None:
            acc = _Acc(created_at=ev.created_at)
            accs[ev.session_id] = acc
            order.append(ev.session_id)
        acc.event_count += 1
        acc.updated_at = ev.created_at
        if ev.event_kind == "started":
            acc.status = "open"
            acc.created_at = ev.created_at
            if ev.brief_id:
                acc.brief_id = ev.brief_id
            if ev.thread_dir:
                acc.thread_dir = ev.thread_dir
            if ev.kickoff_pack_dir:
                acc.kickoff_pack_dir = ev.kickoff_pack_dir
            for t in ev.tags:
                if t not in acc.tags:
                    acc.tags.append(t)
        elif ev.event_kind == "snapshot_attached":
            if ev.thread_dir and not acc.thread_dir:
                acc.thread_dir = ev.thread_dir
            if ev.snapshot_id and ev.snapshot_id not in acc.snapshot_ids:
                acc.snapshot_ids.append(ev.snapshot_id)
        elif ev.event_kind == "artifact_attached":
            for ref in ev.artifact_refs:
                acc.artifact_refs.append(ref)
        elif ev.event_kind == "closed":
            acc.status = ev.status if ev.status in NEUTRAL_STATUSES else "closed"
    return [
        WorkSession(
            schema_version=SCHEMA_VERSION,
            session_id=sid,
            status=accs[sid].status,
            brief_id=accs[sid].brief_id,
            thread_dir=accs[sid].thread_dir,
            kickoff_pack_dir=accs[sid].kickoff_pack_dir,
            snapshot_ids=tuple(accs[sid].snapshot_ids),
            artifact_refs=tuple(accs[sid].artifact_refs),
            tags=tuple(accs[sid].tags),
            event_count=accs[sid].event_count,
            created_at=accs[sid].created_at,
            updated_at=accs[sid].updated_at,
        )
        for sid in order
    ]


def sessions_for_store(store: MemoryStore) -> list[WorkSession]:
    return project_sessions(read_session_events(store))


def events_for_session(store: MemoryStore, session_id: str) -> list[WorkSessionEvent]:
    return [e for e in read_session_events(store) if e.session_id == session_id]


def find_session(store: MemoryStore, session_id: str) -> WorkSession | None:
    for s in sessions_for_store(store):
        if s.session_id == session_id:
            return s
    return None


def filter_sessions(
    sessions: list[WorkSession],
    *,
    status: str | None = None,
    tag: str | None = None,
) -> list[WorkSession]:
    """Exact-match filter (AND). No fuzzy matching, no ranking."""
    return [
        s
        for s in sessions
        if (status is None or s.status == status)
        and (tag is None or tag in s.tags)
    ]


def render_session_markdown(session: WorkSession, events: list[WorkSessionEvent]) -> str:
    """Render a session projection to advisory markdown. Presentation only."""
    lines: list[str] = []
    lines.append("# Chimera Agent Work Session")
    lines.append("")
    lines.append("Advisory session envelope only. Local task lifecycle context;")
    lines.append(f"{SESSION_ADVISORY}.")
    lines.append("")
    lines.append("## Session")
    lines.append(f"- session_id: {session.session_id}")
    lines.append(f"- status: {session.status}")
    lines.append(f"- brief_id: {session.brief_id or '(none)'}")
    lines.append(f"- review thread: {session.thread_dir or '(none)'}")
    lines.append(f"- kickoff pack: {session.kickoff_pack_dir or '(none)'}")
    lines.append(f"- created_at: {session.created_at}")
    lines.append(f"- updated_at: {session.updated_at}")
    lines.append("")
    lines.append("## Attached snapshots")
    if session.snapshot_ids:
        for sid in session.snapshot_ids:
            lines.append(f"- {sid}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Attached artifacts")
    if session.artifact_refs:
        for ref in session.artifact_refs:
            lines.append(f"- {ref}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Events")
    for ev in events:
        suffix = f" — {ev.note}" if ev.note else ""
        lines.append(f"- {ev.created_at} {ev.event_kind}{suffix}")
    return "\n".join(lines)
