"""Memory-side Evidence Bridge v0 — a read-only evidence normalization scaffold.

The bridge consumes *exported* Chimera Memory artifacts (a Harness Evidence Bundle
directory, or a Work Packet bundle directory that references one) and normalizes
them into a stable, neutral input record (``memory_bridge_evidence.v1``) that a
future Engine/Harness branch can consume — by reading the on-disk artifact
contract, not Memory's in-memory classes.

It answers only neutral, observational questions: what local observations exist,
which session/brief they attach to, which harness runs and exit codes were
recorded, which outputs were redacted or truncated, which consequence observations
and suggested checks were listed, which manifest checks held, and which files and
hashes make up the artifact.

It deliberately decides nothing. It does not execute commands, score, rank, route,
approve, merge, train, or grant authority; it never interprets an exit code as a
verdict. Reading is read-only: it reads files only, mutates no source bundle, and
creates or mutates no ``.chimera-memory`` store. ``normalize`` writes only to an
explicit output path.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "memory_bridge_evidence.v1"
INSPECTION_ARTIFACT = "memory_bridge_inspection"

# On-disk artifact contract (file names produced by the Memory bundle writers).
_HEB_EVIDENCE_JSON = "harness-evidence.json"
_HEB_RUNS_JSON = "harness-runs.json"
_WORK_PACKET_JSON = "work-packet.json"
_MANIFEST = "manifest.json"

SOURCE_HARNESS_EVIDENCE = "harness_evidence_bundle"
SOURCE_WORK_PACKET = "work_packet_bundle"
SOURCE_UNKNOWN = "unknown"

# Mutable store names that must never appear inside a portable, exported bundle.
_STORE_FILE_NAMES = frozenset({
    "harness_runs.jsonl",
    "consequence_observations.jsonl",
    "claims.jsonl",
    "outcomes.jsonl",
    "scores.jsonl",
    "sessions.jsonl",
    "claim_locks.jsonl",
    "work_briefs.jsonl",
    "work_session_events.jsonl",
    "tool_notes.jsonl",
    "tool_activity.jsonl",
})

# Observed harness-run fields carried into normalized evidence (no verdict fields).
_HARNESS_RUN_FIELDS = (
    "run_id",
    "created_at",
    "mode",
    "command",
    "cwd",
    "exit_code",
    "status",
    "check_label",
    "redaction_applied",
    "output_truncated",
    "stdout_sha256",
    "stderr_sha256",
    "artifact_refs",
)

# Observed consequence-observation fields carried into normalized evidence.
_CONSEQUENCE_FIELDS = (
    "observation_id",
    "observation_kind",
    "subject",
    "suggested_checks",
    "note",
    "work_session_id",
    "brief_id",
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _package_version() -> str:
    try:
        from importlib.metadata import version

        return version("chimera-memory")
    except Exception:  # noqa: BLE001 - version metadata is best-effort, never fatal
        return "unknown"


@dataclass(frozen=True)
class MemoryBridgeManifestCheck:
    file_count: int = 0
    hash_mismatch_count: int = 0
    missing_file_count: int = 0
    unexpected_store_file_count: int = 0
    parse_error_count: int = 0
    recognized_record_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_count": self.file_count,
            "hash_mismatch_count": self.hash_mismatch_count,
            "missing_file_count": self.missing_file_count,
            "unexpected_store_file_count": self.unexpected_store_file_count,
            "parse_error_count": self.parse_error_count,
            "recognized_record_count": self.recognized_record_count,
        }


@dataclass(frozen=True)
class MemoryBridgeWorkPacketReference:
    path: str | None = None
    resolved: bool = False
    resolved_path: str | None = None
    manifest_sha256: str | None = None
    schema_version: str | None = None
    harness_run_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "resolved": self.resolved,
            "resolved_path": self.resolved_path,
            "manifest_sha256": self.manifest_sha256,
            "schema_version": self.schema_version,
            "harness_run_count": self.harness_run_count,
        }


@dataclass(frozen=True)
class MemoryBridgeEvidence:
    schema_version: str
    created_at: str
    source_kind: str
    source_path: str
    source_manifest_sha256: str | None
    memory_version: str | None
    work_session_id: str | None
    brief_id: str | None
    harness_runs: tuple[dict[str, Any], ...]
    consequence_observations: tuple[dict[str, Any], ...]
    suggested_checks: tuple[str, ...]
    artifact_refs: tuple[str, ...]
    manifest: MemoryBridgeManifestCheck
    work_packet_reference: MemoryBridgeWorkPacketReference | None
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "source_kind": self.source_kind,
            "source_path": self.source_path,
            "source_manifest_sha256": self.source_manifest_sha256,
            "memory_version": self.memory_version,
            "work_session_id": self.work_session_id,
            "brief_id": self.brief_id,
            "harness_runs": [dict(r) for r in self.harness_runs],
            "consequence_observations": [dict(o) for o in self.consequence_observations],
            "suggested_checks": list(self.suggested_checks),
            "artifact_refs": list(self.artifact_refs),
            "manifest": self.manifest.to_dict(),
            "notes": list(self.notes),
        }
        if self.work_packet_reference is not None:
            out["work_packet_reference"] = self.work_packet_reference.to_dict()
        return out

    def inspect_dict(self) -> dict[str, Any]:
        """Compact, count-oriented inspection view (no full record arrays)."""
        out = {
            "schema_version": self.schema_version,
            "artifact": INSPECTION_ARTIFACT,
            "created_at": self.created_at,
            "source_kind": self.source_kind,
            "source_path": self.source_path,
            "source_manifest_sha256": self.source_manifest_sha256,
            "memory_version": self.memory_version,
            "work_session_id": self.work_session_id,
            "brief_id": self.brief_id,
            "manifest": self.manifest.to_dict(),
            "harness_run_count": len(self.harness_runs),
            "consequence_observation_count": len(self.consequence_observations),
            "suggested_check_count": len(self.suggested_checks),
            "artifact_ref_count": len(self.artifact_refs),
            "notes": list(self.notes),
        }
        if self.work_packet_reference is not None:
            out["work_packet_reference"] = self.work_packet_reference.to_dict()
        return out


class BridgeError(Exception):
    """Raised only when required files for the selected source are unreadable."""


@dataclass
class _ManifestAccum:
    file_count: int = 0
    hash_mismatch_count: int = 0
    missing_file_count: int = 0
    unexpected_store_file_count: int = 0
    parse_error_count: int = 0
    notes: list[str] = field(default_factory=list)


def detect_source_kind(bundle_dir: Path) -> str:
    bundle_dir = Path(bundle_dir)
    if (bundle_dir / _HEB_EVIDENCE_JSON).exists():
        return SOURCE_HARNESS_EVIDENCE
    if (bundle_dir / _WORK_PACKET_JSON).exists():
        return SOURCE_WORK_PACKET
    return SOURCE_UNKNOWN


def _verify_manifest(
    bundle_dir: Path, acc: _ManifestAccum, *, prefix: str = ""
) -> tuple[str | None, dict[str, Any] | None]:
    """Recompute each manifest-listed file hash. Returns (manifest_sha256, manifest dict)."""
    manifest_path = bundle_dir / _MANIFEST
    label = f"{prefix}{_MANIFEST}"
    if not manifest_path.exists():
        acc.missing_file_count += 1
        acc.notes.append(f"{label} not found")
        return None, None
    raw = manifest_path.read_bytes()
    manifest_sha256 = _sha256(raw)
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        acc.parse_error_count += 1
        acc.notes.append(f"{label} parse error: {exc}")
        return manifest_sha256, None
    files = manifest.get("files", []) if isinstance(manifest, dict) else []
    acc.file_count += len(files) + 1  # + manifest.json itself
    for entry in files:
        name = entry.get("path", "") if isinstance(entry, dict) else ""
        fp = bundle_dir / name
        if not fp.exists():
            acc.missing_file_count += 1
            acc.notes.append(f"missing file: {prefix}{name}")
            continue
        if _sha256(fp.read_bytes()) != entry.get("sha256"):
            acc.hash_mismatch_count += 1
            acc.notes.append(f"hash mismatch: {prefix}{name}")
    return manifest_sha256, manifest


def _count_unexpected_store_files(bundle_dir: Path, acc: _ManifestAccum) -> None:
    for p in sorted(bundle_dir.rglob("*")):
        rel = p.relative_to(bundle_dir)
        if p.is_dir():
            if p.name == ".chimera-memory":
                acc.unexpected_store_file_count += 1
                acc.notes.append(f"unexpected store directory: {rel}")
            continue
        if p.name in _STORE_FILE_NAMES or p.suffix == ".jsonl":
            acc.unexpected_store_file_count += 1
            acc.notes.append(f"unexpected store file: {rel}")


def _normalize_harness_run(raw: dict[str, Any]) -> dict[str, Any]:
    """Project a run dict to observed fields only (unknown fields ignored deterministically)."""
    out: dict[str, Any] = {}
    for k in _HARNESS_RUN_FIELDS:
        if k == "artifact_refs":
            v = raw.get(k)
            out[k] = [str(x) for x in v if isinstance(x, str)] if isinstance(v, list) else []
        else:
            out[k] = raw.get(k)
    return out


def _normalize_consequence(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in _CONSEQUENCE_FIELDS:
        if k == "suggested_checks":
            v = raw.get(k)
            out[k] = [str(x) for x in v if isinstance(x, str)] if isinstance(v, list) else []
        elif k == "subject":
            v = raw.get(k)
            out[k] = dict(v) if isinstance(v, dict) else {}
        else:
            out[k] = raw.get(k)
    return out


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_harness_evidence_bundle(
    bundle_dir: Path, *, created_at: str
) -> MemoryBridgeEvidence:
    acc = _ManifestAccum()
    manifest_sha256, _ = _verify_manifest(bundle_dir, acc)
    _count_unexpected_store_files(bundle_dir, acc)

    harness_runs: tuple[dict[str, Any], ...] = ()
    work_session_id: str | None = None
    brief_id: str | None = None
    memory_version: str | None = None
    artifact_refs: list[str] = []

    ev_path = bundle_dir / _HEB_EVIDENCE_JSON
    if not ev_path.exists():
        acc.missing_file_count += 1
        acc.notes.append(f"{_HEB_EVIDENCE_JSON} not found")
    else:
        try:
            ev = _read_json(ev_path)
        except (json.JSONDecodeError, OSError) as exc:
            acc.parse_error_count += 1
            acc.notes.append(f"{_HEB_EVIDENCE_JSON} parse error: {exc}")
            ev = {}
        runs = ev.get("harness_runs", []) if isinstance(ev, dict) else []
        harness_runs = tuple(_normalize_harness_run(r) for r in runs if isinstance(r, dict))
        filters = ev.get("filters", {}) if isinstance(ev, dict) else {}
        work_session_id = filters.get("work_session_id")
        brief_id = filters.get("brief_id")
        source = ev.get("source", {}) if isinstance(ev, dict) else {}
        memory_version = source.get("version") if isinstance(source, dict) else None
        for r in harness_runs:
            artifact_refs.extend(r.get("artifact_refs", []))
        if work_session_id is None and harness_runs:
            work_session_id = harness_runs[0].get("work_session_id")

    recognized = len(harness_runs)
    manifest = MemoryBridgeManifestCheck(
        file_count=acc.file_count,
        hash_mismatch_count=acc.hash_mismatch_count,
        missing_file_count=acc.missing_file_count,
        unexpected_store_file_count=acc.unexpected_store_file_count,
        parse_error_count=acc.parse_error_count,
        recognized_record_count=recognized,
    )
    return MemoryBridgeEvidence(
        schema_version=SCHEMA_VERSION,
        created_at=created_at,
        source_kind=SOURCE_HARNESS_EVIDENCE,
        source_path=str(bundle_dir),
        source_manifest_sha256=manifest_sha256,
        memory_version=memory_version,
        work_session_id=work_session_id,
        brief_id=brief_id,
        harness_runs=harness_runs,
        consequence_observations=(),
        suggested_checks=(),
        artifact_refs=tuple(dict.fromkeys(artifact_refs)),
        manifest=manifest,
        work_packet_reference=None,
        notes=tuple(acc.notes),
    )


def _resolve_reference(packet_dir: Path, ref: dict[str, Any], acc: _ManifestAccum
                       ) -> MemoryBridgeWorkPacketReference:
    raw_path = ref.get("path")
    declared_sha = ref.get("manifest_sha256")
    declared_schema = ref.get("schema_version")
    declared_runs = ref.get("harness_run_count")
    if not isinstance(raw_path, str) or not raw_path:
        acc.parse_error_count += 1
        acc.notes.append("harness_evidence_bundle reference has no path")
        return MemoryBridgeWorkPacketReference(
            path=None, resolved=False, manifest_sha256=declared_sha,
            schema_version=declared_schema, harness_run_count=declared_runs,
        )
    # Resolve relative to the packet bundle dir deterministically: try the packet dir,
    # then its parent (the common output root for sibling bundles), then the path
    # as-given (cwd-relative / absolute). First base with a manifest.json wins.
    candidate = Path(raw_path)
    if candidate.is_absolute():
        bases = [candidate]
    else:
        bases = [packet_dir / candidate, packet_dir.parent / candidate, candidate]
    resolved: Path | None = None
    for base in bases:
        if (base / _MANIFEST).exists():
            resolved = base
            break
    if resolved is None:
        acc.missing_file_count += 1
        acc.notes.append(f"referenced harness evidence bundle manifest not found: {raw_path}")
        return MemoryBridgeWorkPacketReference(
            path=raw_path, resolved=False, resolved_path=str(bases[0]),
            manifest_sha256=declared_sha, schema_version=declared_schema,
            harness_run_count=declared_runs,
        )
    # Fold the referenced bundle's manifest check into the overall counts.
    actual_sha, _ = _verify_manifest(resolved, acc, prefix=f"{raw_path}/")
    _count_unexpected_store_files(resolved, acc)
    if declared_sha is not None and actual_sha is not None and declared_sha != actual_sha:
        acc.hash_mismatch_count += 1
        acc.notes.append("referenced bundle manifest_sha256 differs from the reference")
    return MemoryBridgeWorkPacketReference(
        path=raw_path, resolved=True, resolved_path=str(resolved),
        manifest_sha256=actual_sha or declared_sha,
        schema_version=declared_schema, harness_run_count=declared_runs,
    )


def _normalize_work_packet_bundle(bundle_dir: Path, *, created_at: str) -> MemoryBridgeEvidence:
    acc = _ManifestAccum()
    manifest_sha256, _ = _verify_manifest(bundle_dir, acc)
    _count_unexpected_store_files(bundle_dir, acc)

    harness_runs: tuple[dict[str, Any], ...] = ()
    consequence_observations: tuple[dict[str, Any], ...] = ()
    work_session_id: str | None = None
    brief_id: str | None = None
    suggested_checks: list[str] = []
    artifact_refs: list[str] = []
    wp_ref: MemoryBridgeWorkPacketReference | None = None

    wp_path = bundle_dir / _WORK_PACKET_JSON
    if not wp_path.exists():
        acc.missing_file_count += 1
        acc.notes.append(f"{_WORK_PACKET_JSON} not found")
    else:
        try:
            wp = _read_json(wp_path)
        except (json.JSONDecodeError, OSError) as exc:
            acc.parse_error_count += 1
            acc.notes.append(f"{_WORK_PACKET_JSON} parse error: {exc}")
            wp = {}
        runs = wp.get("harness_runs", []) if isinstance(wp, dict) else []
        harness_runs = tuple(_normalize_harness_run(r) for r in runs if isinstance(r, dict))
        obs = wp.get("consequence_observations", []) if isinstance(wp, dict) else []
        consequence_observations = tuple(
            _normalize_consequence(o) for o in obs if isinstance(o, dict)
        )
        filters = wp.get("filters", {}) if isinstance(wp, dict) else {}
        work_session_id = filters.get("session_id")
        for o in consequence_observations:
            suggested_checks.extend(o.get("suggested_checks", []))
            if brief_id is None and o.get("brief_id"):
                brief_id = o.get("brief_id")
        for r in harness_runs:
            artifact_refs.extend(r.get("artifact_refs", []))
        ref = wp.get("harness_evidence_bundle") if isinstance(wp, dict) else None
        if isinstance(ref, dict):
            wp_ref = _resolve_reference(bundle_dir, ref, acc)
        else:
            acc.notes.append("work packet has no harness_evidence_bundle reference")

    recognized = len(harness_runs) + len(consequence_observations)
    manifest = MemoryBridgeManifestCheck(
        file_count=acc.file_count,
        hash_mismatch_count=acc.hash_mismatch_count,
        missing_file_count=acc.missing_file_count,
        unexpected_store_file_count=acc.unexpected_store_file_count,
        parse_error_count=acc.parse_error_count,
        recognized_record_count=recognized,
    )
    return MemoryBridgeEvidence(
        schema_version=SCHEMA_VERSION,
        created_at=created_at,
        source_kind=SOURCE_WORK_PACKET,
        source_path=str(bundle_dir),
        source_manifest_sha256=manifest_sha256,
        memory_version=None,
        work_session_id=work_session_id,
        brief_id=brief_id,
        harness_runs=harness_runs,
        consequence_observations=consequence_observations,
        suggested_checks=tuple(dict.fromkeys(suggested_checks)),
        artifact_refs=tuple(dict.fromkeys(artifact_refs)),
        manifest=manifest,
        work_packet_reference=wp_ref,
        notes=tuple(acc.notes),
    )


def normalize_bundle(bundle_dir: Path, *, created_at: str) -> MemoryBridgeEvidence:
    """Read a bundle directory and normalize it to ``memory_bridge_evidence.v1``. Read-only.

    Detects the source kind from the on-disk contract. Raises :class:`BridgeError`
    only when the directory matches no known source (so nothing required can be read).
    """
    bundle_dir = Path(bundle_dir)
    kind = detect_source_kind(bundle_dir)
    if kind == SOURCE_HARNESS_EVIDENCE:
        return _normalize_harness_evidence_bundle(bundle_dir, created_at=created_at)
    if kind == SOURCE_WORK_PACKET:
        return _normalize_work_packet_bundle(bundle_dir, created_at=created_at)
    raise BridgeError(
        f"no recognized Memory artifact in {bundle_dir} "
        f"(expected {_HEB_EVIDENCE_JSON} or {_WORK_PACKET_JSON})"
    )


def render_inspect_text(result: dict[str, Any]) -> str:
    m = result["manifest"]
    lines: list[str] = []
    lines.append("# Chimera Memory Evidence Bridge inspection")
    lines.append("")
    lines.append("Read-only normalized evidence summary. Counts only; not a verdict.")
    lines.append("")
    lines.append(f"- source_kind: {result['source_kind']}")
    lines.append(f"- source_path: {result['source_path']}")
    lines.append(f"- source_manifest_sha256: {result.get('source_manifest_sha256')}")
    lines.append(f"- memory_version: {result.get('memory_version')}")
    lines.append(f"- work_session_id: {result.get('work_session_id')}")
    lines.append(f"- brief_id: {result.get('brief_id')}")
    lines.append(f"- harness_run_count: {result['harness_run_count']}")
    lines.append(f"- consequence_observation_count: {result['consequence_observation_count']}")
    lines.append(f"- suggested_check_count: {result['suggested_check_count']}")
    lines.append(f"- artifact_ref_count: {result['artifact_ref_count']}")
    lines.append("")
    lines.append("## Manifest check")
    lines.append(f"- file_count: {m['file_count']}")
    lines.append(f"- hash_mismatch_count: {m['hash_mismatch_count']}")
    lines.append(f"- missing_file_count: {m['missing_file_count']}")
    lines.append(f"- unexpected_store_file_count: {m['unexpected_store_file_count']}")
    lines.append(f"- parse_error_count: {m['parse_error_count']}")
    lines.append(f"- recognized_record_count: {m['recognized_record_count']}")
    ref = result.get("work_packet_reference")
    if ref is not None:
        lines.append("")
        lines.append("## Work packet reference")
        lines.append(f"- path: {ref.get('path')}")
        lines.append(f"- resolved: {ref.get('resolved')}")
        lines.append(f"- manifest_sha256: {ref.get('manifest_sha256')}")
        lines.append(f"- harness_run_count: {ref.get('harness_run_count')}")
    if result.get("notes"):
        lines.append("")
        lines.append("## Notes")
        for n in result["notes"]:
            lines.append(f"- {n}")
    return "\n".join(lines)


__all__ = [
    "INSPECTION_ARTIFACT",
    "SCHEMA_VERSION",
    "SOURCE_HARNESS_EVIDENCE",
    "SOURCE_UNKNOWN",
    "SOURCE_WORK_PACKET",
    "BridgeError",
    "MemoryBridgeEvidence",
    "MemoryBridgeManifestCheck",
    "MemoryBridgeWorkPacketReference",
    "detect_source_kind",
    "normalize_bundle",
    "render_inspect_text",
]
