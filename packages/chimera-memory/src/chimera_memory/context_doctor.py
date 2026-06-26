"""Agent Context Doctor (advisory local context-hygiene report).

The Context Doctor reads the existing v0.29 session stack (work-session events +
projections and work briefs) and reports *findings* about missing, stale, or
incomplete session context before another agent continues work: open sessions
with no closeout events, blocked sessions with carryover to review, sessions with
no attached snapshots or no reported checks, work briefs not linked to a session,
and explicitly referenced review-thread / kickoff-pack directories that are
missing on disk.

Everything is advisory. Findings are observations, not verdicts: nothing here
approves, scores, ranks, certifies, or judges work, and no checks are executed.
Building the report composes existing read-only readers; it writes nothing to the
memory store (``--output`` / ``context-doctor bundle`` write only the files you
name).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from chimera_memory.storage import MemoryStore
from chimera_memory.work_brief import read_work_briefs
from chimera_memory.work_session import (
    filter_sessions,
    read_session_events,
    sessions_for_store,
)

SCHEMA_VERSION = 1
DOCTOR_ARTIFACT = "chimera_context_doctor"
DOCTOR_BUNDLE_ARTIFACT = "chimera_context_doctor_bundle"
DOCTOR_ADVISORY = (
    "local context hygiene report only; not a correctness, safety, approval, "
    "merge, production-readiness, or speed guarantee"
)

FINDING_KINDS = frozenset({
    "open_session_without_closeout",
    "blocked_session_with_carryover",
    "session_without_snapshots",
    "session_without_reported_checks",
    "brief_without_session",
    "missing_thread_dir",
    "missing_kickoff_pack_dir",
    "closeout_without_carryover_review",
    "session_without_harness_runs",
    "harness_run_without_session",
    "harness_run_output_truncated",
})

_CLOSEOUT_KINDS = frozenset({
    "check_reported", "done_observed", "carryover_noted", "closeout_created",
})

_DOCTOR_MD = "CONTEXT_DOCTOR.md"
_DOCTOR_JSON = "context-doctor.json"
_MANIFEST = "manifest.json"
_README = "README.md"


class DoctorError(Exception):
    """Raised for doctor bundle precondition failures (clean CLI errors)."""


def _finding_id(kind: str, subject: str) -> str:
    digest = hashlib.sha256(f"{kind}\x1f{subject}".encode()).hexdigest()[:16]
    return f"ctx_{digest}"


def _finding(
    kind: str,
    message: str,
    *,
    session_id: str | None = None,
    brief_id: str | None = None,
    refs: list[str] | None = None,
    suggested_inspection: list[str] | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "finding_id": _finding_id(kind, session_id or brief_id or (refs[0] if refs else "")),
        "kind": kind,
        "message": message,
        "session_id": session_id,
        "brief_id": brief_id,
        "refs": list(refs or []),
        "suggested_inspection": list(suggested_inspection or []),
        "tags": list(tags or []),
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


def _suggested_review_targets(findings: list[dict[str, Any]]) -> list[str]:
    """Deterministic inspection pointers drawn from the findings. No ranking."""
    targets: list[str] = []
    targets += [
        f"Open session: {f['session_id']}"
        for f in findings if f["kind"] == "open_session_without_closeout"
    ]
    targets += [
        f"Blocked session: {f['session_id']}"
        for f in findings if f["kind"] == "blocked_session_with_carryover"
    ]
    for f in findings:
        if f["kind"] in ("missing_thread_dir", "missing_kickoff_pack_dir"):
            targets += [f"Missing referenced path: {r}" for r in f["refs"]]
    targets += [
        f"Unlinked work brief: {f['brief_id']}"
        for f in findings if f["kind"] == "brief_without_session"
    ]
    return _dedup(targets)


def build_context_doctor(
    store: MemoryStore,
    *,
    generated_at: str,
    status: str | None = None,
    tag: str | None = None,
    limit_findings: int | None = None,
) -> dict[str, Any]:
    """Build the read-only context-hygiene report. Writes nothing; executes nothing.

    Exact filters only (``status`` / ``tag`` select which sessions are examined).
    Brief findings are reported only when no ``status`` filter is set. Limits apply
    after the full finding count is computed (``summary.finding_count`` is the total).
    """
    all_sessions = sessions_for_store(store)
    sessions = filter_sessions(all_sessions, status=status, tag=tag)
    events_by_session: dict[str, list[Any]] = {}
    for ev in read_session_events(store):
        events_by_session.setdefault(ev.session_id, []).append(ev)

    briefs = read_work_briefs(store)
    linked_brief_ids = {s.brief_id for s in all_sessions if s.brief_id}

    from chimera_memory.harness_run import read_harness_runs

    all_runs = read_harness_runs(store)
    all_session_ids = {s.session_id for s in all_sessions}
    runs_by_session: dict[str, int] = {}
    for r in all_runs:
        if r.work_session_id:
            runs_by_session[r.work_session_id] = runs_by_session.get(r.work_session_id, 0) + 1

    findings: list[dict[str, Any]] = []
    for s in sessions:
        kinds = {ev.event_kind for ev in events_by_session.get(s.session_id, [])}
        has_carryover = "carryover_noted" in kinds
        has_closeout_ctx = bool(kinds & _CLOSEOUT_KINDS)
        show = f"chimera-memory work-session show {s.session_id}"
        tags = list(s.tags)

        if s.status == "open" and not has_closeout_ctx:
            findings.append(_finding(
                "open_session_without_closeout", "Open session has no closeout events.",
                session_id=s.session_id, brief_id=s.brief_id, tags=tags,
                suggested_inspection=[
                    show, f"chimera-memory work-session closeout {s.session_id}"],
            ))
        if s.status == "blocked" and has_carryover:
            findings.append(_finding(
                "blocked_session_with_carryover",
                "Blocked session has carryover items to review.",
                session_id=s.session_id, brief_id=s.brief_id, tags=tags,
                suggested_inspection=[show, "chimera-memory work-session rollup --status blocked"],
            ))
        if not s.snapshot_ids:
            findings.append(_finding(
                "session_without_snapshots", "Session has no attached snapshots.",
                session_id=s.session_id, brief_id=s.brief_id, tags=tags,
                suggested_inspection=[show],
            ))
        if "check_reported" not in kinds:
            findings.append(_finding(
                "session_without_reported_checks", "Session has no reported checks.",
                session_id=s.session_id, brief_id=s.brief_id, tags=tags,
                suggested_inspection=[
                    show, f"chimera-memory work-session report-check {s.session_id} --check ..."],
            ))
        if has_closeout_ctx and not has_carryover:
            carry_hint = (
                f"chimera-memory work-session note-carryover {s.session_id} --carryover ..."
            )
            findings.append(_finding(
                "closeout_without_carryover_review",
                "Session recorded closeout activity but no carryover for the next agent.",
                session_id=s.session_id, brief_id=s.brief_id, tags=tags,
                suggested_inspection=[show, carry_hint],
            ))
        if s.thread_dir and not Path(s.thread_dir).exists():
            findings.append(_finding(
                "missing_thread_dir", "Referenced review thread directory is missing.",
                session_id=s.session_id, brief_id=s.brief_id, refs=[s.thread_dir], tags=tags,
                suggested_inspection=[show],
            ))
        if s.kickoff_pack_dir and not Path(s.kickoff_pack_dir).exists():
            findings.append(_finding(
                "missing_kickoff_pack_dir", "Referenced kickoff pack directory is missing.",
                session_id=s.session_id, brief_id=s.brief_id, refs=[s.kickoff_pack_dir], tags=tags,
                suggested_inspection=[show],
            ))
        if runs_by_session.get(s.session_id, 0) == 0:
            findings.append(_finding(
                "session_without_harness_runs",
                "Session has no attached harness run observations.",
                session_id=s.session_id, brief_id=s.brief_id, tags=tags,
                suggested_inspection=[
                    show, f"chimera-memory harness list --work-session {s.session_id}"],
            ))

    if status is None:
        for b in briefs:
            if b.brief_id in linked_brief_ids:
                continue
            if tag is not None and tag not in b.tags:
                continue
            findings.append(_finding(
                "brief_without_session", "Work brief is not linked to any work session.",
                brief_id=b.brief_id, tags=list(b.tags),
                suggested_inspection=[
                    f"chimera-memory work-brief show {b.brief_id}",
                    f"chimera-memory work-session start --brief {b.brief_id}"],
            ))

    if status is None:
        for r in all_runs:
            if not r.work_session_id or r.work_session_id not in all_session_ids:
                findings.append(_finding(
                    "harness_run_without_session",
                    "Harness run is not attached to a known work session.",
                    tags=list(r.tags),
                    refs=[r.run_id],
                    suggested_inspection=[f"chimera-memory harness show {r.run_id}"],
                ))
        for r in all_runs:
            if r.output_truncated:
                findings.append(_finding(
                    "harness_run_output_truncated",
                    "Harness run output was truncated; full output is hashed, not stored.",
                    tags=list(r.tags),
                    refs=[r.run_id],
                    suggested_inspection=[f"chimera-memory harness show {r.run_id}"],
                ))

    carryover_count = sum(
        1
        for s in sessions
        for ev in events_by_session.get(s.session_id, [])
        if ev.event_kind == "carryover_noted"
    )
    listed = findings[:limit_findings] if limit_findings is not None else findings

    return {
        "schema_version": SCHEMA_VERSION,
        "artifact": DOCTOR_ARTIFACT,
        "advisory": DOCTOR_ADVISORY,
        "generated_at": generated_at,
        "filters": {"status": status, "tag": tag, "limit_findings": limit_findings},
        "summary": {
            "session_count": len(sessions),
            "brief_count": len(briefs),
            "finding_count": len(findings),
            "open_session_count": sum(1 for s in sessions if s.status == "open"),
            "blocked_session_count": sum(1 for s in sessions if s.status == "blocked"),
            "carryover_count": carryover_count,
        },
        "findings": listed,
        "suggested_review_targets": _suggested_review_targets(findings),
    }


def render_context_doctor_markdown(doctor: dict[str, Any]) -> str:
    """Render the report to advisory markdown. Presentation only; no ranking."""
    summary = doctor["summary"]
    lines: list[str] = []
    lines.append("# Chimera Context Doctor")
    lines.append("")
    lines.append("Advisory only. Local context hygiene report;")
    lines.append(f"{DOCTOR_ADVISORY}.")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- sessions: {summary['session_count']}")
    lines.append(f"- work briefs: {summary['brief_count']}")
    lines.append(f"- findings: {summary['finding_count']}")
    lines.append(f"- open sessions: {summary['open_session_count']}")
    lines.append(f"- blocked sessions: {summary['blocked_session_count']}")
    lines.append(f"- carryover items: {summary['carryover_count']}")
    lines.append("")
    lines.append("## Findings")
    findings = doctor["findings"]
    if not findings:
        lines.append("- no findings")
    for f in findings:
        subject = f.get("session_id") or f.get("brief_id") or "(none)"
        lines.append(f"- [{f['kind']}] {subject}")
        lines.append(f"  Message: {f['message']}")
        if f.get("suggested_inspection"):
            lines.append("  Suggested inspection:")
            lines.extend(f"  - {cmd}" for cmd in f["suggested_inspection"])
    lines.append("")
    lines.append("## Suggested review targets")
    targets = doctor["suggested_review_targets"]
    lines.extend([f"- {t}" for t in targets] or ["- (none)"])
    return "\n".join(lines)


def _hashed_entry(name: str, data: bytes) -> dict[str, Any]:
    return {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def _doctor_readme(names: list[str]) -> str:
    lines = [
        "# Chimera Context Doctor",
        "",
        "A portable, local, advisory context-hygiene report for the next reviewer:",
        "",
    ]
    lines.extend(f"- `{n}`" for n in names)
    lines.append("")
    lines.append(
        "Advisory only — local context hygiene report; not a correctness, safety, "
        "approval, merge, or production-readiness signal. Findings are observations, "
        "not verdicts; nothing here is executed or scored."
    )
    return "\n".join(lines) + "\n"


def write_doctor_bundle(
    doctor: dict[str, Any],
    *,
    output_dir: Path,
    force: bool = False,
) -> dict[str, Any]:
    """Write a portable doctor bundle and return the manifest dict.

    Writes only into ``output_dir`` (never the memory store). Parent must exist;
    a non-empty dir is refused without ``force``.
    """
    if output_dir.exists() and output_dir.is_file():
        raise DoctorError(f"output path is a file, not a directory: {output_dir}")
    if not output_dir.parent.exists():
        raise DoctorError(f"parent directory does not exist: {output_dir.parent}")
    if output_dir.exists():
        existing = [p.name for p in output_dir.iterdir()]
        if existing and not force:
            raise DoctorError(
                f"output directory is not empty: {output_dir} (use --force to overwrite)"
            )
    else:
        output_dir.mkdir()

    rendered: dict[str, str] = {
        _DOCTOR_MD: render_context_doctor_markdown(doctor) + "\n",
        _DOCTOR_JSON: json.dumps(doctor, sort_keys=True, indent=2) + "\n",
    }
    order = [_DOCTOR_MD, _DOCTOR_JSON]
    rendered[_README] = _doctor_readme(order + [_MANIFEST])
    order.append(_README)

    file_entries: list[dict[str, Any]] = []
    for name in order:
        data = rendered[name].encode("utf-8")
        (output_dir / name).write_bytes(data)
        file_entries.append(_hashed_entry(name, data))

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "artifact": DOCTOR_BUNDLE_ARTIFACT,
        "generated_at": doctor.get("generated_at"),
        "advisory": DOCTOR_ADVISORY,
        "files": file_entries,
    }
    (output_dir / _MANIFEST).write_bytes(
        (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")
    )
    return manifest
