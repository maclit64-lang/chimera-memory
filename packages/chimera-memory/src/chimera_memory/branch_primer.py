"""Chimera Agent / Branch Primer v0 — local starting-context artifact.

A Branch Primer tells the next agent what local context to read before starting
work. It composes existing read-only projections — no duplicated logic:

    build_work_packet (claims / open items / inspection targets / tool notes /
        candidate lessons / counts)
    + optional review-thread index + latest-snapshot delta

It answers: what is the current local work state, what is unresolved, what to
inspect first, which Tool Notes apply, which Candidate Lessons to review, and —
if a review thread is supplied — what changed since the previous packet.

It is **advisory and local-only** — local work context and operational memory,
never a correctness, safety, approval, merge, or production-readiness signal, and
not a form of verification. It is read-only (the CLI ``--output`` flag writes only
the file you name) and is a starting-context artifact, not a verdict.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chimera_memory.handoff import HandoffTarget
from chimera_memory.storage import MemoryStore
from chimera_memory.tool_activity import CandidateLesson
from chimera_memory.tool_notes import ToolNote
from chimera_memory.work_packet import (
    ThreadError,
    WorkPacket,
    build_work_packet,
    read_thread_index,
    thread_diff_by_id,
    thread_diff_latest,
)

SCHEMA_VERSION = 1
PRIMER_ARTIFACT = "chimera_branch_primer"

PRIMER_ADVISORY = (
    "local work context and operational memory only; not a correctness, safety, "
    "approval, merge, production-readiness, or speed guarantee"
)

_BUNDLE_MD = "WORK_PACKET.md"
_THREAD_PACKETS = "packets"


@dataclass(frozen=True)
class BranchPrimerFilters:
    claim_id: str | None = None
    session_id: str | None = None
    status: str | None = None
    task_kind: str | None = None
    tag: str | None = None
    thread_dir: str | None = None
    since: str | None = None
    limit_tool_notes: int | None = None
    limit_candidates: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "session_id": self.session_id,
            "status": self.status,
            "task_kind": self.task_kind,
            "tag": self.tag,
            "thread_dir": self.thread_dir,
            "since": self.since,
            "limit_tool_notes": self.limit_tool_notes,
            "limit_candidates": self.limit_candidates,
        }


@dataclass(frozen=True)
class BranchPrimerSummary:
    shown_claim_count: int
    open_or_unresolved_count: int
    next_inspection_target_count: int
    tool_note_count: int
    candidate_count: int
    thread_snapshot_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "shown_claim_count": self.shown_claim_count,
            "open_or_unresolved_count": self.open_or_unresolved_count,
            "next_inspection_target_count": self.next_inspection_target_count,
            "tool_note_count": self.tool_note_count,
            "candidate_count": self.candidate_count,
            "thread_snapshot_count": self.thread_snapshot_count,
        }


@dataclass(frozen=True)
class BranchPrimer:
    schema_version: int
    artifact: str
    advisory: str
    generated_at: str
    filters: BranchPrimerFilters
    summary: BranchPrimerSummary
    work_packet: dict[str, Any]
    thread_delta: dict[str, Any] | None
    work_brief: dict[str, Any] | None
    next_inspection_targets: tuple[HandoffTarget, ...]
    tool_notes: tuple[ToolNote, ...]
    candidate_tool_lessons: tuple[CandidateLesson, ...]
    suggested_first_read: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact": self.artifact,
            "advisory": self.advisory,
            "generated_at": self.generated_at,
            "filters": self.filters.to_dict(),
            "summary": self.summary.to_dict(),
            "work_packet": self.work_packet,
            "thread_delta": self.thread_delta,
            "work_brief": self.work_brief,
            "next_inspection_targets": [t.to_dict() for t in self.next_inspection_targets],
            "tool_notes": [n.to_dict() for n in self.tool_notes],
            "candidate_tool_lessons": [c.to_dict() for c in self.candidate_tool_lessons],
            "suggested_first_read": list(self.suggested_first_read),
        }


def _compact_packet(packet: WorkPacket) -> dict[str, Any]:
    """A compact reference to the underlying packet (no duplicated detail lists)."""
    return {
        "artifact": packet.artifact,
        "advisory": packet.advisory,
        "generated_at": packet.generated_at,
        "filters": packet.filters.to_dict(),
        "summary": packet.summary.to_dict(),
    }


def _suggested_first_read(
    packet: WorkPacket,
    *,
    store_label: str,
    thread_dir: Path | None,
    latest_snapshot: dict[str, Any] | None,
) -> list[str]:
    """A deterministic inspection list — what to read, never an action to run."""
    reads: list[str] = [f"Local memory store: {store_label}"]
    if thread_dir is not None and latest_snapshot is not None:
        sid = latest_snapshot.get("snapshot_id", "")
        reads.append(f"Review thread index: {thread_dir}/INDEX.md")
        reads.append(f"Latest packet: {thread_dir}/{_THREAD_PACKETS}/{sid}/{_BUNDLE_MD}")
    for target in packet.next_inspection_targets:
        reads.append(f"Inspect claim {target.claim_id}: {target.reason}")
    if packet.tool_notes:
        reads.append(
            f"Relevant tool lessons: {len(packet.tool_notes)} "
            "(chimera-memory tool-notes list)"
        )
    if packet.candidate_tool_lessons:
        reads.append(
            f"Candidate lessons to review: {len(packet.candidate_tool_lessons)} "
            "(chimera-memory tool-notes candidates)"
        )
    return reads


def build_branch_primer(
    store: MemoryStore,
    *,
    generated_at: str,
    store_label: str,
    claim_id: str | None = None,
    session_id: str | None = None,
    status: str | None = None,
    task_kind: str | None = None,
    tag: str | None = None,
    thread_dir: Path | None = None,
    since: str | None = None,
    limit_tool_notes: int | None = None,
    limit_candidates: int | None = None,
    work_brief: dict[str, Any] | None = None,
    extra_first_read: tuple[str, ...] = (),
) -> BranchPrimer:
    """Compose a BranchPrimer from the local ledger (and an optional review thread).

    Read-only; writes nothing. Reuses ``build_work_packet`` and the read-only
    review-thread helpers. Raises :class:`ThreadError` if ``thread_dir`` is given
    but has no readable index.
    """
    packet = build_work_packet(
        store,
        generated_at=generated_at,
        claim_id=claim_id,
        session_id=session_id,
        status=status,
        task_kind=task_kind,
        tag=tag,
        limit_tool_notes=limit_tool_notes,
        limit_candidates=limit_candidates,
    )

    thread_snapshot_count = 0
    latest_snapshot: dict[str, Any] | None = None
    thread_delta: dict[str, Any] | None = None
    if since is not None and thread_dir is None:
        raise ThreadError("--since requires a review thread directory")
    if thread_dir is not None:
        index = read_thread_index(thread_dir)
        if index is None:
            raise ThreadError(f"no review thread index at {thread_dir}")
        snapshots = index.get("snapshots", [])
        thread_snapshot_count = len(snapshots)
        if snapshots:
            latest_snapshot = snapshots[-1]
        if since is not None:
            if latest_snapshot is None:
                raise ThreadError("review thread has no latest snapshot to compare against")
            known = {s["snapshot_id"] for s in snapshots}
            if since not in known:
                raise ThreadError(f"unknown snapshot id: {since}")
            new_id = latest_snapshot["snapshot_id"]
            thread_delta = {
                "mode": "since",
                "old_snapshot_id": since,
                "new_snapshot_id": new_id,
                "diff": thread_diff_by_id(thread_dir, since, new_id),
            }
        elif thread_snapshot_count >= 2:
            thread_delta = {
                "mode": "latest-two",
                "old_snapshot_id": snapshots[-2]["snapshot_id"],
                "new_snapshot_id": snapshots[-1]["snapshot_id"],
                "diff": thread_diff_latest(thread_dir),
            }

    summary = BranchPrimerSummary(
        shown_claim_count=packet.summary.shown_claim_count,
        open_or_unresolved_count=packet.summary.open_or_unresolved_count,
        next_inspection_target_count=packet.summary.next_inspection_target_count,
        tool_note_count=packet.summary.tool_note_count,
        candidate_count=packet.summary.candidate_count,
        thread_snapshot_count=thread_snapshot_count,
    )
    return BranchPrimer(
        schema_version=SCHEMA_VERSION,
        artifact=PRIMER_ARTIFACT,
        advisory=PRIMER_ADVISORY,
        generated_at=generated_at,
        filters=BranchPrimerFilters(
            claim_id=claim_id,
            session_id=session_id,
            status=status,
            task_kind=task_kind,
            tag=tag,
            thread_dir=str(thread_dir) if thread_dir is not None else None,
            since=since,
            limit_tool_notes=limit_tool_notes,
            limit_candidates=limit_candidates,
        ),
        summary=summary,
        work_packet=_compact_packet(packet),
        thread_delta=thread_delta,
        work_brief=work_brief,
        next_inspection_targets=packet.next_inspection_targets,
        tool_notes=packet.tool_notes,
        candidate_tool_lessons=packet.candidate_tool_lessons,
        suggested_first_read=tuple(
            _suggested_first_read(
                packet, store_label=store_label, thread_dir=thread_dir,
                latest_snapshot=latest_snapshot,
            )
            + list(extra_first_read)
        ),
    )


def _filter_label(filters: BranchPrimerFilters) -> str:
    active = {k: v for k, v in filters.to_dict().items() if v is not None}
    return " ".join(f"{k}={v}" for k, v in active.items()) if active else "none"


def _delta(value: int) -> str:
    return f"+{value}" if value > 0 else str(value)


def render_branch_primer_markdown(primer: BranchPrimer, *, store_label: str) -> str:
    """Render the primer as advisory markdown. Presentation only."""
    s = primer.summary
    f = primer.filters
    lines: list[str] = []
    lines.append("# Chimera Branch Primer")
    lines.append("")
    lines.append(f"Advisory only. {primer.advisory}.")
    lines.append("")
    lines.append("## Start here")
    lines.append(f"- generated_at: {primer.generated_at}")
    lines.append(f"- memory root: {store_label}")
    lines.append(f"- filters: {_filter_label(f)}")
    lines.append(f"- review thread: {f.thread_dir or '(none)'}")
    lines.append("")
    if primer.work_brief is not None:
        wb = primer.work_brief
        lines.append("## Work brief")
        lines.append("")
        lines.append(f"- title: {wb.get('title', '')}")
        lines.append(f"- objective: {wb.get('objective', '')}")
        scope = ", ".join(wb.get("scope_paths", []) or []) or "(none)"
        lines.append(f"- scope: {scope}")
        checks = wb.get("checks", []) or []
        lines.append(f"- checks to report: {len(checks)}")
        done = wb.get("done_criteria", []) or []
        lines.append(f"- done criteria: {len(done)}")
        lines.append("")
    lines.append("## Current work state")
    lines.append(f"- claims shown: {s.shown_claim_count}")
    lines.append(f"- unresolved: {s.open_or_unresolved_count}")
    lines.append(f"- next inspection targets: {s.next_inspection_target_count}")
    lines.append(f"- tool lessons: {s.tool_note_count}")
    lines.append(f"- candidate lessons: {s.candidate_count}")
    lines.append(f"- thread snapshots: {s.thread_snapshot_count}")
    lines.append("")
    if primer.thread_delta is not None:
        td = primer.thread_delta
        delta = td.get("diff", {}).get("summary_delta", {})
        if td.get("mode") == "since":
            lines.append(f"## Thread delta since {td.get('old_snapshot_id', '')}")
        else:
            lines.append("## Latest thread delta")
        lines.append(f"- claims shown: {_delta(delta.get('shown_claim_count', 0))}")
        lines.append(f"- unresolved: {_delta(delta.get('open_or_unresolved_count', 0))}")
        lines.append(f"- tool lessons: {_delta(delta.get('tool_note_count', 0))}")
        lines.append(f"- candidate lessons: {_delta(delta.get('candidate_count', 0))}")
        lines.append("")
    lines.append("## Next inspection targets")
    if primer.next_inspection_targets:
        for t in primer.next_inspection_targets:
            lines.append(f"- `{t.claim_id}` — {t.reason}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Relevant tool lessons")
    if primer.tool_notes:
        for n in primer.tool_notes:
            lines.append(f"- [{n.task_kind}] {n.tool_name} / {n.workflow_name}")
            if n.lesson:
                lines.append(f"  {n.lesson}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Candidate lessons to review")
    lines.append("")
    lines.append("Advisory only. Review before saving as Tool Notes.")
    lines.append("")
    if primer.candidate_tool_lessons:
        for c in primer.candidate_tool_lessons:
            lines.append(f"- [{c.task_kind}] {c.tool_name} / {c.workflow_name}")
            lines.append(f"  Candidate lesson: {c.lesson}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Suggested first read")
    for item in primer.suggested_first_read:
        lines.append(f"- {item}")
    return "\n".join(lines)


# ── prompt header + Agent Kickoff Pack bundle ────────────────────────────────

KICKOFF_ARTIFACT = "chimera_agent_kickoff_pack"
KICKOFF_ADVISORY = (
    "local agent starting context only; not a correctness, safety, approval, merge, "
    "production-readiness, or speed guarantee"
)
PROMPT_HEADER_ARTIFACT = "chimera_branch_primer_prompt_header"

_PACK_PRIMER_MD = "BRANCH_PRIMER.md"
_PACK_PRIMER_JSON = "branch-primer.json"
_PACK_PROMPT_HEADER = "AGENT_PROMPT_HEADER.md"
_PACK_BRIEF_MD = "WORK_BRIEF.md"
_PACK_BRIEF_JSON = "work-brief.json"
_PACK_README = "README.md"
_PACK_MANIFEST = "manifest.json"


def _pack_readme(has_brief: bool) -> str:
    lines = [
        "# Chimera Agent Kickoff Pack",
        "",
        "A portable, local, advisory starting-context package for the next agent:",
        "",
        f"- `{_PACK_PROMPT_HEADER}` — a pasteable agent prompt header (read this first).",
        f"- `{_PACK_PRIMER_MD}` — the human-readable branch primer.",
        f"- `{_PACK_PRIMER_JSON}` — the machine-readable branch primer.",
    ]
    if has_brief:
        lines.append(f"- `{_PACK_BRIEF_MD}` — the human-readable work brief (task contract).")
        lines.append(f"- `{_PACK_BRIEF_JSON}` — the machine-readable work brief.")
    lines.append(f"- `{_PACK_MANIFEST}` — the bundle manifest (file list + sha256 + byte counts).")
    lines.append(f"- `{_PACK_README}` — this file.")
    lines.append("")
    lines.append(f"Work brief: {'included' if has_brief else 'none'}.")
    lines.append("")
    lines.append(
        "Advisory only — local agent starting context; not a correctness, safety, approval, "
        "merge, or production-readiness signal."
    )
    return "\n".join(lines) + "\n"


def render_prompt_header(primer: BranchPrimer) -> str:
    """Render a compact, pasteable agent prompt header. Text only; advisory."""
    s = primer.summary
    lines: list[str] = []
    lines.append("# Chimera Agent Kickoff Header")
    lines.append("")
    lines.append("Read this before starting work.")
    lines.append("")
    lines.append(f"Local advisory context only; {primer.advisory}.")
    lines.append("")
    if primer.work_brief is not None:
        wb = primer.work_brief
        lines.append("Task brief:")
        lines.append(f"- title: {wb.get('title', '')}")
        lines.append(f"- objective: {wb.get('objective', '')}")
        scope = ", ".join(wb.get("scope_paths", []) or []) or "(none)"
        lines.append(f"- scope: {scope}")
        lines.append(f"- checks to report: {len(wb.get('checks', []) or [])}")
        lines.append(f"- done criteria: {len(wb.get('done_criteria', []) or [])}")
        lines.append("")
    lines.append("Current work state:")
    lines.append(f"- claims shown: {s.shown_claim_count}")
    lines.append(f"- unresolved items: {s.open_or_unresolved_count}")
    lines.append(f"- next inspection targets: {s.next_inspection_target_count}")
    lines.append(f"- tool lessons: {s.tool_note_count}")
    lines.append(f"- candidate lessons: {s.candidate_count}")
    lines.append("")
    lines.append("Thread context:")
    if s.thread_snapshot_count == 0:
        lines.append("- review thread: (none)")
    else:
        td = primer.thread_delta
        if td is not None:
            diff = td.get("diff", {}).get("summary_delta", {})
            source = (
                f"since {td.get('old_snapshot_id', '')}"
                if td.get("mode") == "since"
                else "latest-two"
            )
            lines.append(f"- latest snapshot: {td.get('new_snapshot_id', '')}")
            lines.append(f"- delta source: {source}")
            lines.append(f"- unresolved delta: {_delta(diff.get('open_or_unresolved_count', 0))}")
            lines.append(f"- tool lesson delta: {_delta(diff.get('tool_note_count', 0))}")
        else:
            lines.append(f"- snapshots: {s.thread_snapshot_count}")
            lines.append("- delta source: none (need >=2 snapshots or --since)")
    lines.append("")
    lines.append("First inspection targets:")
    if primer.next_inspection_targets:
        for i, t in enumerate(primer.next_inspection_targets[:3], start=1):
            lines.append(f"{i}. {t.claim_id} — {t.reason}")
    else:
        lines.append("1. (none)")
    lines.append("")
    lines.append("Relevant tool lessons:")
    if primer.tool_notes:
        for n in primer.tool_notes:
            label = f"[{n.task_kind}] {n.tool_name} / {n.workflow_name}"
            lines.append(f"- {label}: {n.lesson}" if n.lesson else f"- {label}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("Candidate lessons to review:")
    if primer.candidate_tool_lessons:
        for c in primer.candidate_tool_lessons:
            lines.append(f"- [{c.task_kind}] {c.tool_name} / {c.workflow_name}: {c.lesson}")
    else:
        lines.append("- (none)")
    return "\n".join(lines)


class PackError(Exception):
    """Raised for kickoff-pack write precondition failures (clean CLI errors)."""


def _hashed_entry(name: str, data: bytes) -> dict[str, Any]:
    return {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def write_kickoff_pack(
    primer: BranchPrimer,
    *,
    output_dir: Path,
    store_label: str,
    force: bool = False,
    brief_files: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Write a portable Agent Kickoff Pack and return the manifest dict.

    Writes only into ``output_dir``; never touches the memory store. The parent of
    ``output_dir`` must already exist; an existing non-empty directory is refused
    unless ``force`` (then the bundle files are overwritten). When ``brief_files``
    is supplied (``{WORK_BRIEF.md: ..., work-brief.json: ...}``) those two files are
    added to the pack and the manifest.
    """
    if output_dir.exists() and output_dir.is_file():
        raise PackError(f"output path is a file, not a directory: {output_dir}")
    if not output_dir.parent.exists():
        raise PackError(f"parent directory does not exist: {output_dir.parent}")
    if output_dir.exists():
        existing = [p.name for p in output_dir.iterdir()]
        if existing and not force:
            raise PackError(
                f"output directory is not empty: {output_dir} (use --force to overwrite)"
            )
    else:
        output_dir.mkdir()

    has_brief = bool(brief_files)
    rendered = {
        _PACK_PRIMER_MD: render_branch_primer_markdown(primer, store_label=store_label) + "\n",
        _PACK_PRIMER_JSON: json.dumps(primer.to_dict(), sort_keys=True, indent=2) + "\n",
        _PACK_PROMPT_HEADER: render_prompt_header(primer) + "\n",
    }
    content_order = [_PACK_PRIMER_MD, _PACK_PRIMER_JSON, _PACK_PROMPT_HEADER]
    if brief_files is not None:
        rendered[_PACK_BRIEF_MD] = brief_files[_PACK_BRIEF_MD]
        rendered[_PACK_BRIEF_JSON] = brief_files[_PACK_BRIEF_JSON]
        content_order += [_PACK_BRIEF_MD, _PACK_BRIEF_JSON]
    rendered[_PACK_README] = _pack_readme(has_brief)
    content_order.append(_PACK_README)

    file_entries: list[dict[str, Any]] = []
    for name in content_order:
        data = rendered[name].encode("utf-8")
        (output_dir / name).write_bytes(data)
        file_entries.append(_hashed_entry(name, data))

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "artifact": KICKOFF_ARTIFACT,
        "generated_at": primer.generated_at,
        "advisory": KICKOFF_ADVISORY,
        "filters": primer.filters.to_dict(),
        "primer_summary": primer.summary.to_dict(),
        "files": file_entries,
    }
    (output_dir / _PACK_MANIFEST).write_bytes(
        (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")
    )
    return manifest
