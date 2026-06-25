"""Chimera Work Packet v0 — one portable, local, advisory review artifact.

A Work Packet composes existing read-only projections into a single packet a
human or the next agent can review:

    handoff builder (claims / open / inspection targets / tool notes / counts)
    + candidate lesson selector (candidates available to review)

It answers: what happened here, what claims exist, which settled / contradicted
/ remain unresolved, what to inspect next, what local tool lessons apply, and
what candidate lessons are available to review.

It is **advisory and local-only** — a local evidence and operational memory
summary, never a correctness, safety, approval, merge, or production-readiness
signal, and not a form of verification. It is strictly read-only and reuses the
existing projection layers (no duplicated business logic).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from chimera_memory.handoff import (
    HandoffClaim,
    HandoffOpenItem,
    HandoffTarget,
    build_handoff,
)
from chimera_memory.storage import MemoryStore
from chimera_memory.tool_activity import CandidateLesson, select_candidates
from chimera_memory.tool_notes import ToolNote

SCHEMA_VERSION = 1
ARTIFACT = "chimera_work_packet"

ADVISORY = (
    "local evidence and operational memory summary only; not a correctness, "
    "safety, approval, merge, production-readiness, or speed guarantee"
)

# Run `preflight` for recommended checks; we point at it rather than embedding
# its output (preflight legitimately discusses statistical "proof", which this
# artifact deliberately avoids claiming).
PREFLIGHT_POINTER = (
    "Run `chimera-memory preflight` (optionally with --task-kind / --tag) for "
    "recommended local checks before changes. Advisory only."
)


@dataclass(frozen=True)
class WorkPacketFilters:
    """The read-only filters applied to this packet (echoed for transparency).

    ``claim_id`` / ``session_id`` / ``status`` narrow the claim view;
    ``task_kind`` / ``tag`` narrow tool notes and candidate lessons; the limits
    apply after filtering.
    """

    claim_id: str | None = None
    session_id: str | None = None
    status: str | None = None
    task_kind: str | None = None
    tag: str | None = None
    limit_tool_notes: int | None = None
    limit_candidates: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "session_id": self.session_id,
            "status": self.status,
            "task_kind": self.task_kind,
            "tag": self.tag,
            "limit_tool_notes": self.limit_tool_notes,
            "limit_candidates": self.limit_candidates,
        }


@dataclass(frozen=True)
class WorkPacketSummary:
    event_count: int
    settled_claim_count: int
    shown_claim_count: int
    open_or_unresolved_count: int
    next_inspection_target_count: int
    tool_note_count: int
    candidate_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_count": self.event_count,
            "settled_claim_count": self.settled_claim_count,
            "shown_claim_count": self.shown_claim_count,
            "open_or_unresolved_count": self.open_or_unresolved_count,
            "next_inspection_target_count": self.next_inspection_target_count,
            "tool_note_count": self.tool_note_count,
            "candidate_count": self.candidate_count,
        }


@dataclass(frozen=True)
class WorkPacket:
    schema_version: int
    artifact: str
    advisory: str
    generated_at: str
    filters: WorkPacketFilters
    summary: WorkPacketSummary
    claims: tuple[HandoffClaim, ...]
    open_or_unresolved: tuple[HandoffOpenItem, ...]
    next_inspection_targets: tuple[HandoffTarget, ...]
    tool_notes: tuple[ToolNote, ...]
    candidate_tool_lessons: tuple[CandidateLesson, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact": self.artifact,
            "advisory": self.advisory,
            "generated_at": self.generated_at,
            "filters": self.filters.to_dict(),
            "summary": self.summary.to_dict(),
            "claims": [c.to_dict() for c in self.claims],
            "open_or_unresolved": [o.to_dict() for o in self.open_or_unresolved],
            "next_inspection_targets": [t.to_dict() for t in self.next_inspection_targets],
            "tool_notes": [n.to_dict() for n in self.tool_notes],
            "candidate_tool_lessons": [c.to_dict() for c in self.candidate_tool_lessons],
        }


def build_work_packet(
    store: MemoryStore,
    *,
    generated_at: str,
    claim_id: str | None = None,
    session_id: str | None = None,
    status: str | None = None,
    task_kind: str | None = None,
    tag: str | None = None,
    limit_tool_notes: int | None = None,
    limit_candidates: int | None = None,
) -> WorkPacket:
    """Compose a WorkPacket from the local ledger. Read-only; writes nothing.

    Reuses ``build_handoff`` for the claim/evidence/tool-note view and
    ``select_candidates`` for candidate lessons. Exact-match filters combine
    with AND; limits apply after filtering; stored order; no ranking.
    """
    handoff = build_handoff(
        store,
        session_id=session_id,
        claim_id=claim_id,
        status=status,
        task_kind=task_kind,
        tag=tag,
        tool_note_limit=limit_tool_notes,
    )
    candidates = select_candidates(store, task_kind=task_kind, tag=tag, limit=limit_candidates)

    summary = WorkPacketSummary(
        event_count=handoff.event_count,
        settled_claim_count=handoff.settled_claim_count,
        shown_claim_count=len(handoff.claims),
        open_or_unresolved_count=len(handoff.open_or_unresolved),
        next_inspection_target_count=len(handoff.next_inspection_targets),
        tool_note_count=len(handoff.tool_notes),
        candidate_count=len(candidates),
    )
    return WorkPacket(
        schema_version=SCHEMA_VERSION,
        artifact=ARTIFACT,
        advisory=ADVISORY,
        generated_at=generated_at,
        filters=WorkPacketFilters(
            claim_id=claim_id,
            session_id=session_id,
            status=status,
            task_kind=task_kind,
            tag=tag,
            limit_tool_notes=limit_tool_notes,
            limit_candidates=limit_candidates,
        ),
        summary=summary,
        claims=handoff.claims,
        open_or_unresolved=handoff.open_or_unresolved,
        next_inspection_targets=handoff.next_inspection_targets,
        tool_notes=handoff.tool_notes,
        candidate_tool_lessons=tuple(candidates),
    )


def _filter_label(filters: WorkPacketFilters) -> str:
    active = {k: v for k, v in filters.to_dict().items() if v is not None}
    return " ".join(f"{k}={v}" for k, v in active.items()) if active else "none"


def render_work_packet_markdown(packet: WorkPacket, *, store_label: str) -> str:
    """Render the packet as advisory markdown. Presentation only."""
    s = packet.summary
    validated = sum(1 for c in packet.claims if c.latest_status == "validated")
    contradicted = sum(1 for c in packet.claims if c.latest_status == "contradicted")

    lines: list[str] = []
    lines.append("# Chimera Work Packet")
    lines.append("")
    lines.append(f"Advisory only. {packet.advisory}.")
    lines.append("")
    lines.append("## Store")
    lines.append(f"- root: {store_label}")
    lines.append(f"- generated_at: {packet.generated_at}")
    lines.append(f"- filters: {_filter_label(packet.filters)}")
    lines.append("")
    lines.append("## Claims")
    lines.append(f"- total: {s.settled_claim_count}")
    lines.append(f"- shown: {s.shown_claim_count}")
    lines.append(f"- validated: {validated}")
    lines.append(f"- contradicted: {contradicted}")
    lines.append(f"- unresolved: {s.open_or_unresolved_count}")
    if packet.claims:
        for c in packet.claims:
            lines.append(
                f"- `{c.claim_id}` — status={c.latest_status} events={c.event_count} "
                f"latest_exit_code={c.latest_exit_code}"
            )
    lines.append("")
    lines.append("## Open / unresolved evidence")
    if packet.open_or_unresolved:
        for o in packet.open_or_unresolved:
            lines.append(f"- `{o.claim_id}` — {', '.join(o.reasons)}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Next inspection targets")
    if packet.next_inspection_targets:
        for t in packet.next_inspection_targets:
            lines.append(f"- `{t.claim_id}` — {t.reason}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Tool lessons")
    if packet.tool_notes:
        for n in packet.tool_notes:
            lines.append(f"- [{n.task_kind}] {n.tool_name} / {n.workflow_name}")
            if n.lesson:
                lines.append(f"  {n.lesson}")
            if n.evidence:
                lines.append(f"  Evidence: {n.evidence}")
            if n.caveat:
                lines.append(f"  Caveat: {n.caveat}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Candidate tool lessons")
    lines.append("")
    lines.append("Advisory only. Review before saving as Tool Notes.")
    lines.append("")
    if packet.candidate_tool_lessons:
        for cand in packet.candidate_tool_lessons:
            lines.append(f"- [{cand.task_kind}] {cand.tool_name} / {cand.workflow_name}")
            lines.append(f"  Candidate lesson: {cand.lesson}")
            if cand.evidence:
                lines.append(f"  Evidence: {cand.evidence}")
            if cand.caveat:
                lines.append(f"  Caveat: {cand.caveat}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Preflight advisory")
    lines.append(f"- {PREFLIGHT_POINTER}")
    return "\n".join(lines)
