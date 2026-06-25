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

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
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


# ── v1: portable bundle + inspect + diff ─────────────────────────────────────

BUNDLE_ARTIFACT = "chimera_work_packet_bundle"
INSPECTION_ARTIFACT = "chimera_work_packet_bundle_inspection"
DIFF_ARTIFACT = "chimera_work_packet_diff"

_BUNDLE_MD = "WORK_PACKET.md"
_BUNDLE_JSON = "work-packet.json"
_BUNDLE_README = "README.md"
_BUNDLE_MANIFEST = "manifest.json"
# Content files hashed into the manifest (manifest.json cannot hash itself).
_BUNDLE_CONTENT_FILES = (_BUNDLE_MD, _BUNDLE_JSON, _BUNDLE_README)

_README_TEXT = (
    "# Chimera Work Packet bundle\n\n"
    "A portable, local, advisory review packet:\n\n"
    f"- `{_BUNDLE_MD}` — the human-readable packet.\n"
    f"- `{_BUNDLE_JSON}` — the machine-readable packet.\n"
    f"- `{_BUNDLE_MANIFEST}` — the bundle manifest (file list + sha256 + byte counts).\n"
    f"- `{_BUNDLE_README}` — this file.\n\n"
    "Inspect it with `chimera-memory work-packet inspect <dir>` and compare two bundles "
    "with `chimera-memory work-packet diff <old> <new>`.\n\n"
    "Advisory only — a local evidence and operational memory summary; not a correctness, "
    "safety, approval, merge, or production-readiness signal.\n"
)


class BundleError(Exception):
    """Raised for bundle-write precondition failures (clean CLI errors)."""


def _hashed_entry(name: str, data: bytes) -> dict[str, Any]:
    return {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def write_work_packet_bundle(
    packet: WorkPacket,
    *,
    output_dir: Path,
    store_label: str,
    force: bool = False,
) -> dict[str, Any]:
    """Write a portable bundle (4 files) and return the manifest dict.

    Writes only into ``output_dir``; never touches the memory store. The parent
    of ``output_dir`` must already exist. An existing non-empty ``output_dir`` is
    refused unless ``force`` is set (then the bundle files are overwritten).
    """
    if output_dir.exists() and output_dir.is_file():
        raise BundleError(f"output path is a file, not a directory: {output_dir}")
    if not output_dir.parent.exists():
        raise BundleError(f"parent directory does not exist: {output_dir.parent}")
    if output_dir.exists():
        existing = [p.name for p in output_dir.iterdir()]
        if existing and not force:
            raise BundleError(
                f"output directory is not empty: {output_dir} (use --force to overwrite)"
            )
    else:
        output_dir.mkdir()

    rendered = {
        _BUNDLE_MD: render_work_packet_markdown(packet, store_label=store_label) + "\n",
        _BUNDLE_JSON: json.dumps(packet.to_dict(), sort_keys=True, indent=2) + "\n",
        _BUNDLE_README: _README_TEXT,
    }
    file_entries: list[dict[str, Any]] = []
    for name in _BUNDLE_CONTENT_FILES:
        data = rendered[name].encode("utf-8")
        (output_dir / name).write_bytes(data)
        file_entries.append(_hashed_entry(name, data))

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "artifact": BUNDLE_ARTIFACT,
        "generated_at": packet.generated_at,
        "advisory": packet.advisory,
        "filters": packet.filters.to_dict(),
        "packet_summary": packet.summary.to_dict(),
        "files": file_entries,
    }
    (output_dir / _BUNDLE_MANIFEST).write_bytes(
        (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")
    )
    return manifest


def inspect_bundle(bundle_dir: Path) -> dict[str, Any]:
    """Read a bundle manifest and verify each listed file. Read-only."""
    errors: list[str] = []
    manifest_path = bundle_dir / _BUNDLE_MANIFEST
    if not manifest_path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "artifact": INSPECTION_ARTIFACT,
            "valid": False,
            "bundle": {"path": str(bundle_dir), "manifest": None},
            "files": [],
            "errors": [f"{_BUNDLE_MANIFEST} not found"],
        }
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "artifact": INSPECTION_ARTIFACT,
            "valid": False,
            "bundle": {"path": str(bundle_dir), "manifest": None},
            "files": [],
            "errors": [f"{_BUNDLE_MANIFEST} is unreadable: {exc}"],
        }

    file_results: list[dict[str, Any]] = []
    for entry in manifest.get("files", []):
        name = entry.get("path", "")
        fp = bundle_dir / name
        exists = fp.exists()
        sha_ok = False
        bytes_ok = False
        if exists:
            data = fp.read_bytes()
            sha_ok = hashlib.sha256(data).hexdigest() == entry.get("sha256")
            bytes_ok = len(data) == entry.get("bytes")
            if not sha_ok:
                errors.append(f"sha256 mismatch: {name}")
            if not bytes_ok:
                errors.append(f"bytes mismatch: {name}")
        else:
            errors.append(f"missing file: {name}")
        file_results.append({
            "path": name,
            "exists": exists,
            "sha256_matches": sha_ok,
            "bytes_matches": bytes_ok,
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "artifact": INSPECTION_ARTIFACT,
        "valid": not errors,
        "bundle": {"path": str(bundle_dir), "manifest": manifest},
        "files": file_results,
        "errors": errors,
    }


def render_inspect_text(result: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Chimera Work Packet bundle inspection")
    lines.append("")
    lines.append("Advisory only. Local bundle integrity check (file hashes/sizes).")
    lines.append("")
    lines.append(f"- bundle: {result['bundle']['path']}")
    lines.append(f"- valid: {result['valid']}")
    for f in result["files"]:
        lines.append(
            f"- {f['path']}: exists={f['exists']} sha256_matches={f['sha256_matches']} "
            f"bytes_matches={f['bytes_matches']}"
        )
    if result["errors"]:
        lines.append("- errors:")
        for e in result["errors"]:
            lines.append(f"  - {e}")
    return "\n".join(lines)


def load_packet_dict(path: Path) -> dict[str, Any]:
    """Load a packet dict from a bundle directory or a work-packet.json file."""
    target = path / _BUNDLE_JSON if path.is_dir() else path
    return json.loads(target.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def diff_packets(
    old: dict[str, Any],
    new: dict[str, Any],
    *,
    old_path: str,
    new_path: str,
) -> dict[str, Any]:
    """Compute a read-only, deterministic diff between two work packets."""
    old_summary = old.get("summary", {})
    new_summary = new.get("summary", {})
    summary_delta = {
        k: int(new_summary.get(k, 0)) - int(old_summary.get(k, 0))
        for k in sorted(set(old_summary) | set(new_summary))
    }

    old_claims = {c["claim_id"]: c.get("latest_status") for c in old.get("claims", [])}
    new_claims = {c["claim_id"]: c.get("latest_status") for c in new.get("claims", [])}
    status_changed = [
        {"claim_id": cid, "old_status": old_claims[cid], "new_status": new_claims[cid]}
        for cid in sorted(set(old_claims) & set(new_claims))
        if old_claims[cid] != new_claims[cid]
    ]

    def _ids(packet: dict[str, Any], key: str, id_field: str) -> set[str]:
        return {item[id_field] for item in packet.get(key, [])}

    old_notes = _ids(old, "tool_notes", "note_id")
    new_notes = _ids(new, "tool_notes", "note_id")
    old_cands = _ids(old, "candidate_tool_lessons", "candidate_id")
    new_cands = _ids(new, "candidate_tool_lessons", "candidate_id")

    return {
        "schema_version": SCHEMA_VERSION,
        "artifact": DIFF_ARTIFACT,
        "old": {"path": old_path, "artifact": old.get("artifact")},
        "new": {"path": new_path, "artifact": new.get("artifact")},
        "summary_delta": summary_delta,
        "claims": {
            "added": sorted(set(new_claims) - set(old_claims)),
            "removed": sorted(set(old_claims) - set(new_claims)),
            "status_changed": status_changed,
        },
        "tool_notes": {
            "added": sorted(new_notes - old_notes),
            "removed": sorted(old_notes - new_notes),
        },
        "candidate_tool_lessons": {
            "added": sorted(new_cands - old_cands),
            "removed": sorted(old_cands - new_cands),
        },
    }


def _delta(value: int) -> str:
    return f"+{value}" if value > 0 else str(value)


def render_diff_markdown(diff: dict[str, Any]) -> str:
    s = diff["summary_delta"]
    lines: list[str] = []
    lines.append("# Chimera Work Packet Diff")
    lines.append("")
    lines.append(
        "Advisory only. Local packet comparison; not a correctness, safety, approval, "
        "merge, or production-readiness signal."
    )
    lines.append("")
    lines.append(f"- old: {diff['old']['path']}")
    lines.append(f"- new: {diff['new']['path']}")
    lines.append("")
    lines.append("Summary deltas:")
    lines.append(f"- claims shown: {_delta(s.get('shown_claim_count', 0))}")
    lines.append(f"- settled claims: {_delta(s.get('settled_claim_count', 0))}")
    lines.append(f"- unresolved: {_delta(s.get('open_or_unresolved_count', 0))}")
    lines.append(f"- next inspection targets: {_delta(s.get('next_inspection_target_count', 0))}")
    lines.append(f"- tool lessons: {_delta(s.get('tool_note_count', 0))}")
    lines.append(f"- candidate lessons: {_delta(s.get('candidate_count', 0))}")
    lines.append("")
    claims = diff["claims"]
    lines.append("Claims:")
    lines.append(f"- added: {', '.join(claims['added']) or '(none)'}")
    lines.append(f"- removed: {', '.join(claims['removed']) or '(none)'}")
    if claims["status_changed"]:
        lines.append("- status changed:")
        for ch in claims["status_changed"]:
            lines.append(f"  - {ch['claim_id']}: {ch['old_status']} -> {ch['new_status']}")
    else:
        lines.append("- status changed: (none)")
    lines.append("")
    lines.append("Tool lessons:")
    lines.append(f"- added: {', '.join(diff['tool_notes']['added']) or '(none)'}")
    lines.append(f"- removed: {', '.join(diff['tool_notes']['removed']) or '(none)'}")
    lines.append("")
    lines.append("Candidate tool lessons:")
    lines.append(f"- added: {', '.join(diff['candidate_tool_lessons']['added']) or '(none)'}")
    lines.append(f"- removed: {', '.join(diff['candidate_tool_lessons']['removed']) or '(none)'}")
    return "\n".join(lines)


# ── v0: review thread (local timeline of bundles) ────────────────────────────

THREAD_ARTIFACT = "chimera_work_packet_thread"
THREAD_INSPECTION_ARTIFACT = "chimera_work_packet_thread_inspection"
THREAD_ADVISORY = (
    "local review thread index only; not a correctness, safety, approval, merge, "
    "production-readiness, or speed guarantee"
)

_THREAD_INDEX = "index.json"
_THREAD_INDEX_MD = "INDEX.md"
_THREAD_PACKETS = "packets"


class ThreadError(Exception):
    """Raised for review-thread precondition failures (clean CLI errors)."""


def _packet_json_bytes(packet: WorkPacket) -> bytes:
    return (json.dumps(packet.to_dict(), sort_keys=True, indent=2) + "\n").encode("utf-8")


def make_snapshot_id(packet: WorkPacket, now: datetime) -> str:
    """Deterministic snapshot id: ``wp_<UTC stamp>_<8-char content hash>``."""
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(_packet_json_bytes(packet)).hexdigest()[:8]
    return f"wp_{stamp}_{digest}"


def read_thread_index(thread_dir: Path) -> dict[str, Any] | None:
    """Read the thread ``index.json`` (or None if absent). Read-only."""
    index_path = thread_dir / _THREAD_INDEX
    if not index_path.exists():
        return None
    return json.loads(index_path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def add_thread_snapshot(
    packet: WorkPacket,
    *,
    thread_dir: Path,
    store_label: str,
    now: datetime,
    label: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Write the packet as a bundle under ``thread_dir/packets/<id>/`` and append the index.

    Writes only under ``thread_dir``; never touches the memory store. The parent
    of ``thread_dir`` must already exist. Refuses to overwrite an existing
    snapshot directory. Returns the updated index dict.
    """
    if not thread_dir.parent.exists():
        raise ThreadError(f"parent directory does not exist: {thread_dir.parent}")
    packets_dir = thread_dir / _THREAD_PACKETS
    packets_dir.mkdir(parents=True, exist_ok=True)

    created_at = now.isoformat()
    snapshot_id = make_snapshot_id(packet, now)
    snapshot_dir = packets_dir / snapshot_id
    if snapshot_dir.exists() and any(snapshot_dir.iterdir()):
        raise ThreadError(f"snapshot already exists: {snapshot_id}")

    write_work_packet_bundle(packet, output_dir=snapshot_dir, store_label=store_label)
    packet_sha256 = hashlib.sha256((snapshot_dir / _BUNDLE_JSON).read_bytes()).hexdigest()
    manifest_sha256 = hashlib.sha256((snapshot_dir / _BUNDLE_MANIFEST).read_bytes()).hexdigest()

    entry = {
        "snapshot_id": snapshot_id,
        "created_at": created_at,
        "path": f"{_THREAD_PACKETS}/{snapshot_id}",
        "label": label,
        "note": note,
        "filters": packet.filters.to_dict(),
        "packet_summary": packet.summary.to_dict(),
        "manifest_sha256": manifest_sha256,
        "packet_sha256": packet_sha256,
    }

    index = read_thread_index(thread_dir)
    if index is None:
        index = {
            "schema_version": SCHEMA_VERSION,
            "artifact": THREAD_ARTIFACT,
            "advisory": THREAD_ADVISORY,
            "created_at": created_at,
            "updated_at": created_at,
            "snapshot_count": 0,
            "latest_snapshot_id": None,
            "snapshots": [],
        }
    index["snapshots"].append(entry)
    index["updated_at"] = created_at
    index["snapshot_count"] = len(index["snapshots"])
    index["latest_snapshot_id"] = snapshot_id

    (thread_dir / _THREAD_INDEX).write_text(
        json.dumps(index, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    (thread_dir / _THREAD_INDEX_MD).write_text(render_index_md(index), encoding="utf-8")
    return index


def inspect_thread(thread_dir: Path) -> dict[str, Any]:
    """Verify each snapshot bundle and its index-recorded hashes. Read-only."""
    index = read_thread_index(thread_dir)
    if index is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "artifact": THREAD_INSPECTION_ARTIFACT,
            "valid": False,
            "snapshot_count": 0,
            "latest_snapshot_id": None,
            "snapshots": [],
            "errors": [f"{_THREAD_INDEX} not found"],
        }
    errors: list[str] = []
    results: list[dict[str, Any]] = []
    for entry in index.get("snapshots", []):
        sid = entry.get("snapshot_id", "")
        snapshot_dir = thread_dir / entry.get("path", f"{_THREAD_PACKETS}/{sid}")
        snap_errors: list[str] = []
        exists = snapshot_dir.exists()
        bundle_valid = False
        if not exists:
            snap_errors.append(f"missing snapshot directory: {sid}")
        else:
            inspection = inspect_bundle(snapshot_dir)
            bundle_valid = bool(inspection["valid"])
            snap_errors.extend(f"{sid}: {e}" for e in inspection["errors"])
            manifest_path = snapshot_dir / _BUNDLE_MANIFEST
            packet_path = snapshot_dir / _BUNDLE_JSON
            if entry.get("manifest_sha256") and manifest_path.exists():
                actual = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
                if actual != entry["manifest_sha256"]:
                    snap_errors.append(f"{sid}: manifest_sha256 mismatch vs index")
            if entry.get("packet_sha256") and packet_path.exists():
                actual = hashlib.sha256(packet_path.read_bytes()).hexdigest()
                if actual != entry["packet_sha256"]:
                    snap_errors.append(f"{sid}: packet_sha256 mismatch vs index")
        results.append({
            "snapshot_id": sid,
            "exists": exists,
            "bundle_valid": bundle_valid,
            "errors": snap_errors,
        })
        errors.extend(snap_errors)
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact": THREAD_INSPECTION_ARTIFACT,
        "valid": not errors,
        "snapshot_count": len(index.get("snapshots", [])),
        "latest_snapshot_id": index.get("latest_snapshot_id"),
        "snapshots": results,
        "errors": errors,
    }


def _thread_diff(thread_dir: Path, old_id: str, new_id: str) -> dict[str, Any]:
    old_packet = load_packet_dict(thread_dir / _THREAD_PACKETS / old_id)
    new_packet = load_packet_dict(thread_dir / _THREAD_PACKETS / new_id)
    return diff_packets(old_packet, new_packet, old_path=old_id, new_path=new_id)


def thread_diff_latest(thread_dir: Path) -> dict[str, Any]:
    """Diff the latest two snapshots (index order). Read-only."""
    index = read_thread_index(thread_dir)
    snapshots = (index or {}).get("snapshots", [])
    if len(snapshots) < 2:
        raise ThreadError("need at least two snapshots to diff")
    return _thread_diff(thread_dir, snapshots[-2]["snapshot_id"], snapshots[-1]["snapshot_id"])


def thread_diff_by_id(thread_dir: Path, old_id: str, new_id: str) -> dict[str, Any]:
    """Diff two snapshots by exact id. Read-only."""
    index = read_thread_index(thread_dir)
    if index is None:
        raise ThreadError(f"{_THREAD_INDEX} not found")
    known = {s["snapshot_id"] for s in index.get("snapshots", [])}
    for sid in (old_id, new_id):
        if sid not in known:
            raise ThreadError(f"unknown snapshot id: {sid}")
    return _thread_diff(thread_dir, old_id, new_id)


def render_index_md(index: dict[str, Any]) -> str:
    """Render INDEX.md (human timeline mirror of index.json). Presentation only."""
    lines: list[str] = []
    lines.append("# Chimera Work Packet Review Thread")
    lines.append("")
    lines.append(f"Advisory only. {THREAD_ADVISORY}.")
    lines.append("")
    lines.append("## Snapshots")
    lines.append("")
    lines.append("| Snapshot | Created | Claims | Unresolved | Tool notes | Candidates | Label |")
    lines.append("|---|---|---:|---:|---:|---:|---|")
    for snap in index.get("snapshots", []):
        s = snap.get("packet_summary", {})
        label = snap.get("label") or ""
        lines.append(
            f"| {snap.get('snapshot_id', '')} | {snap.get('created_at', '')} "
            f"| {s.get('shown_claim_count', 0)} | {s.get('open_or_unresolved_count', 0)} "
            f"| {s.get('tool_note_count', 0)} | {s.get('candidate_count', 0)} | {label} |"
        )
    lines.append("")
    lines.append("## Latest")
    lines.append("")
    latest = index.get("latest_snapshot_id")
    if latest:
        lines.append(f"- latest snapshot: {latest}")
        lines.append(f"- packet: {_THREAD_PACKETS}/{latest}/{_BUNDLE_MD}")
        lines.append(f"- JSON: {_THREAD_PACKETS}/{latest}/{_BUNDLE_JSON}")
    else:
        lines.append("- (none)")
    return "\n".join(lines) + "\n"


def render_thread_list_text(index: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Chimera Work Packet Review Thread")
    lines.append("")
    lines.append("Advisory only. Local packet timeline.")
    lines.append(f"- snapshots: {index.get('snapshot_count', 0)}")
    lines.append(f"- latest: {index.get('latest_snapshot_id') or '(none)'}")
    for snap in index.get("snapshots", []):
        s = snap.get("packet_summary", {})
        label = snap.get("label")
        suffix = f" — {label}" if label else ""
        counts = (
            f"claims={s.get('shown_claim_count', 0)} "
            f"unresolved={s.get('open_or_unresolved_count', 0)} "
            f"tool_notes={s.get('tool_note_count', 0)} "
            f"candidates={s.get('candidate_count', 0)}"
        )
        lines.append(
            f"- {snap.get('snapshot_id', '')} ({snap.get('created_at', '')}): {counts}{suffix}"
        )
    return "\n".join(lines)


def render_thread_inspect_text(result: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Chimera Work Packet Review Thread inspection")
    lines.append("")
    lines.append("Advisory only. Local thread integrity check (bundle hashes/sizes).")
    lines.append(f"- valid: {result['valid']}")
    lines.append(f"- snapshots: {result['snapshot_count']}")
    lines.append(f"- latest: {result.get('latest_snapshot_id') or '(none)'}")
    for snap in result.get("snapshots", []):
        lines.append(
            f"- {snap['snapshot_id']}: exists={snap['exists']} bundle_valid={snap['bundle_valid']}"
        )
        for err in snap.get("errors", []):
            lines.append(f"  - {err}")
    return "\n".join(lines)
