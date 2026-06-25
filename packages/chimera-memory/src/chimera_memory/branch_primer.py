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
    latest_thread_delta: dict[str, Any] | None
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
            "latest_thread_delta": self.latest_thread_delta,
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
    limit_tool_notes: int | None = None,
    limit_candidates: int | None = None,
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
    latest_thread_delta: dict[str, Any] | None = None
    if thread_dir is not None:
        index = read_thread_index(thread_dir)
        if index is None:
            raise ThreadError(f"no review thread index at {thread_dir}")
        snapshots = index.get("snapshots", [])
        thread_snapshot_count = len(snapshots)
        if snapshots:
            latest_snapshot = snapshots[-1]
        if thread_snapshot_count >= 2:
            latest_thread_delta = thread_diff_latest(thread_dir)

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
            limit_tool_notes=limit_tool_notes,
            limit_candidates=limit_candidates,
        ),
        summary=summary,
        work_packet=_compact_packet(packet),
        latest_thread_delta=latest_thread_delta,
        next_inspection_targets=packet.next_inspection_targets,
        tool_notes=packet.tool_notes,
        candidate_tool_lessons=packet.candidate_tool_lessons,
        suggested_first_read=tuple(
            _suggested_first_read(
                packet, store_label=store_label, thread_dir=thread_dir,
                latest_snapshot=latest_snapshot,
            )
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
    lines.append("## Current work state")
    lines.append(f"- claims shown: {s.shown_claim_count}")
    lines.append(f"- unresolved: {s.open_or_unresolved_count}")
    lines.append(f"- next inspection targets: {s.next_inspection_target_count}")
    lines.append(f"- tool lessons: {s.tool_note_count}")
    lines.append(f"- candidate lessons: {s.candidate_count}")
    lines.append(f"- thread snapshots: {s.thread_snapshot_count}")
    lines.append("")
    if primer.latest_thread_delta is not None:
        delta = primer.latest_thread_delta.get("summary_delta", {})
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
