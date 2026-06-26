"""Consequence Observation Ledger v0 — a local, append-only, neutral inspection ledger.

A Consequence Observation is a *neutral inspection target* derived by an explicit
scan of existing local Memory / Harness evidence: a session with no attached
harness observations, a harness run that recorded a nonzero exit code, a run whose
output preview was truncated or redacted, or a reported check with no matching
harness run. Each observation records what was observed, which subject it attaches
to, suggested checks to inspect, and neutral evidence refs.

It is an **inspection-target ledger, not a gate**. It never says work is correct,
complete, safe, or appropriate to merge; it never interprets an exit code as a
verdict; it assigns no score, severity, or priority; it routes nothing and
executes nothing. Scanning is always explicit (`consequence scan`); reads write
nothing. The only write path is an explicit scan that appends to
``consequence_observations.jsonl`` (with deterministic de-duplication).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from chimera_memory.harness_run import filter_runs, read_harness_runs
from chimera_memory.storage import MemoryStore
from chimera_memory.work_brief import find_work_brief
from chimera_memory.work_session import (
    events_for_session,
    filter_sessions,
    sessions_for_store,
)

SCHEMA_VERSION = "consequence_observation.v1"
STORE_FILE = "consequence_observations.jsonl"

# Neutral observation kinds. v0 implements A/B/C/D/F; the remaining names are
# reserved for later scans and are documented as deferred.
OBSERVATION_KINDS = frozenset({
    "session_without_harness_runs",                 # rule A
    "harness_run_nonzero_exit_code_observed",       # rule B
    "harness_run_output_truncated",                 # rule C
    "harness_run_preview_redacted",                 # rule D
    "reported_check_without_matching_harness_run",  # rule F
})

SOURCE_KINDS = frozenset({
    "scan", "manual_record", "bundle_inspection", "work_packet_projection",
})

ADVISORY = (
    "local inspection-target ledger; not a correctness, safety, approval, merge, "
    "or production-readiness signal, and not a gate"
)


def _strs(value: Any) -> tuple[str, ...]:
    return tuple(str(v) for v in value if isinstance(v, str)) if isinstance(value, list) else ()


def _opt(value: Any) -> str | None:
    return str(value) if isinstance(value, str) else None


def _package_version() -> str:
    try:
        from importlib.metadata import version

        return version("chimera-memory")
    except Exception:  # noqa: BLE001 - version metadata is best-effort, never fatal
        return "unknown"


def make_observation_id(
    *,
    observation_kind: str,
    subject_type: str,
    subject_id: str,
    evidence_refs: tuple[str, ...],
    suggested_checks: tuple[str, ...],
) -> str:
    """Deterministic id from the dedupe key (schema + kind + subject + evidence + checks).

    Excludes ``created_at`` / ``source`` / ``note`` so re-scanning the same evidence
    produces the same id (and therefore de-duplicates).
    """
    key = "\x1f".join([
        SCHEMA_VERSION,
        observation_kind,
        f"{subject_type}:{subject_id}",
        "|".join(evidence_refs),
        "|".join(suggested_checks),
    ])
    return "co_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ConsequenceObservation:
    schema_version: str
    observation_id: str
    created_at: str
    source: dict[str, Any]
    subject: dict[str, str]
    observation_kind: str
    affected_paths: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    suggested_checks: tuple[str, ...]
    note: str
    tags: tuple[str, ...]
    work_session_id: str | None
    brief_id: str | None
    harness_run_ids: tuple[str, ...]
    bundle_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "observation_id": self.observation_id,
            "created_at": self.created_at,
            "source": dict(self.source),
            "subject": dict(self.subject),
            "observation_kind": self.observation_kind,
            "affected_paths": list(self.affected_paths),
            "evidence_refs": list(self.evidence_refs),
            "suggested_checks": list(self.suggested_checks),
            "note": self.note,
            "tags": list(self.tags),
            "work_session_id": self.work_session_id,
            "brief_id": self.brief_id,
            "harness_run_ids": list(self.harness_run_ids),
            "bundle_ids": list(self.bundle_ids),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ConsequenceObservation:
        subject = d.get("subject") or {}
        source = d.get("source") or {}
        return cls(
            schema_version=str(d.get("schema_version", SCHEMA_VERSION)),
            observation_id=str(d.get("observation_id", "")),
            created_at=str(d.get("created_at", "")),
            source=dict(source) if isinstance(source, dict) else {},
            subject={str(k): str(v) for k, v in subject.items()} if isinstance(subject, dict)
            else {},
            observation_kind=str(d.get("observation_kind", "")),
            affected_paths=_strs(d.get("affected_paths")),
            evidence_refs=_strs(d.get("evidence_refs")),
            suggested_checks=_strs(d.get("suggested_checks")),
            note=str(d.get("note", "")),
            tags=_strs(d.get("tags")),
            work_session_id=_opt(d.get("work_session_id")),
            brief_id=_opt(d.get("brief_id")),
            harness_run_ids=_strs(d.get("harness_run_ids")),
            bundle_ids=_strs(d.get("bundle_ids")),
        )


def _build(
    *,
    observation_kind: str,
    subject_type: str,
    subject_id: str,
    created_at: str,
    source: dict[str, Any],
    note: str,
    affected_paths: tuple[str, ...] = (),
    evidence_refs: tuple[str, ...] = (),
    suggested_checks: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    work_session_id: str | None = None,
    brief_id: str | None = None,
    harness_run_ids: tuple[str, ...] = (),
    bundle_ids: tuple[str, ...] = (),
) -> ConsequenceObservation:
    return ConsequenceObservation(
        schema_version=SCHEMA_VERSION,
        observation_id=make_observation_id(
            observation_kind=observation_kind,
            subject_type=subject_type,
            subject_id=subject_id,
            evidence_refs=evidence_refs,
            suggested_checks=suggested_checks,
        ),
        created_at=created_at,
        source=source,
        subject={"type": subject_type, "id": subject_id},
        observation_kind=observation_kind,
        affected_paths=affected_paths,
        evidence_refs=evidence_refs,
        suggested_checks=suggested_checks,
        note=note,
        tags=tags,
        work_session_id=work_session_id,
        brief_id=brief_id,
        harness_run_ids=harness_run_ids,
        bundle_ids=bundle_ids,
    )


def make_scan_id(*, generated_at: str, work_session_id: str | None,
                 brief_id: str | None, tag: str | None) -> str:
    key = "\x1f".join([generated_at, work_session_id or "", brief_id or "", tag or ""])
    return "scan_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def scan_observations(
    store: MemoryStore,
    *,
    generated_at: str,
    work_session_id: str | None = None,
    brief_id: str | None = None,
    tag: str | None = None,
    limit: int | None = None,
) -> list[ConsequenceObservation]:
    """Scan existing Memory/Harness evidence and return candidate observations.

    Read-only: reads the work-session, work-brief, and harness ledgers and writes
    nothing. Exact-match filters combine with AND; ``limit`` caps the candidate
    list (deterministic rule order). De-duplicated within the batch by observation
    id; callers persist with :func:`append_new_observations`.
    """
    source = {
        "kind": "scan",
        "scan_id": make_scan_id(
            generated_at=generated_at, work_session_id=work_session_id,
            brief_id=brief_id, tag=tag,
        ),
        "package": "chimera-memory",
        "version": _package_version(),
    }

    sessions = filter_sessions(sessions_for_store(store), tag=tag)
    if work_session_id is not None:
        sessions = [s for s in sessions if s.session_id == work_session_id]
    if brief_id is not None:
        sessions = [s for s in sessions if s.brief_id == brief_id]

    all_runs = read_harness_runs(store)
    selected_runs = filter_runs(
        all_runs, work_session_id=work_session_id, brief_id=brief_id, tag=tag
    )

    out: list[ConsequenceObservation] = []

    # Rule A — session_without_harness_runs
    for s in sessions:
        if filter_runs(all_runs, work_session_id=s.session_id):
            continue
        brief = find_work_brief(store, s.brief_id) if s.brief_id else None
        out.append(_build(
            observation_kind="session_without_harness_runs",
            subject_type="work_session", subject_id=s.session_id,
            created_at=generated_at, source=source,
            note="No harness run observations are linked to this work session.",
            affected_paths=tuple(brief.scope_paths) if brief else (),
            suggested_checks=tuple(brief.checks) if brief else (),
            tags=tuple(s.tags), work_session_id=s.session_id, brief_id=s.brief_id,
        ))

    # Rules B / C / D — per harness run
    for r in selected_runs:
        common: dict[str, Any] = {
            "subject_type": "harness_run", "subject_id": r.run_id,
            "created_at": generated_at, "source": source,
            "evidence_refs": (r.run_id,), "harness_run_ids": (r.run_id,),
            "tags": tuple(r.tags), "work_session_id": r.work_session_id,
            "brief_id": r.brief_id,
        }
        if r.exit_code is not None and r.exit_code != 0:
            out.append(_build(
                observation_kind="harness_run_nonzero_exit_code_observed",
                note="Harness run recorded a nonzero exit code.",
                suggested_checks=(r.check_label,) if r.check_label else (), **common,
            ))
        if r.output_truncated:
            out.append(_build(
                observation_kind="harness_run_output_truncated",
                note="Harness run output preview was truncated.", **common,
            ))
        if r.redaction_applied:
            out.append(_build(
                observation_kind="harness_run_preview_redacted",
                note="Harness run preview had redaction applied.", **common,
            ))

    # Rule F — reported_check_without_matching_harness_run
    for s in sessions:
        reported = [
            e.check for e in events_for_session(store, s.session_id)
            if e.event_kind == "check_reported" and e.check
        ]
        if not reported:
            continue
        session_runs = filter_runs(all_runs, work_session_id=s.session_id)
        for check in reported:
            if _check_has_matching_run(check, session_runs):
                continue
            out.append(_build(
                observation_kind="reported_check_without_matching_harness_run",
                subject_type="work_session", subject_id=s.session_id,
                created_at=generated_at, source=source,
                note="A reported check has no matching harness run observation.",
                suggested_checks=(check,), tags=tuple(s.tags),
                work_session_id=s.session_id, brief_id=s.brief_id,
            ))

    deduped = _dedupe(out)
    return deduped[:limit] if limit is not None and limit >= 0 else deduped


def _check_has_matching_run(check: str, runs: list[Any]) -> bool:
    """Deterministic, literal match: exact check_label, or substring either direction."""
    for r in runs:
        if r.check_label and r.check_label == check:
            return True
        if check and r.command and check in r.command:
            return True
        if r.command and r.command and r.command in check:
            return True
    return False


def _dedupe(observations: list[ConsequenceObservation]) -> list[ConsequenceObservation]:
    seen: set[str] = set()
    out: list[ConsequenceObservation] = []
    for obs in observations:
        if obs.observation_id in seen:
            continue
        seen.add(obs.observation_id)
        out.append(obs)
    return out


def read_consequence_observations(store: MemoryStore) -> list[ConsequenceObservation]:
    """Read all observations (stored order). Read-only; never creates a store."""
    return [ConsequenceObservation.from_dict(d) for d in store.read_jsonl(STORE_FILE)]


def existing_observation_ids(store: MemoryStore) -> set[str]:
    return {o.observation_id for o in read_consequence_observations(store)}


def append_new_observations(
    store: MemoryStore, observations: list[ConsequenceObservation]
) -> list[ConsequenceObservation]:
    """Append only observations whose id is not already present. The only write path.

    De-duplicates against the existing store and within the batch. Returns the
    observations actually appended.
    """
    have = existing_observation_ids(store)
    appended: list[ConsequenceObservation] = []
    for obs in observations:
        if obs.observation_id in have:
            continue
        store.ensure()
        store.append_jsonl(STORE_FILE, obs.to_dict())
        have.add(obs.observation_id)
        appended.append(obs)
    return appended


def filter_observations(
    observations: list[ConsequenceObservation],
    *,
    work_session_id: str | None = None,
    brief_id: str | None = None,
    kind: str | None = None,
    tag: str | None = None,
) -> list[ConsequenceObservation]:
    """Exact-match filter (AND). No fuzzy matching, no ranking."""
    return [
        o
        for o in observations
        if (work_session_id is None or o.work_session_id == work_session_id)
        and (brief_id is None or o.brief_id == brief_id)
        and (kind is None or o.observation_kind == kind)
        and (tag is None or tag in o.tags)
    ]


def find_observation(
    store: MemoryStore, observation_id: str
) -> ConsequenceObservation | None:
    for o in read_consequence_observations(store):
        if o.observation_id == observation_id:
            return o
    return None


def compact_observation(obs: ConsequenceObservation) -> dict[str, Any]:
    """Compact observation reference for closeout / rollup / work-packet surfaces."""
    return {
        "observation_id": obs.observation_id,
        "observation_kind": obs.observation_kind,
        "subject": dict(obs.subject),
        "suggested_checks": list(obs.suggested_checks),
        "note": obs.note,
        "work_session_id": obs.work_session_id,
        "brief_id": obs.brief_id,
    }


def observations_for_session(
    store: MemoryStore, session_id: str
) -> list[dict[str, Any]]:
    """Compact, read-only observations attached to one work session."""
    return [
        compact_observation(o)
        for o in filter_observations(
            read_consequence_observations(store), work_session_id=session_id
        )
    ]


def render_observation_markdown(obs: ConsequenceObservation) -> str:
    """Render one observation to neutral markdown. Presentation only; no verdict."""
    lines = [
        "# Chimera Consequence Observation",
        "",
        f"Advisory only. {ADVISORY}.",
        "",
        f"- observation_id: {obs.observation_id}",
        f"- observation_kind: {obs.observation_kind}",
        f"- subject: {obs.subject.get('type')} {obs.subject.get('id')}",
        f"- created_at: {obs.created_at}",
        f"- work_session_id: {obs.work_session_id or '(none)'}",
        f"- brief_id: {obs.brief_id or '(none)'}",
    ]
    if obs.evidence_refs:
        lines.append("- evidence refs: " + ", ".join(obs.evidence_refs))
    if obs.affected_paths:
        lines.append("- affected paths: " + ", ".join(obs.affected_paths))
    lines.append("")
    lines.append("## Suggested checks")
    if obs.suggested_checks:
        lines.extend(f"- {c}" for c in obs.suggested_checks)
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Note")
    lines.append(obs.note or "(none)")
    return "\n".join(lines)


def render_observations_markdown(observations: list[ConsequenceObservation]) -> str:
    """Render a list of observations to neutral markdown. Presentation only."""
    lines = [
        "# Chimera Consequence Observations",
        "",
        f"Advisory only. {ADVISORY}.",
        "",
        f"- observations: {len(observations)}",
        "",
    ]
    if not observations:
        lines.append("- (none)")
        return "\n".join(lines)
    for o in observations:
        subject = f"{o.subject.get('type')} {o.subject.get('id')}"
        lines.append(f"- [{o.observation_kind}] {subject}")
        lines.append(f"  Note: {o.note}")
        if o.suggested_checks:
            lines.append("  Suggested checks: " + ", ".join(o.suggested_checks))
    return "\n".join(lines)


__all__ = [
    "ADVISORY",
    "OBSERVATION_KINDS",
    "SCHEMA_VERSION",
    "SOURCE_KINDS",
    "STORE_FILE",
    "ConsequenceObservation",
    "append_new_observations",
    "compact_observation",
    "existing_observation_ids",
    "filter_observations",
    "find_observation",
    "make_observation_id",
    "observations_for_session",
    "read_consequence_observations",
    "render_observation_markdown",
    "render_observations_markdown",
    "scan_observations",
]
