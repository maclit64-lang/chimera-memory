"""Tool Activity + Candidate Lesson capture (local, advisory, review-before-save).

A ``ToolActivity`` is an append-only local record that a tool/workflow ran (what
happened operationally). A ``CandidateLesson`` is a **read-only projection** over
activities: a proposed Tool Note that a human or agent reviews before saving via
the existing ``tool-notes add`` path.

Boundaries (intentional):
- Candidates are never saved automatically. Projection writes nothing.
- No inference, ranking, fuzzy/semantic matching, or model calls. The candidate
  lesson is the activity's ``summary`` verbatim — a starting point to review and
  rewrite, not a finished or judged lesson.
- A candidate makes no correctness, safety, approval, merge, production-readiness,
  or speed claim. It is a candidate local operational lesson to review before saving.

Storage is a separate append-only ``tool_activity.jsonl``; the
claims/outcomes/scores/sessions ledger and ``tool_notes.jsonl`` are never touched.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chimera_memory.storage import MemoryStore

SCHEMA_VERSION = 1
STORE_FILE = "tool_activity.jsonl"
CANDIDATE_ADVISORY = "candidate local operational lessons only; review before saving"


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _opt_float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _str_tuple(value: Any) -> tuple[str, ...]:
    return tuple(str(v) for v in value if isinstance(v, str)) if isinstance(value, list) else ()


@dataclass(frozen=True)
class ToolActivity:
    schema_version: int
    activity_id: str
    created_at: str
    task_kind: str | None
    tool_name: str | None
    workflow_name: str | None
    phase: str | None
    summary: str | None
    evidence: str | None
    caveat: str | None
    status: str | None
    duration_seconds: float | None
    cost_units: float | None
    artifact_refs: tuple[str, ...]
    tags: tuple[str, ...]
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "activity_id": self.activity_id,
            "created_at": self.created_at,
            "task_kind": self.task_kind,
            "tool_name": self.tool_name,
            "workflow_name": self.workflow_name,
            "phase": self.phase,
            "summary": self.summary,
            "evidence": self.evidence,
            "caveat": self.caveat,
            "status": self.status,
            "duration_seconds": self.duration_seconds,
            "cost_units": self.cost_units,
            "artifact_refs": list(self.artifact_refs),
            "tags": list(self.tags),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ToolActivity:
        return cls(
            schema_version=int(d.get("schema_version", SCHEMA_VERSION)),
            activity_id=str(d.get("activity_id", "")),
            created_at=str(d.get("created_at", "")),
            task_kind=_opt_str(d.get("task_kind")),
            tool_name=_opt_str(d.get("tool_name")),
            workflow_name=_opt_str(d.get("workflow_name")),
            phase=_opt_str(d.get("phase")),
            summary=_opt_str(d.get("summary")),
            evidence=_opt_str(d.get("evidence")),
            caveat=_opt_str(d.get("caveat")),
            status=_opt_str(d.get("status")),
            duration_seconds=_opt_float(d.get("duration_seconds")),
            cost_units=_opt_float(d.get("cost_units")),
            artifact_refs=_str_tuple(d.get("artifact_refs")),
            tags=_str_tuple(d.get("tags")),
            source=str(d.get("source", "manual")),
        )


def make_activity_id(
    *,
    created_at: str,
    task_kind: str | None,
    tool_name: str | None,
    workflow_name: str | None,
    summary: str | None,
) -> str:
    key = "\x1f".join(
        [created_at, task_kind or "", tool_name or "", workflow_name or "", summary or ""]
    )
    return "act_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def build_tool_activity(
    *,
    task_kind: str | None = None,
    tool_name: str | None = None,
    workflow_name: str | None = None,
    phase: str | None = None,
    summary: str | None = None,
    evidence: str | None = None,
    caveat: str | None = None,
    status: str | None = None,
    duration_seconds: float | None = None,
    cost_units: float | None = None,
    artifact_refs: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    source: str = "manual",
    created_at: str | None = None,
) -> ToolActivity:
    ts = created_at or datetime.now(UTC).isoformat()
    return ToolActivity(
        schema_version=SCHEMA_VERSION,
        activity_id=make_activity_id(
            created_at=ts,
            task_kind=task_kind,
            tool_name=tool_name,
            workflow_name=workflow_name,
            summary=summary,
        ),
        created_at=ts,
        task_kind=task_kind,
        tool_name=tool_name,
        workflow_name=workflow_name,
        phase=phase,
        summary=summary,
        evidence=evidence,
        caveat=caveat,
        status=status,
        duration_seconds=duration_seconds,
        cost_units=cost_units,
        artifact_refs=artifact_refs,
        tags=tags,
        source=source,
    )


def add_tool_activity(store: MemoryStore, activity: ToolActivity) -> None:
    """Append one ToolActivity to the local append-only ``tool_activity.jsonl``.

    Writes only the tool-activity file; the claims/outcomes/scores/sessions ledger
    and tool_notes.jsonl are never touched.
    """
    store.ensure()
    store.append_jsonl(STORE_FILE, activity.to_dict())


def read_tool_activities(store: MemoryStore) -> list[ToolActivity]:
    """Return all tool activities in insertion order. Read-only."""
    return [ToolActivity.from_dict(d) for d in store.read_jsonl(STORE_FILE)]


def tool_activities_for_root(root: str | Path) -> list[ToolActivity]:
    return read_tool_activities(MemoryStore.from_paths(root=root))


def filter_tool_activities(
    activities: list[ToolActivity],
    *,
    task_kind: str | None = None,
    tool_name: str | None = None,
    workflow_name: str | None = None,
    tag: str | None = None,
) -> list[ToolActivity]:
    """Exact-match filter (AND across provided criteria). No fuzzy matching."""
    return [
        a
        for a in activities
        if (task_kind is None or a.task_kind == task_kind)
        and (tool_name is None or a.tool_name == tool_name)
        and (workflow_name is None or a.workflow_name == workflow_name)
        and (tag is None or tag in a.tags)
    ]


def render_tool_activities_text(activities: list[ToolActivity]) -> str:
    if not activities:
        return "No tool activity recorded (local)."
    lines: list[str] = []
    for a in activities:
        lines.append(f"[{a.task_kind}] {a.tool_name} / {a.workflow_name}  ({a.activity_id})")
        if a.phase:
            lines.append(f"  phase: {a.phase}")
        if a.summary:
            lines.append(f"  summary: {a.summary}")
        if a.status:
            lines.append(f"  status: {a.status}")
        if a.tags:
            lines.append(f"  tags: {', '.join(a.tags)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Candidate Lesson projection (read-only; review before saving)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateLesson:
    schema_version: int
    candidate_id: str
    task_kind: str | None
    tool_name: str | None
    workflow_name: str | None
    lesson: str | None
    evidence: str | None
    caveat: str | None
    source_activity_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "task_kind": self.task_kind,
            "tool_name": self.tool_name,
            "workflow_name": self.workflow_name,
            "lesson": self.lesson,
            "evidence": self.evidence,
            "caveat": self.caveat,
            "source_activity_ids": list(self.source_activity_ids),
        }


def make_candidate_id(*, activity_id: str, lesson: str) -> str:
    return "cand_" + hashlib.sha256(f"{activity_id}\x1f{lesson}".encode()).hexdigest()[:16]


def project_candidates(activities: list[ToolActivity]) -> list[CandidateLesson]:
    """Project one candidate lesson per activity that has the required fields.

    Deterministic and read-only. The candidate ``lesson`` is the activity's
    ``summary`` verbatim — a starting point to review and rewrite, never inferred
    or paraphrased. Activities missing task_kind / tool_name / summary are skipped.
    """
    candidates: list[CandidateLesson] = []
    for a in activities:
        if not (a.task_kind and a.tool_name and a.summary):
            continue
        lesson = a.summary
        candidates.append(
            CandidateLesson(
                schema_version=SCHEMA_VERSION,
                candidate_id=make_candidate_id(activity_id=a.activity_id, lesson=lesson),
                task_kind=a.task_kind,
                tool_name=a.tool_name,
                workflow_name=a.workflow_name,
                lesson=lesson,
                evidence=a.evidence,
                caveat=a.caveat,
                source_activity_ids=(a.activity_id,),
            )
        )
    return candidates


def candidates_for_root(
    root: str | Path,
    *,
    task_kind: str | None = None,
) -> list[CandidateLesson]:
    activities = read_tool_activities(MemoryStore.from_paths(root=root))
    if task_kind is not None:
        activities = filter_tool_activities(activities, task_kind=task_kind)
    return project_candidates(activities)


def select_candidates(
    store: MemoryStore,
    *,
    task_kind: str | None = None,
    tool_name: str | None = None,
    workflow_name: str | None = None,
    tag: str | None = None,
    limit: int | None = None,
) -> list[CandidateLesson]:
    """Read-only: exact-filter activities, project candidates, then apply limit.

    Filters combine with AND; limit applies after filtering; stored order, no
    ranking. ``limit`` is clamped to >= 0 (0 -> empty).
    """
    activities = filter_tool_activities(
        read_tool_activities(store),
        task_kind=task_kind,
        tool_name=tool_name,
        workflow_name=workflow_name,
        tag=tag,
    )
    candidates = project_candidates(activities)
    if limit is not None:
        candidates = candidates[: max(limit, 0)]
    return candidates


def find_candidate(store: MemoryStore, candidate_id: str) -> CandidateLesson | None:
    """Read-only: return the projected candidate with this exact id, or None."""
    for candidate in project_candidates(read_tool_activities(store)):
        if candidate.candidate_id == candidate_id:
            return candidate
    return None


def render_candidates_text(candidates: list[CandidateLesson]) -> str:
    if not candidates:
        return "No candidate tool lessons (advisory; review before saving)."
    lines: list[str] = [f"Candidate tool lessons ({CANDIDATE_ADVISORY}):"]
    for c in candidates:
        lines.append(f"- [{c.task_kind}] {c.tool_name} / {c.workflow_name}  ({c.candidate_id})")
        if c.lesson:
            lines.append(f"  Candidate lesson: {c.lesson}")
        if c.evidence:
            lines.append(f"  Evidence: {c.evidence}")
        if c.caveat:
            lines.append(f"  Caveat: {c.caveat}")
    return "\n".join(lines)
