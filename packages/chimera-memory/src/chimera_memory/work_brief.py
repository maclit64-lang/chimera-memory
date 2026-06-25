"""Chimera Agent Work Brief v0 — a local task brief / kickoff contract.

A Work Brief captures the *requested task* before an agent starts work: its
objective, scope, out-of-scope paths, constraints, checks to report, done
criteria, and links to starting context. It is an **input contract**, not an
output verdict.

Stored append-only in ``.chimera-memory/work_briefs.jsonl``. Adding a brief is an
explicit write; reads never create or mutate a store. It is advisory and local:
never a correctness, safety, approval, merge, or production-readiness signal, and
not a form of verification or automation.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from chimera_memory.storage import MemoryStore

SCHEMA_VERSION = 1
STORE_FILE = "work_briefs.jsonl"

WORK_BRIEF_ADVISORY = (
    "local task context; not a correctness, safety, approval, merge, "
    "production-readiness, or speed guarantee"
)


def _strs(value: Any) -> tuple[str, ...]:
    return tuple(str(v) for v in value if isinstance(v, str)) if isinstance(value, list) else ()


@dataclass(frozen=True)
class WorkBrief:
    schema_version: int
    brief_id: str
    created_at: str
    title: str
    objective: str
    task_kind: str | None
    scope_paths: tuple[str, ...]
    out_of_scope_paths: tuple[str, ...]
    constraints: tuple[str, ...]
    checks: tuple[str, ...]
    done_criteria: tuple[str, ...]
    context_refs: tuple[str, ...]
    tags: tuple[str, ...]
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "brief_id": self.brief_id,
            "created_at": self.created_at,
            "title": self.title,
            "objective": self.objective,
            "task_kind": self.task_kind,
            "scope_paths": list(self.scope_paths),
            "out_of_scope_paths": list(self.out_of_scope_paths),
            "constraints": list(self.constraints),
            "checks": list(self.checks),
            "done_criteria": list(self.done_criteria),
            "context_refs": list(self.context_refs),
            "tags": list(self.tags),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WorkBrief:
        task_kind = d.get("task_kind")
        return cls(
            schema_version=int(d.get("schema_version", SCHEMA_VERSION)),
            brief_id=str(d.get("brief_id", "")),
            created_at=str(d.get("created_at", "")),
            title=str(d.get("title", "")),
            objective=str(d.get("objective", "")),
            task_kind=str(task_kind) if isinstance(task_kind, str) else None,
            scope_paths=_strs(d.get("scope_paths")),
            out_of_scope_paths=_strs(d.get("out_of_scope_paths")),
            constraints=_strs(d.get("constraints")),
            checks=_strs(d.get("checks")),
            done_criteria=_strs(d.get("done_criteria")),
            context_refs=_strs(d.get("context_refs")),
            tags=_strs(d.get("tags")),
            source=str(d.get("source", "manual")),
        )


def make_brief_id(*, created_at: str, title: str, objective: str) -> str:
    key = "\x1f".join([created_at, title, objective])
    return "brief_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def build_work_brief(
    *,
    title: str,
    objective: str,
    task_kind: str | None = None,
    scope_paths: tuple[str, ...] = (),
    out_of_scope_paths: tuple[str, ...] = (),
    constraints: tuple[str, ...] = (),
    checks: tuple[str, ...] = (),
    done_criteria: tuple[str, ...] = (),
    context_refs: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    source: str = "manual",
    created_at: str | None = None,
) -> WorkBrief:
    """Build a WorkBrief. ``title`` and ``objective`` are required (non-empty)."""
    if not title:
        raise ValueError("work brief requires a non-empty title")
    if not objective:
        raise ValueError("work brief requires a non-empty objective")
    ts = created_at if created_at is not None else datetime.now(UTC).isoformat()
    return WorkBrief(
        schema_version=SCHEMA_VERSION,
        brief_id=make_brief_id(created_at=ts, title=title, objective=objective),
        created_at=ts,
        title=title,
        objective=objective,
        task_kind=task_kind,
        scope_paths=tuple(scope_paths),
        out_of_scope_paths=tuple(out_of_scope_paths),
        constraints=tuple(constraints),
        checks=tuple(checks),
        done_criteria=tuple(done_criteria),
        context_refs=tuple(context_refs),
        tags=tuple(tags),
        source=source,
    )


def add_work_brief(store: MemoryStore, brief: WorkBrief) -> None:
    """Append one work brief to ``work_briefs.jsonl``. Explicit write only.

    Creates the store directory if needed and appends; does NOT initialize the
    claim/outcome/score ledgers.
    """
    store.ensure()
    store.append_jsonl(STORE_FILE, brief.to_dict())


def read_work_briefs(store: MemoryStore) -> list[WorkBrief]:
    """Read all work briefs (stored order). Read-only; never creates a store."""
    return [WorkBrief.from_dict(d) for d in store.read_jsonl(STORE_FILE)]


def filter_work_briefs(
    briefs: list[WorkBrief],
    *,
    task_kind: str | None = None,
    tag: str | None = None,
) -> list[WorkBrief]:
    """Exact-match filter (AND). No fuzzy matching, no ranking."""
    return [
        b
        for b in briefs
        if (task_kind is None or b.task_kind == task_kind)
        and (tag is None or tag in b.tags)
    ]


def find_work_brief(store: MemoryStore, brief_id: str) -> WorkBrief | None:
    """Return the work brief with this exact id, or None. Read-only."""
    for brief in read_work_briefs(store):
        if brief.brief_id == brief_id:
            return brief
    return None


def compact_work_brief(brief: WorkBrief) -> dict[str, Any]:
    """A compact brief object for embedding in a primer / kickoff pack."""
    return brief.to_dict()


def _render_brief_lines(d: dict[str, Any]) -> list[str]:
    def _section(title: str, items: list[str]) -> list[str]:
        out = [f"## {title}", ""]
        if items:
            out.extend(f"- {item}" for item in items)
        else:
            out.append("- (none)")
        out.append("")
        return out

    lines: list[str] = []
    lines.append("# Chimera Agent Work Brief")
    lines.append("")
    lines.append(f"Advisory task brief only. Local task context; {WORK_BRIEF_ADVISORY}.")
    lines.append("")
    lines.append(f"- title: {d.get('title', '')}")
    lines.append(f"- task_kind: {d.get('task_kind') or '(none)'}")
    lines.append("")
    lines.append("## Objective")
    lines.append("")
    lines.append(d.get("objective", ""))
    lines.append("")
    lines.extend(_section("Scope", list(d.get("scope_paths", []))))
    lines.extend(_section("Out of scope", list(d.get("out_of_scope_paths", []))))
    lines.extend(_section("Constraints", list(d.get("constraints", []))))
    lines.extend(_section("Checks to report", list(d.get("checks", []))))
    lines.extend(_section("Done criteria", list(d.get("done_criteria", []))))
    lines.extend(_section("Context refs", list(d.get("context_refs", []))))
    lines.extend(_section("Tags", list(d.get("tags", []))))
    return lines


def render_work_brief_markdown_from_dict(d: dict[str, Any]) -> str:
    """Render a work brief (as a dict) to advisory markdown. Presentation only."""
    return "\n".join(_render_brief_lines(d)).rstrip() + "\n"


def render_work_brief_markdown(brief: WorkBrief) -> str:
    """Render a work brief to advisory markdown. Presentation only."""
    return render_work_brief_markdown_from_dict(brief.to_dict())
