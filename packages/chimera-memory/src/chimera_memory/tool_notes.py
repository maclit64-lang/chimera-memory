"""Manual Tool Notes (Stage 3): local, advisory agent-skill memory.

Where the rest of the stack records *what happened* (EvidenceEvent), *what was
claimed/settled* (SettledClaim), and *what the next agent should know*
(handoff), a ToolNote records *how the next agent should work* — a reusable
operational lesson about a tool or workflow, captured manually.

This is manual, local, advisory memory only. A ToolNote is never a claim that a
workflow is correct, safe, approved, merge-ready, production-ready, or optimal,
and it is not a form of proof. Storage is a separate append-only
``tool_notes.jsonl`` file; the claims/outcomes/scores/sessions/evidence ledger
is never touched.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chimera_memory.storage import MemoryStore

SCHEMA_VERSION = 1
STORE_FILE = "tool_notes.jsonl"


@dataclass(frozen=True)
class ToolNote:
    schema_version: int
    note_id: str
    created_at: str
    task_kind: str | None
    tool_name: str | None
    workflow_name: str | None
    lesson: str | None
    evidence: str | None
    caveat: str | None
    source: str
    tags: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "note_id": self.note_id,
            "created_at": self.created_at,
            "task_kind": self.task_kind,
            "tool_name": self.tool_name,
            "workflow_name": self.workflow_name,
            "lesson": self.lesson,
            "evidence": self.evidence,
            "caveat": self.caveat,
            "source": self.source,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ToolNote:
        raw_tags = d.get("tags")
        tags = (
            tuple(str(t) for t in raw_tags if isinstance(t, str))
            if isinstance(raw_tags, list)
            else ()
        )
        return cls(
            schema_version=int(d.get("schema_version", SCHEMA_VERSION)),
            note_id=str(d.get("note_id", "")),
            created_at=str(d.get("created_at", "")),
            task_kind=_opt_str(d.get("task_kind")),
            tool_name=_opt_str(d.get("tool_name")),
            workflow_name=_opt_str(d.get("workflow_name")),
            lesson=_opt_str(d.get("lesson")),
            evidence=_opt_str(d.get("evidence")),
            caveat=_opt_str(d.get("caveat")),
            source=str(d.get("source", "manual")),
            tags=tags,
        )


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def make_note_id(
    *,
    created_at: str,
    task_kind: str | None,
    tool_name: str | None,
    workflow_name: str | None,
    lesson: str | None,
) -> str:
    """Deterministic, content-addressed id (stable for the same inputs)."""
    key = "\x1f".join(
        [created_at, task_kind or "", tool_name or "", workflow_name or "", lesson or ""]
    )
    return "tn_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def build_tool_note(
    *,
    task_kind: str | None = None,
    tool_name: str | None = None,
    workflow_name: str | None = None,
    lesson: str | None = None,
    evidence: str | None = None,
    caveat: str | None = None,
    source: str = "manual",
    tags: tuple[str, ...] = (),
    created_at: str | None = None,
) -> ToolNote:
    ts = created_at or datetime.now(UTC).isoformat()
    return ToolNote(
        schema_version=SCHEMA_VERSION,
        note_id=make_note_id(
            created_at=ts,
            task_kind=task_kind,
            tool_name=tool_name,
            workflow_name=workflow_name,
            lesson=lesson,
        ),
        created_at=ts,
        task_kind=task_kind,
        tool_name=tool_name,
        workflow_name=workflow_name,
        lesson=lesson,
        evidence=evidence,
        caveat=caveat,
        source=source,
        tags=tags,
    )


def add_tool_note(store: MemoryStore, note: ToolNote) -> None:
    """Append one ToolNote to the local append-only ``tool_notes.jsonl``.

    Writes only the tool-notes file; the claims/outcomes/scores/sessions ledger
    is never touched.
    """
    store.ensure()
    store.append_jsonl(STORE_FILE, note.to_dict())


def read_tool_notes(store: MemoryStore) -> list[ToolNote]:
    """Return all tool notes in insertion order. Read-only."""
    return [ToolNote.from_dict(d) for d in store.read_jsonl(STORE_FILE)]


def tool_notes_for_root(root: str | Path) -> list[ToolNote]:
    return read_tool_notes(MemoryStore.from_paths(root=root))


def filter_tool_notes(
    notes: list[ToolNote],
    *,
    task_kind: str | None = None,
    tool_name: str | None = None,
    workflow_name: str | None = None,
    tag: str | None = None,
) -> list[ToolNote]:
    """Exact-match filter over tool notes; criteria combine with AND.

    No fuzzy matching, no semantic search, no ranking. ``tag`` matches when it is
    present in a note's ``tags``. A ``None`` criterion is not applied.
    """
    return [
        n
        for n in notes
        if (task_kind is None or n.task_kind == task_kind)
        and (tool_name is None or n.tool_name == tool_name)
        and (workflow_name is None or n.workflow_name == workflow_name)
        and (tag is None or tag in n.tags)
    ]


def render_tool_notes_text(notes: list[ToolNote]) -> str:
    """Render a terse text listing for the CLI. Advisory only."""
    if not notes:
        return "No tool notes recorded (local, advisory)."
    lines: list[str] = []
    for n in notes:
        head = f"[{n.task_kind}] {n.tool_name} / {n.workflow_name}  ({n.note_id})"
        lines.append(head)
        if n.lesson:
            lines.append(f"  lesson: {n.lesson}")
        if n.evidence:
            lines.append(f"  evidence: {n.evidence}")
        if n.caveat:
            lines.append(f"  caveat: {n.caveat}")
        if n.tags:
            lines.append(f"  tags: {', '.join(n.tags)}")
    return "\n".join(lines)
