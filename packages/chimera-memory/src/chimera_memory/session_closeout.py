"""Chimera Agent Session Closeout v0 — a local, advisory end-of-session summary.

A Session Closeout Pack summarizes what happened in one Work Session after the
agent task ends: the session state, the original Work Brief, attached review-thread
snapshots, the local packet comparison between the first and latest attached
snapshot, the checks the agent *reported* running, the done-criteria the agent
*reported* addressing, attached artifacts, and carryover for the next agent.

Everything is reported / advisory. Nothing is judged correct, safe, approved, or
merge-ready. It composes existing read-only projections (work session events, the
work brief, and the packet diff); building it writes nothing to the memory store
(``--output`` / ``closeout-bundle`` write only the files you name).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from chimera_memory.storage import MemoryStore
from chimera_memory.work_packet import _THREAD_PACKETS, diff_packets, load_packet_dict
from chimera_memory.work_session import events_for_session, find_session

SCHEMA_VERSION = 1
CLOSEOUT_ARTIFACT = "chimera_agent_session_closeout"
CLOSEOUT_BUNDLE_ARTIFACT = "chimera_agent_session_closeout_bundle"
CLOSEOUT_ADVISORY = (
    "local session closeout context only; not a correctness, safety, approval, "
    "merge, production-readiness, or speed guarantee"
)


class CloseoutError(Exception):
    """Raised for closeout precondition failures (clean CLI errors)."""


def _load_snapshot_packet(thread_dir: str, snapshot_id: str) -> dict[str, Any] | None:
    try:
        return load_packet_dict(Path(thread_dir) / _THREAD_PACKETS / snapshot_id)
    except (OSError, json.JSONDecodeError):
        return None


def _snapshot_delta(session: dict[str, Any]) -> dict[str, Any] | None:
    """First-vs-latest attached-snapshot packet comparison (local). Read-only."""
    snapshot_ids = session.get("snapshot_ids", []) or []
    thread_dir = session.get("thread_dir")
    if not snapshot_ids:
        return None
    if len(snapshot_ids) == 1:
        return {"mode": "single", "snapshot_id": snapshot_ids[0]}
    if not thread_dir:
        return None
    old_id, new_id = snapshot_ids[0], snapshot_ids[-1]
    old_packet = _load_snapshot_packet(thread_dir, old_id)
    new_packet = _load_snapshot_packet(thread_dir, new_id)
    if old_packet is None or new_packet is None:
        return None
    return {
        "mode": "first-vs-latest",
        "old_snapshot_id": old_id,
        "new_snapshot_id": new_id,
        "diff": diff_packets(old_packet, new_packet, old_path=old_id, new_path=new_id),
    }


def _suggested_review_targets(
    session: dict[str, Any], reported_checks: list[dict[str, Any]],
    carryover: list[dict[str, Any]],
) -> list[str]:
    targets: list[str] = []
    thread_dir = session.get("thread_dir")
    snapshot_ids = session.get("snapshot_ids", []) or []
    if thread_dir and snapshot_ids:
        latest_packet = f"{thread_dir}/{_THREAD_PACKETS}/{snapshot_ids[-1]}/WORK_PACKET.md"
        targets.append(f"Latest packet: {latest_packet}")
    if session.get("kickoff_pack_dir"):
        targets.append(f"Kickoff pack: {session['kickoff_pack_dir']}")
    for ref in session.get("artifact_refs", []) or []:
        targets.append(f"Artifact: {ref}")
    for c in reported_checks:
        if c.get("check"):
            targets.append(f"Reported check: {c['check']}")
    for c in carryover:
        if c.get("carryover"):
            targets.append(f"Carryover: {c['carryover']}")
    return targets


def build_session_closeout(
    store: MemoryStore, session_id: str, *, generated_at: str
) -> dict[str, Any] | None:
    """Build the closeout dict for a session, or None if the session is unknown.

    Read-only; writes nothing. Composes the session projection, the work brief,
    and a first-vs-latest packet comparison from attached snapshots.
    """
    session = find_session(store, session_id)
    if session is None:
        return None
    events = events_for_session(store, session_id)

    reported_checks = [
        {"check": e.check, "note": e.note, "created_at": e.created_at}
        for e in events
        if e.event_kind == "check_reported"
    ]
    done_observations = [
        {"done_criterion": e.done_criterion, "status": e.status, "note": e.note,
         "created_at": e.created_at}
        for e in events
        if e.event_kind == "done_observed"
    ]
    carryover = [
        {"carryover": e.carryover, "tags": list(e.tags), "note": e.note,
         "created_at": e.created_at}
        for e in events
        if e.event_kind == "carryover_noted"
    ]

    work_brief: dict[str, Any] | None = None
    if session.brief_id:
        from chimera_memory.work_brief import find_work_brief

        brief = find_work_brief(store, session.brief_id)
        work_brief = brief.to_dict() if brief else None

    session_dict = session.to_dict()
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact": CLOSEOUT_ARTIFACT,
        "advisory": CLOSEOUT_ADVISORY,
        "generated_at": generated_at,
        "session": session_dict,
        "work_brief": work_brief,
        "snapshot_delta": _snapshot_delta(session_dict),
        "reported_checks": reported_checks,
        "done_observations": done_observations,
        "carryover": carryover,
        "attached_artifacts": list(session.artifact_refs),
        "suggested_review_targets": _suggested_review_targets(
            session_dict, reported_checks, carryover
        ),
    }


def render_session_closeout_markdown(closeout: dict[str, Any]) -> str:
    """Render the closeout as advisory markdown. Presentation only."""
    s = closeout["session"]
    lines: list[str] = []
    lines.append("# Chimera Agent Session Closeout")
    lines.append("")
    lines.append("Advisory only. Local session closeout context;")
    lines.append(f"{CLOSEOUT_ADVISORY}.")
    lines.append("")
    lines.append("## Session")
    lines.append(f"- session_id: {s.get('session_id')}")
    lines.append(f"- status: {s.get('status')}")
    lines.append(f"- brief: {s.get('brief_id') or '(none)'}")
    lines.append(f"- review thread: {s.get('thread_dir') or '(none)'}")
    lines.append(f"- kickoff pack: {s.get('kickoff_pack_dir') or '(none)'}")
    lines.append("")
    lines.append("## Original work brief")
    wb = closeout.get("work_brief")
    if wb:
        lines.append(f"- title: {wb.get('title', '')}")
        lines.append(f"- objective: {wb.get('objective', '')}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Snapshot delta")
    lines.append("")
    lines.append("Local packet comparison only.")
    delta = closeout.get("snapshot_delta")
    if delta and delta.get("mode") == "first-vs-latest":
        d = delta["diff"].get("summary_delta", {})
        lines.append(f"- claims shown: {d.get('shown_claim_count', 0):+d}")
        lines.append(f"- unresolved: {d.get('open_or_unresolved_count', 0):+d}")
        lines.append(f"- tool lessons: {d.get('tool_note_count', 0):+d}")
        lines.append(f"- candidate lessons: {d.get('candidate_count', 0):+d}")
    elif delta and delta.get("mode") == "single":
        lines.append(f"- single attached snapshot: {delta.get('snapshot_id')}")
    else:
        lines.append("- (no attached snapshots)")
    lines.append("")
    lines.append("## Reported checks")
    if closeout["reported_checks"]:
        for c in closeout["reported_checks"]:
            note = f" — {c['note']}" if c.get("note") else ""
            lines.append(f"- {c.get('check')}{note}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Done criteria observations")
    if closeout["done_observations"]:
        for c in closeout["done_observations"]:
            note = f" — {c['note']}" if c.get("note") else ""
            lines.append(f"- [{c.get('status') or 'unknown'}] {c.get('done_criterion')}{note}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Attached artifacts")
    if closeout["attached_artifacts"]:
        for ref in closeout["attached_artifacts"]:
            lines.append(f"- {ref}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Carryover for next agent")
    if closeout["carryover"]:
        for c in closeout["carryover"]:
            lines.append(f"- {c.get('carryover')}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Suggested review targets")
    if closeout["suggested_review_targets"]:
        for t in closeout["suggested_review_targets"]:
            lines.append(f"- {t}")
    else:
        lines.append("- (none)")
    return "\n".join(lines)


# ── bundle ───────────────────────────────────────────────────────────────────

_CLOSEOUT_MD = "SESSION_CLOSEOUT.md"
_CLOSEOUT_JSON = "session-closeout.json"
_SESSION_MD = "SESSION.md"
_SESSION_JSON = "session.json"
_BRIEF_MD = "WORK_BRIEF.md"
_BRIEF_JSON = "work-brief.json"
_SNAPSHOT_DIFF = "snapshot-diff.json"
_KICKOFF_REF = "kickoff-pack-ref.txt"
_README = "README.md"
_MANIFEST = "manifest.json"


def _hashed_entry(name: str, data: bytes) -> dict[str, Any]:
    return {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def _closeout_readme(names: list[str]) -> str:
    lines = [
        "# Chimera Agent Session Closeout Pack",
        "",
        "A portable, local, advisory end-of-session summary for the next reviewer:",
        "",
    ]
    lines.extend(f"- `{n}`" for n in names)
    lines.append("")
    lines.append(
        "Advisory only — local session closeout context; not a correctness, safety, "
        "approval, merge, or production-readiness signal."
    )
    return "\n".join(lines) + "\n"


def write_closeout_bundle(
    closeout: dict[str, Any],
    *,
    output_dir: Path,
    session_markdown: str,
    brief_markdown: str | None,
    force: bool = False,
) -> dict[str, Any]:
    """Write a portable closeout bundle and return the manifest dict.

    Writes only into ``output_dir`` (never the memory store). Parent must exist;
    a non-empty dir is refused without ``force``.
    """
    if output_dir.exists() and output_dir.is_file():
        raise CloseoutError(f"output path is a file, not a directory: {output_dir}")
    if not output_dir.parent.exists():
        raise CloseoutError(f"parent directory does not exist: {output_dir.parent}")
    if output_dir.exists():
        existing = [p.name for p in output_dir.iterdir()]
        if existing and not force:
            raise CloseoutError(
                f"output directory is not empty: {output_dir} (use --force to overwrite)"
            )
    else:
        output_dir.mkdir()

    session = closeout["session"]
    rendered: dict[str, str] = {
        _CLOSEOUT_MD: render_session_closeout_markdown(closeout) + "\n",
        _CLOSEOUT_JSON: json.dumps(closeout, sort_keys=True, indent=2) + "\n",
        _SESSION_MD: session_markdown + "\n",
        _SESSION_JSON: json.dumps(session, sort_keys=True, indent=2) + "\n",
        _BRIEF_MD: (brief_markdown or "# (no work brief)\n"),
        _BRIEF_JSON: json.dumps(closeout.get("work_brief") or {}, sort_keys=True, indent=2) + "\n",
    }
    order = [_CLOSEOUT_MD, _CLOSEOUT_JSON, _SESSION_MD, _SESSION_JSON, _BRIEF_MD, _BRIEF_JSON]

    delta = closeout.get("snapshot_delta")
    if delta and delta.get("mode") == "first-vs-latest":
        rendered[_SNAPSHOT_DIFF] = json.dumps(delta["diff"], sort_keys=True, indent=2) + "\n"
        order.append(_SNAPSHOT_DIFF)
    if session.get("kickoff_pack_dir"):
        rendered[_KICKOFF_REF] = str(session["kickoff_pack_dir"]) + "\n"
        order.append(_KICKOFF_REF)

    rendered[_README] = _closeout_readme(order + [_MANIFEST])
    order.append(_README)

    file_entries: list[dict[str, Any]] = []
    for name in order:
        data = rendered[name].encode("utf-8")
        (output_dir / name).write_bytes(data)
        file_entries.append(_hashed_entry(name, data))

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "artifact": CLOSEOUT_BUNDLE_ARTIFACT,
        "generated_at": closeout.get("generated_at"),
        "advisory": CLOSEOUT_ADVISORY,
        "session_id": session.get("session_id"),
        "files": file_entries,
    }
    (output_dir / _MANIFEST).write_bytes(
        (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")
    )
    return manifest
