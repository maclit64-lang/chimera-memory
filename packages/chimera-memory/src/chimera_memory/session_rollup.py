"""Multi-session review rollup (advisory carryover inbox / review board).

A Session Review Rollup is a read-only, local summary across Agent Work Sessions:
which sessions are open, which are blocked, which recently closed, the checks the
agent *reported* running, the done-criteria the agent *reported* observing, the
carryover items left for the next agent, and a deterministic list of suggested
review targets (snapshots, artifacts, briefs, threads) drawn only from explicit
session data.

Everything is reported / advisory. Nothing is ranked, scored, prioritized,
approved, or judged. Building the rollup composes existing read-only session
projections and events; it writes nothing to the memory store (``--output`` /
``rollup-bundle`` write only the files you name).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from chimera_memory.storage import MemoryStore
from chimera_memory.work_session import (
    WorkSession,
    filter_sessions,
    read_session_events,
    sessions_for_store,
)

SCHEMA_VERSION = 1
ROLLUP_ARTIFACT = "chimera_work_session_rollup"
ROLLUP_BUNDLE_ARTIFACT = "chimera_work_session_rollup_bundle"
ROLLUP_ADVISORY = (
    "local multi-session review context only; not a correctness, safety, approval, "
    "merge, production-readiness, or speed guarantee"
)

_ROLLUP_MD = "SESSION_ROLLUP.md"
_ROLLUP_JSON = "session-rollup.json"
_MANIFEST = "manifest.json"
_README = "README.md"


class RollupError(Exception):
    """Raised for rollup bundle precondition failures (clean CLI errors)."""


def _carryover_item(ev: Any, sess_by_id: dict[str, WorkSession]) -> dict[str, Any]:
    sess = sess_by_id.get(ev.session_id)
    return {
        "session_id": ev.session_id,
        "created_at": ev.created_at,
        "carryover": ev.carryover,
        "note": ev.note,
        "tags": list(ev.tags),
        "source": ev.source,
        "brief_id": sess.brief_id if sess else None,
        "session_status": sess.status if sess else None,
    }


def _dedup(items: list[str]) -> list[str]:
    """Drop exact-duplicate strings, preserving first-seen order (no semantic dedup)."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _suggested_review_targets(sessions: list[WorkSession]) -> list[str]:
    """Deterministic inspection targets from explicit session data. No ranking."""
    targets: list[str] = []
    targets += [f"Open session: {s.session_id}" for s in sessions if s.status == "open"]
    targets += [f"Blocked session: {s.session_id}" for s in sessions if s.status == "blocked"]
    for s in sessions:
        targets += [f"Snapshot: {sid}" for sid in s.snapshot_ids]
    for s in sessions:
        targets += [f"Artifact: {ref}" for ref in s.artifact_refs]
    targets += [f"Work brief: {s.brief_id}" for s in sessions if s.brief_id]
    targets += [f"Review thread: {s.thread_dir}" for s in sessions if s.thread_dir]
    return _dedup(targets)


def build_session_rollup(
    store: MemoryStore,
    *,
    generated_at: str,
    status: str | None = None,
    tag: str | None = None,
    limit_sessions: int | None = None,
    limit_carryover: int | None = None,
    carryover_tag: str | None = None,
) -> dict[str, Any]:
    """Build the read-only multi-session review rollup. Writes nothing.

    Exact filters only (``status`` / ``tag``); limits apply *after* filtering.
    ``limit_carryover`` truncates the carryover inbox listing only — the summary
    counts always reflect the full selected set.
    """
    all_sessions = sessions_for_store(store)
    filtered = filter_sessions(all_sessions, status=status, tag=tag)
    sessions = filtered[:limit_sessions] if limit_sessions is not None else filtered
    selected_ids = {s.session_id for s in sessions}
    sess_by_id = {s.session_id: s for s in sessions}

    events = [e for e in read_session_events(store) if e.session_id in selected_ids]

    reported_checks = [
        {"session_id": e.session_id, "check": e.check, "note": e.note,
         "created_at": e.created_at}
        for e in events
        if e.event_kind == "check_reported"
    ]
    done_observations = [
        {"session_id": e.session_id, "done_criterion": e.done_criterion, "status": e.status,
         "note": e.note, "created_at": e.created_at}
        for e in events
        if e.event_kind == "done_observed"
    ]
    carryover_all = [
        _carryover_item(e, sess_by_id) for e in events if e.event_kind == "carryover_noted"
    ]
    if carryover_tag is not None:
        carryover_all = [c for c in carryover_all if carryover_tag in c["tags"]]
    carryover = (
        carryover_all[:limit_carryover] if limit_carryover is not None else carryover_all
    )

    open_sessions = [s.to_dict() for s in sessions if s.status == "open"]
    blocked_sessions = [s.to_dict() for s in sessions if s.status == "blocked"]
    closed = [s for s in sessions if s.status == "closed"]
    recent_closeouts = [
        s.to_dict()
        for s in sorted(closed, key=lambda x: (x.updated_at, x.session_id), reverse=True)
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "artifact": ROLLUP_ARTIFACT,
        "advisory": ROLLUP_ADVISORY,
        "generated_at": generated_at,
        "filters": {
            "status": status,
            "tag": tag,
            "limit_sessions": limit_sessions,
            "limit_carryover": limit_carryover,
            "carryover_tag": carryover_tag,
        },
        "summary": {
            "session_count": len(sessions),
            "open_count": sum(1 for s in sessions if s.status == "open"),
            "blocked_count": sum(1 for s in sessions if s.status == "blocked"),
            "closed_count": len(closed),
            "reported_check_count": len(reported_checks),
            "done_observation_count": len(done_observations),
            "carryover_count": len(carryover_all),
            "attached_snapshot_count": sum(len(s.snapshot_ids) for s in sessions),
            "attached_artifact_count": sum(len(s.artifact_refs) for s in sessions),
        },
        "sessions": [s.to_dict() for s in sessions],
        "open_sessions": open_sessions,
        "blocked_sessions": blocked_sessions,
        "recent_closeouts": recent_closeouts,
        "reported_checks": reported_checks,
        "done_observations": done_observations,
        "carryover": carryover,
        "suggested_review_targets": _suggested_review_targets(sessions),
    }


def _session_line(session: dict[str, Any]) -> str:
    brief = session.get("brief_id") or "(no brief)"
    tags = ", ".join(session.get("tags", []) or []) or "(no tags)"
    return f"- {session['session_id']} — brief: {brief} — tags: {tags}"


def render_session_rollup_markdown(rollup: dict[str, Any]) -> str:
    """Render the rollup to advisory markdown. Presentation only; no ranking."""
    summary = rollup["summary"]
    lines: list[str] = []
    lines.append("# Chimera Work Session Rollup")
    lines.append("")
    lines.append("Advisory only. Local multi-session review context;")
    lines.append(f"{ROLLUP_ADVISORY}.")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- sessions: {summary['session_count']}")
    lines.append(f"- open: {summary['open_count']}")
    lines.append(f"- blocked: {summary['blocked_count']}")
    lines.append(f"- closed: {summary['closed_count']}")
    lines.append(f"- reported checks: {summary['reported_check_count']}")
    lines.append(f"- done observations: {summary['done_observation_count']}")
    lines.append(f"- carryover items: {summary['carryover_count']}")
    lines.append("")
    lines.append("## Open sessions")
    lines.extend([_session_line(s) for s in rollup["open_sessions"]] or ["- (none)"])
    lines.append("")
    lines.append("## Blocked sessions")
    lines.extend([_session_line(s) for s in rollup["blocked_sessions"]] or ["- (none)"])
    lines.append("")
    lines.append("## Recent closeouts")
    lines.extend([_session_line(s) for s in rollup["recent_closeouts"]] or ["- (none)"])
    lines.append("")
    lines.append("## Reported checks")
    checks = [
        f"- [{c['session_id']}] {c.get('check') or '(unspecified)'}"
        for c in rollup["reported_checks"]
    ]
    lines.extend(checks or ["- (none)"])
    lines.append("")
    lines.append("## Done observations")
    dones = [
        f"- [{d['session_id']}] {d.get('done_criterion') or '(unspecified)'} "
        f"(status: {d.get('status') or 'unknown'})"
        for d in rollup["done_observations"]
    ]
    lines.extend(dones or ["- (none)"])
    lines.append("")
    lines.append("## Carryover inbox")
    carry = [
        f"- [{c['session_id']}] {c.get('carryover') or c.get('note') or '(empty)'}"
        + (f" — tags: {', '.join(c['tags'])}" if c.get("tags") else "")
        for c in rollup["carryover"]
    ]
    lines.extend(carry or ["- (none)"])
    lines.append("")
    lines.append("## Suggested review targets")
    lines.extend([f"- {t}" for t in rollup["suggested_review_targets"]] or ["- (none)"])
    return "\n".join(lines)


def _hashed_entry(name: str, data: bytes) -> dict[str, Any]:
    return {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def _rollup_readme(names: list[str]) -> str:
    lines = [
        "# Chimera Work Session Rollup",
        "",
        "A portable, local, advisory multi-session review board for the next reviewer:",
        "",
    ]
    lines.extend(f"- `{n}`" for n in names)
    lines.append("")
    lines.append(
        "Advisory only — local multi-session review context; not a correctness, safety, "
        "approval, merge, or production-readiness signal. Not a task queue or router."
    )
    return "\n".join(lines) + "\n"


def write_rollup_bundle(
    rollup: dict[str, Any],
    *,
    output_dir: Path,
    force: bool = False,
) -> dict[str, Any]:
    """Write a portable rollup bundle and return the manifest dict.

    Writes only into ``output_dir`` (never the memory store). Parent must exist;
    a non-empty dir is refused without ``force``.
    """
    if output_dir.exists() and output_dir.is_file():
        raise RollupError(f"output path is a file, not a directory: {output_dir}")
    if not output_dir.parent.exists():
        raise RollupError(f"parent directory does not exist: {output_dir.parent}")
    if output_dir.exists():
        existing = [p.name for p in output_dir.iterdir()]
        if existing and not force:
            raise RollupError(
                f"output directory is not empty: {output_dir} (use --force to overwrite)"
            )
    else:
        output_dir.mkdir()

    rendered: dict[str, str] = {
        _ROLLUP_MD: render_session_rollup_markdown(rollup) + "\n",
        _ROLLUP_JSON: json.dumps(rollup, sort_keys=True, indent=2) + "\n",
    }
    order = [_ROLLUP_MD, _ROLLUP_JSON]
    rendered[_README] = _rollup_readme(order + [_MANIFEST])
    order.append(_README)

    file_entries: list[dict[str, Any]] = []
    for name in order:
        data = rendered[name].encode("utf-8")
        (output_dir / name).write_bytes(data)
        file_entries.append(_hashed_entry(name, data))

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "artifact": ROLLUP_BUNDLE_ARTIFACT,
        "generated_at": rollup.get("generated_at"),
        "advisory": ROLLUP_ADVISORY,
        "files": file_entries,
    }
    (output_dir / _MANIFEST).write_bytes(
        (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")
    )
    return manifest
