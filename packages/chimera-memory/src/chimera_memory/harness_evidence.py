"""Harness Evidence Bundle v1 — a portable, redacted, hash-manifested export.

A Harness Evidence Bundle is an *evidence transport format*: it packages local
Harness Lite run observations (what was observed, which session/brief/labels, which
exit codes, which outputs were redacted or truncated, which artifact refs were
attached, which files make up the bundle and their hashes) into a portable
directory that external Chimera Engine / Harness / Forge tooling can consume as a
neutral observation artifact — without importing chimera-memory.

It deliberately does NOT answer whether code was correct, whether a task was
complete, whether anything is "safe to merge", whether a command's exit code is a
verdict, or whether a model/agent should receive authority. An exit code is
recorded, never interpreted; statuses are neutral (``completed`` / ``interrupted``
/ ``unknown``).

Boundaries:
- read-only on the memory store (reads the ledger, writes nothing to it);
- explicit write only into the chosen output directory;
- executes nothing and creates no harness runs or work-session events;
- never includes unbounded stdout/stderr (full output is referenced by sha256);
- stdout/stderr previews are omitted by default (only with ``include_previews``);
- hashes every generated bundle file with deterministic ordering and JSON.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chimera_memory.harness_run import HarnessRun, filter_runs, read_harness_runs
from chimera_memory.storage import MemoryStore

SCHEMA_VERSION = "harness_evidence_bundle.v1"
BUNDLE_ARTIFACT = "chimera_harness_evidence_bundle"
INSPECTION_ARTIFACT = "chimera_harness_evidence_bundle_inspection"
DIFF_ARTIFACT = "chimera_harness_evidence_bundle_diff"

_MD = "HARNESS_EVIDENCE.md"
_EVIDENCE_JSON = "harness-evidence.json"
_RUNS_JSON = "harness-runs.json"
_MANIFEST = "manifest.json"
_README = "README.md"
# Content files hashed into the manifest (manifest.json cannot hash itself).
_CONTENT_FILES = (_MD, _EVIDENCE_JSON, _RUNS_JSON, _README)

ADVISORY = (
    "portable local harness run observation bundle; not a correctness, safety, "
    "approval, merge, or production-readiness signal, and not a form of verification"
)

# Compact, output-free run fields carried in the portable bundle (no full stdout/stderr).
_RUN_FIELDS = (
    "run_id",
    "created_at",
    "started_at",
    "ended_at",
    "duration_ms",
    "mode",
    "command",
    "cwd",
    "exit_code",
    "status",
    "check_label",
    "note",
    "tags",
    "work_session_id",
    "brief_id",
    "redaction_applied",
    "output_truncated",
    "stdout_sha256",
    "stderr_sha256",
    "artifact_refs",
    "source",
)

# Mutable store names that must never appear inside a portable bundle.
_STORE_FILE_NAMES = frozenset({
    "harness_runs.jsonl",
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


class HarnessEvidenceError(Exception):
    """Raised for evidence-bundle precondition failures (clean CLI errors)."""


def _exit_phrase(exit_code: int | None) -> str:
    if exit_code is None:
        return "exit code unknown"
    return "exit code 0" if exit_code == 0 else f"nonzero exit code ({exit_code})"


def _package_version() -> str:
    try:
        from importlib.metadata import version

        return version("chimera-memory")
    except Exception:  # noqa: BLE001 - version metadata is best-effort, never fatal
        return "unknown"


def evidence_run(run: HarnessRun, *, include_previews: bool = False) -> dict[str, Any]:
    """Compact, portable projection of one run. Full stdout/stderr is never included.

    Bounded, already-redacted previews are included only when ``include_previews``
    is set; by default a portable bundle carries no preview text at all.
    """
    d = run.to_dict()
    out: dict[str, Any] = {k: d[k] for k in _RUN_FIELDS}
    if include_previews:
        out["stdout_preview"] = d["stdout_preview"]
        out["stderr_preview"] = d["stderr_preview"]
    return out


@dataclass(frozen=True)
class HarnessEvidenceSource:
    package: str
    version: str
    store: str

    def to_dict(self) -> dict[str, Any]:
        return {"package": self.package, "version": self.version, "store": self.store}


@dataclass(frozen=True)
class HarnessEvidenceRedactionSummary:
    redacted_preview_count: int
    truncated_output_count: int
    previews_included: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "redacted_preview_count": self.redacted_preview_count,
            "truncated_output_count": self.truncated_output_count,
            "previews_included": self.previews_included,
        }


@dataclass(frozen=True)
class HarnessEvidenceBundle:
    schema_version: str
    bundle_id: str
    artifact: str
    advisory: str
    created_at: str
    root: str
    filters: dict[str, Any]
    source: HarnessEvidenceSource
    summary: dict[str, int]
    harness_runs: tuple[dict[str, Any], ...]
    redaction_summary: HarnessEvidenceRedactionSummary

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "bundle_id": self.bundle_id,
            "artifact": self.artifact,
            "advisory": self.advisory,
            "created_at": self.created_at,
            "root": self.root,
            "filters": dict(self.filters),
            "source": self.source.to_dict(),
            "summary": dict(self.summary),
            "harness_runs": [dict(r) for r in self.harness_runs],
            "redaction_summary": self.redaction_summary.to_dict(),
        }


def _bundle_id(ev_runs: tuple[dict[str, Any], ...]) -> str:
    """Deterministic id from the run content (stable across rebuilds of the same runs)."""
    payload = json.dumps(list(ev_runs), sort_keys=True).encode("utf-8")
    return "heb_" + hashlib.sha256(payload).hexdigest()[:16]


def build_harness_evidence_bundle(
    store: MemoryStore,
    *,
    created_at: str,
    work_session_id: str | None = None,
    brief_id: str | None = None,
    tag: str | None = None,
    limit: int | None = None,
    include_previews: bool = False,
    root_label: str = ".",
    store_label: str = ".chimera-memory",
) -> HarnessEvidenceBundle:
    """Build a portable evidence bundle from the local ledger. Read-only; writes nothing.

    Exact-match filters combine with AND; ``limit`` keeps the most-recent N (stored
    order). Runs are projected output-free; previews are omitted unless
    ``include_previews`` is set.
    """
    runs = filter_runs(
        read_harness_runs(store),
        work_session_id=work_session_id,
        brief_id=brief_id,
        tag=tag,
    )
    if limit is not None:
        runs = runs[-limit:] if limit > 0 else []
    ev_runs = tuple(evidence_run(r, include_previews=include_previews) for r in runs)

    summary: dict[str, int] = {
        "harness_run_count": len(ev_runs),
        "executed_run_count": sum(1 for r in ev_runs if r["mode"] == "executed"),
        "recorded_run_count": sum(1 for r in ev_runs if r["mode"] == "recorded"),
        "redacted_preview_count": sum(1 for r in ev_runs if r["redaction_applied"]),
        "truncated_output_count": sum(1 for r in ev_runs if r["output_truncated"]),
        "artifact_ref_count": sum(len(r["artifact_refs"]) for r in ev_runs),
    }
    redaction = HarnessEvidenceRedactionSummary(
        redacted_preview_count=summary["redacted_preview_count"],
        truncated_output_count=summary["truncated_output_count"],
        previews_included=include_previews,
    )
    return HarnessEvidenceBundle(
        schema_version=SCHEMA_VERSION,
        bundle_id=_bundle_id(ev_runs),
        artifact=BUNDLE_ARTIFACT,
        advisory=ADVISORY,
        created_at=created_at,
        root=root_label,
        filters={
            "work_session_id": work_session_id,
            "brief_id": brief_id,
            "tag": tag,
            "limit": limit,
            "include_previews": include_previews,
        },
        source=HarnessEvidenceSource(
            package="chimera-memory", version=_package_version(), store=store_label
        ),
        summary=summary,
        harness_runs=ev_runs,
        redaction_summary=redaction,
    )


def _filter_label(filters: dict[str, Any]) -> str:
    active = {k: v for k, v in filters.items() if v is not None and v is not False}
    return " ".join(f"{k}={v}" for k, v in active.items()) if active else "none"


def render_markdown(bundle: HarnessEvidenceBundle) -> str:
    """Render the bundle overview to neutral markdown. Presentation only; no verdict."""
    s = bundle.summary
    lines: list[str] = []
    lines.append("# Chimera Harness Evidence Bundle")
    lines.append("")
    lines.append(f"Advisory only. {bundle.advisory}.")
    lines.append("")
    lines.append("An exit code is recorded, not interpreted as a verdict.")
    lines.append("")
    lines.append("## Bundle")
    lines.append(f"- bundle_id: {bundle.bundle_id}")
    lines.append(f"- schema_version: {bundle.schema_version}")
    lines.append(f"- created_at: {bundle.created_at}")
    lines.append(f"- root: {bundle.root}")
    lines.append(
        f"- source: {bundle.source.package} {bundle.source.version} "
        f"(store {bundle.source.store})"
    )
    lines.append(f"- filters: {_filter_label(bundle.filters)}")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- harness runs: {s['harness_run_count']}")
    lines.append(f"- executed: {s['executed_run_count']}")
    lines.append(f"- recorded: {s['recorded_run_count']}")
    lines.append(f"- redacted previews: {s['redacted_preview_count']}")
    lines.append(f"- truncated outputs: {s['truncated_output_count']}")
    lines.append(f"- artifact refs: {s['artifact_ref_count']}")
    lines.append(f"- previews included: {bundle.redaction_summary.previews_included}")
    lines.append("")
    lines.append("## Run observations")
    if bundle.harness_runs:
        for r in bundle.harness_runs:
            label = f" — {r['check_label']}" if r.get("check_label") else ""
            lines.append(
                f"- [{r['mode']}] {r['command']} ({_exit_phrase(r['exit_code'])}){label}"
            )
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append(
        "Full stdout/stderr is never included; outputs are referenced by sha256. Bounded, "
        "redacted previews appear in harness-evidence.json only when the bundle was created "
        "with previews included."
    )
    return "\n".join(lines)


_README_TEXT = (
    "# Chimera Harness Evidence Bundle\n\n"
    "A portable, redacted, hash-manifested export of local harness run observations.\n\n"
    f"- `{_MD}` — the human-readable overview.\n"
    f"- `{_EVIDENCE_JSON}` — the machine-readable bundle (filters, source, summary, runs, "
    "redaction summary).\n"
    f"- `{_RUNS_JSON}` — just the portable run array, for external tools.\n"
    f"- `{_MANIFEST}` — the bundle manifest (file list + sha256 + byte counts).\n"
    f"- `{_README}` — this file.\n\n"
    "Inspect it with `chimera-memory harness bundle-inspect <dir>` and compare two bundles "
    "with `chimera-memory harness bundle-diff <a> <b>`.\n\n"
    "Full stdout/stderr is never included; outputs are referenced by sha256. Bounded, "
    "redacted previews are omitted by default. An exit code is recorded, not interpreted as "
    "a verdict.\n\n"
    "Advisory only — a local observation artifact; not a correctness, safety, approval, "
    "merge, or production-readiness signal, and not a form of verification.\n"
)


def _hashed_entry(name: str, data: bytes) -> dict[str, Any]:
    return {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def write_harness_evidence_bundle(
    bundle: HarnessEvidenceBundle,
    *,
    output_dir: Path,
    force: bool = False,
) -> dict[str, Any]:
    """Write the portable bundle (5 files) and return the manifest dict.

    Writes only into ``output_dir``; never touches the memory store. The parent of
    ``output_dir`` must already exist. A non-empty ``output_dir`` is refused unless
    ``force`` is set (then the bundle files are overwritten).
    """
    output_dir = Path(output_dir)
    if output_dir.exists() and output_dir.is_file():
        raise HarnessEvidenceError(f"output path is a file, not a directory: {output_dir}")
    if not output_dir.parent.exists():
        raise HarnessEvidenceError(f"parent directory does not exist: {output_dir.parent}")
    if output_dir.exists():
        existing = [p.name for p in output_dir.iterdir()]
        if existing and not force:
            raise HarnessEvidenceError(
                f"output directory is not empty: {output_dir} (use --force to overwrite)"
            )
    else:
        output_dir.mkdir()

    runs_payload = {
        "schema_version": SCHEMA_VERSION,
        "bundle_id": bundle.bundle_id,
        "harness_runs": [dict(r) for r in bundle.harness_runs],
    }
    rendered = {
        _MD: render_markdown(bundle) + "\n",
        _EVIDENCE_JSON: json.dumps(bundle.to_dict(), sort_keys=True, indent=2) + "\n",
        _RUNS_JSON: json.dumps(runs_payload, sort_keys=True, indent=2) + "\n",
        _README: _README_TEXT,
    }
    file_entries: list[dict[str, Any]] = []
    for name in _CONTENT_FILES:
        data = rendered[name].encode("utf-8")
        (output_dir / name).write_bytes(data)
        file_entries.append(_hashed_entry(name, data))

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "artifact": BUNDLE_ARTIFACT,
        "bundle_id": bundle.bundle_id,
        "generated_at": bundle.created_at,
        "advisory": bundle.advisory,
        "filters": dict(bundle.filters),
        "summary": dict(bundle.summary),
        "files": file_entries,
    }
    (output_dir / _MANIFEST).write_bytes(
        (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")
    )
    return manifest


def _inspect_dict(
    bundle_dir: Path,
    *,
    manifest_present: bool,
    bundle_id: str | None,
    bundle_schema_version: Any,
    schema_version_recognized: bool,
    runs_parse_ok: bool,
    file_count: int,
    harness_run_count: int,
    hash_mismatch_count: int,
    missing_file_count: int,
    unexpected_store_file_count: int,
    files: list[dict[str, Any]],
    notes: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact": INSPECTION_ARTIFACT,
        "bundle": {"path": str(bundle_dir), "bundle_id": bundle_id},
        "bundle_id": bundle_id,
        "bundle_schema_version": bundle_schema_version,
        "schema_version_recognized": schema_version_recognized,
        "manifest_present": manifest_present,
        "runs_parse_ok": runs_parse_ok,
        "file_count": file_count,
        "harness_run_count": harness_run_count,
        "hash_mismatch_count": hash_mismatch_count,
        "missing_file_count": missing_file_count,
        "unexpected_store_file_count": unexpected_store_file_count,
        "files": files,
        "notes": notes,
    }


def _count_unexpected_store_files(bundle_dir: Path, notes: list[str]) -> int:
    """Count mutable store files / a store directory mistakenly placed inside the bundle."""
    unexpected = 0
    for p in sorted(bundle_dir.rglob("*")):
        rel = p.relative_to(bundle_dir)
        if p.is_dir():
            if p.name == ".chimera-memory":
                unexpected += 1
                notes.append(f"unexpected store directory: {rel}")
            continue
        if p.name in _STORE_FILE_NAMES or p.suffix == ".jsonl":
            unexpected += 1
            notes.append(f"unexpected store file: {rel}")
    return unexpected


def inspect_harness_evidence_bundle(bundle_dir: Path) -> dict[str, Any]:
    """Read a bundle manifest and verify each file + the bundle shape. Read-only.

    Output is neutral counts (no pass/fail wording): file_count, harness_run_count,
    hash_mismatch_count, missing_file_count, unexpected_store_file_count, plus
    schema recognition and parse flags. Notes describe any discrepancies found.
    """
    bundle_dir = Path(bundle_dir)
    notes: list[str] = []
    manifest_path = bundle_dir / _MANIFEST
    if not manifest_path.exists():
        return _inspect_dict(
            bundle_dir, manifest_present=False, bundle_id=None, bundle_schema_version=None,
            schema_version_recognized=False, runs_parse_ok=False, file_count=0,
            harness_run_count=0, hash_mismatch_count=0, missing_file_count=1,
            unexpected_store_file_count=_count_unexpected_store_files(bundle_dir, notes),
            files=[], notes=[f"{_MANIFEST} not found", *notes],
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return _inspect_dict(
            bundle_dir, manifest_present=True, bundle_id=None, bundle_schema_version=None,
            schema_version_recognized=False, runs_parse_ok=False, file_count=0,
            harness_run_count=0, hash_mismatch_count=0, missing_file_count=0,
            unexpected_store_file_count=_count_unexpected_store_files(bundle_dir, notes),
            files=[], notes=[f"{_MANIFEST} is unreadable: {exc}", *notes],
        )

    hash_mismatch = 0
    missing = 0
    file_results: list[dict[str, Any]] = []
    for entry in manifest.get("files", []):
        name = entry.get("path", "")
        fp = bundle_dir / name
        exists = fp.exists()
        sha_ok = False
        if exists:
            data = fp.read_bytes()
            sha_ok = hashlib.sha256(data).hexdigest() == entry.get("sha256")
            if not sha_ok:
                hash_mismatch += 1
                notes.append(f"hash mismatch: {name}")
        else:
            missing += 1
            notes.append(f"missing file: {name}")
        file_results.append({"path": name, "exists": exists, "sha256_matches": sha_ok})

    bundle_schema = manifest.get("schema_version")
    schema_recognized = bundle_schema == SCHEMA_VERSION
    if not schema_recognized:
        notes.append(f"unrecognized schema_version: {bundle_schema!r}")

    bundle_id = manifest.get("bundle_id")
    run_count = 0
    runs_parse_ok = False
    ev_path = bundle_dir / _EVIDENCE_JSON
    if ev_path.exists():
        try:
            ev = json.loads(ev_path.read_text(encoding="utf-8"))
            run_count = len(ev.get("harness_runs", []))
            runs_parse_ok = True
            if bundle_id is None:
                bundle_id = ev.get("bundle_id")
        except (json.JSONDecodeError, OSError) as exc:
            notes.append(f"{_EVIDENCE_JSON} is unreadable: {exc}")
    else:
        notes.append(f"{_EVIDENCE_JSON} not found")

    unexpected = _count_unexpected_store_files(bundle_dir, notes)
    file_count = len(manifest.get("files", [])) + 1  # + manifest.json itself

    return _inspect_dict(
        bundle_dir, manifest_present=True, bundle_id=bundle_id,
        bundle_schema_version=bundle_schema, schema_version_recognized=schema_recognized,
        runs_parse_ok=runs_parse_ok, file_count=file_count, harness_run_count=run_count,
        hash_mismatch_count=hash_mismatch, missing_file_count=missing,
        unexpected_store_file_count=unexpected, files=file_results, notes=notes,
    )


def render_inspect_text(result: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Chimera Harness Evidence Bundle inspection")
    lines.append("")
    lines.append("Advisory only. Local bundle manifest check (file hashes/sizes).")
    lines.append("")
    lines.append(f"- bundle: {result['bundle']['path']}")
    lines.append(f"- bundle_id: {result.get('bundle_id')}")
    lines.append(f"- schema_version: {result.get('bundle_schema_version')}")
    lines.append(f"- schema_version_recognized: {result.get('schema_version_recognized')}")
    lines.append(f"- file_count: {result['file_count']}")
    lines.append(f"- harness_run_count: {result['harness_run_count']}")
    lines.append(f"- hash_mismatch_count: {result['hash_mismatch_count']}")
    lines.append(f"- missing_file_count: {result['missing_file_count']}")
    lines.append(f"- unexpected_store_file_count: {result['unexpected_store_file_count']}")
    if result["notes"]:
        lines.append("- notes:")
        for n in result["notes"]:
            lines.append(f"  - {n}")
    return "\n".join(lines)


def inspect_is_clean(result: dict[str, Any]) -> bool:
    """Mechanical check used for the CLI exit code: all counts zero + schema recognized."""
    return (
        result.get("manifest_present", False)
        and result.get("schema_version_recognized", False)
        and result.get("runs_parse_ok", False)
        and result["hash_mismatch_count"] == 0
        and result["missing_file_count"] == 0
        and result["unexpected_store_file_count"] == 0
    )


def load_evidence_dict(path: Path) -> dict[str, Any]:
    """Load the bundle dict from a bundle directory or a harness-evidence.json file."""
    path = Path(path)
    target = path / _EVIDENCE_JSON if path.is_dir() else path
    return json.loads(target.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _manifest_file_hashes(path: Path) -> dict[str, str]:
    """Map filename -> sha256 from a bundle's manifest.json (empty if absent)."""
    path = Path(path)
    manifest_path = path / _MANIFEST if path.is_dir() else None
    if manifest_path is None or not manifest_path.exists():
        return {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {
        str(e.get("path", "")): str(e.get("sha256", "")) for e in manifest.get("files", [])
    }


def _run_content_hash(run: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(run, sort_keys=True).encode("utf-8")).hexdigest()


def diff_harness_evidence_bundles(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    left_path: str,
    right_path: str,
    left_manifest: dict[str, str] | None = None,
    right_manifest: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Compute a read-only, deterministic diff between two evidence bundles.

    Reports added / removed run_ids, summary deltas (including redaction / truncation
    / artifact-ref deltas), changed manifest files, and — defensively, for append-only
    semantics — ``content_changed`` run_ids (same run_id, different content hash).
    """
    left_runs = {r["run_id"]: r for r in left.get("harness_runs", [])}
    right_runs = {r["run_id"]: r for r in right.get("harness_runs", [])}
    common = set(left_runs) & set(right_runs)
    content_changed = sorted(
        rid for rid in common
        if _run_content_hash(left_runs[rid]) != _run_content_hash(right_runs[rid])
    )

    ls = left.get("summary", {})
    rs = right.get("summary", {})
    summary_delta = {
        k: int(rs.get(k, 0)) - int(ls.get(k, 0)) for k in sorted(set(ls) | set(rs))
    }

    lm = left_manifest or {}
    rm = right_manifest or {}
    manifest_files = {
        "changed": sorted(p for p in (set(lm) & set(rm)) if lm[p] != rm[p]),
        "added": sorted(set(rm) - set(lm)),
        "removed": sorted(set(lm) - set(rm)),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "artifact": DIFF_ARTIFACT,
        "left": {"path": left_path, "bundle_id": left.get("bundle_id")},
        "right": {"path": right_path, "bundle_id": right.get("bundle_id")},
        "harness_runs": {
            "added": sorted(set(right_runs) - set(left_runs)),
            "removed": sorted(set(left_runs) - set(right_runs)),
            "content_changed": content_changed,
        },
        "summary_delta": summary_delta,
        "manifest_files": manifest_files,
    }


def diff_bundle_dirs(left_dir: Path, right_dir: Path) -> dict[str, Any]:
    """Load two bundle directories (or JSON files) and diff them. Read-only."""
    left_dir = Path(left_dir)
    right_dir = Path(right_dir)
    return diff_harness_evidence_bundles(
        load_evidence_dict(left_dir),
        load_evidence_dict(right_dir),
        left_path=str(left_dir),
        right_path=str(right_dir),
        left_manifest=_manifest_file_hashes(left_dir),
        right_manifest=_manifest_file_hashes(right_dir),
    )


def _delta(value: int) -> str:
    return f"+{value}" if value > 0 else str(value)


def render_diff_text(diff: dict[str, Any]) -> str:
    s = diff["summary_delta"]
    runs = diff["harness_runs"]
    mf = diff["manifest_files"]
    lines: list[str] = []
    lines.append("# Chimera Harness Evidence Bundle diff")
    lines.append("")
    lines.append(
        "Advisory only. Local bundle comparison; not a correctness, safety, approval, "
        "merge, or production-readiness signal."
    )
    lines.append("")
    lines.append(f"- left: {diff['left']['path']}")
    lines.append(f"- right: {diff['right']['path']}")
    lines.append("")
    lines.append("Run observations:")
    lines.append(f"- added: {', '.join(runs['added']) or '(none)'}")
    lines.append(f"- removed: {', '.join(runs['removed']) or '(none)'}")
    lines.append(f"- content_changed: {', '.join(runs['content_changed']) or '(none)'}")
    lines.append("")
    lines.append("Summary deltas:")
    lines.append(f"- harness runs: {_delta(s.get('harness_run_count', 0))}")
    lines.append(f"- executed: {_delta(s.get('executed_run_count', 0))}")
    lines.append(f"- recorded: {_delta(s.get('recorded_run_count', 0))}")
    lines.append(f"- redacted previews: {_delta(s.get('redacted_preview_count', 0))}")
    lines.append(f"- truncated outputs: {_delta(s.get('truncated_output_count', 0))}")
    lines.append(f"- artifact refs: {_delta(s.get('artifact_ref_count', 0))}")
    lines.append("")
    lines.append("Manifest files:")
    lines.append(f"- changed: {', '.join(mf['changed']) or '(none)'}")
    lines.append(f"- added: {', '.join(mf['added']) or '(none)'}")
    lines.append(f"- removed: {', '.join(mf['removed']) or '(none)'}")
    return "\n".join(lines)


def evidence_reference(bundle_dir: Path, *, as_path: str | None = None) -> dict[str, Any]:
    """Build a compact reference to an existing evidence bundle (path + manifest hash).

    Reads only the bundle's ``manifest.json``; does not copy the bundle. Used by the
    Work Packet bundle to reference an evidence bundle by relative path.
    """
    bundle_dir = Path(bundle_dir)
    manifest_path = bundle_dir / _MANIFEST
    if not manifest_path.exists():
        raise HarnessEvidenceError(
            f"no {_MANIFEST} in harness evidence dir: {bundle_dir}"
        )
    data = manifest_path.read_bytes()
    manifest = json.loads(data.decode("utf-8"))
    summary = manifest.get("summary", {})
    return {
        "path": as_path if as_path is not None else str(bundle_dir),
        "schema_version": manifest.get("schema_version"),
        "manifest_sha256": hashlib.sha256(data).hexdigest(),
        "harness_run_count": int(summary.get("harness_run_count", 0)),
        "bundle_id": manifest.get("bundle_id"),
    }


__all__ = [
    "ADVISORY",
    "BUNDLE_ARTIFACT",
    "DIFF_ARTIFACT",
    "INSPECTION_ARTIFACT",
    "SCHEMA_VERSION",
    "HarnessEvidenceBundle",
    "HarnessEvidenceError",
    "HarnessEvidenceRedactionSummary",
    "HarnessEvidenceSource",
    "build_harness_evidence_bundle",
    "diff_bundle_dirs",
    "diff_harness_evidence_bundles",
    "evidence_reference",
    "evidence_run",
    "inspect_harness_evidence_bundle",
    "inspect_is_clean",
    "load_evidence_dict",
    "render_diff_text",
    "render_inspect_text",
    "render_markdown",
    "write_harness_evidence_bundle",
]
