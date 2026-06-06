"""Chimera Memory Preflight — read-only advisory report before starting work.

Retrieves historical failures, repair loops, and recommended verification
commands relevant to a given scope. Supports inference from git-changed files
for CI/PR contexts. Advisory only — no routing, no scoring,
no autonomy decisions, no M2B.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from chimera_memory.storage import MemoryStore

SCHEMA_VERSION = 2

# ---------------------------------------------------------------------------
# Scope inference rules
# ---------------------------------------------------------------------------

# Path prefix → inferred scope path
_SCOPE_PREFIX_MAP: list[tuple[str, str]] = [
    ("packages/chimera-memory/src", "packages/chimera-memory"),
    ("packages/chimera-memory/tests", "packages/chimera-memory"),
    ("packages/chimera-memory/", "packages/chimera-memory"),
    ("packages/chimera-memory-types/src", "packages/chimera-memory-types"),
    ("packages/chimera-memory-types/", "packages/chimera-memory-types"),
    ("docs/", "docs"),
    ("apps/", "apps"),
    ("tools/", "tools"),
    ("scripts/", "scripts"),
]

# Scope → recommended verification commands
_SCOPE_CHECKS: dict[str, list[str]] = {
    "packages/chimera-memory": [
        "pytest packages/chimera-memory/tests -m 'not slow'",
        "mypy packages/chimera-memory/src",
        "ruff check packages/chimera-memory/src packages/chimera-memory/tests",
        "chimera-memory verify",
    ],
    "packages/chimera-memory-types": [
        "mypy packages/chimera-memory-types/src",
        "ruff check packages/chimera-memory-types/src",
    ],
}
_GENERIC_CHECKS = [
    "chimera-memory verify",
    "chimera-memory status",
    "chimera-memory m2b-readiness",
]

# ---------------------------------------------------------------------------
# Intelligence typed structures
# ---------------------------------------------------------------------------

@dataclass
class KnownFailure:
    """An enriched historical failure relevant to the current scope."""
    claim_id: str
    command: str
    scope_paths: list[str]
    effective_failure_origin: str
    repair_loop_id: str | None
    repair_status: str  # fixed_same_scope | later_regression_validated | classified_errata | open
    lesson: str
    witness_excerpt: str | None
    scope_match_reason: str  # exact | parent | child

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "command": self.command,
            "scope_paths": self.scope_paths,
            "effective_failure_origin": self.effective_failure_origin,
            "repair_loop_id": self.repair_loop_id,
            "repair_status": self.repair_status,
            "lesson": self.lesson,
            "witness_excerpt": self.witness_excerpt,
            "scope_match_reason": self.scope_match_reason,
        }


@dataclass
class RepairLoopLesson:
    """A synthesized lesson from a repair loop that touched the current scope."""
    repair_loop_id: str
    baseline_failures: int
    fix_validations: int
    status: str  # fixed | has_validations | open
    lesson: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "repair_loop_id": self.repair_loop_id,
            "baseline_failures": self.baseline_failures,
            "fix_validations": self.fix_validations,
            "status": self.status,
            "lesson": self.lesson,
        }


@dataclass
class HygieneWarning:
    """A recurring invocation_artifact pattern — not a product defect."""
    pattern: str
    count: int
    lesson: str
    example_claim_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern": self.pattern,
            "count": self.count,
            "lesson": self.lesson,
            "example_claim_id": self.example_claim_id,
        }


@dataclass
class FailureSignature:
    """Stable fingerprint of a recurring failure pattern."""
    command_family: str
    scope: str
    exit_code: int | None
    count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_family": self.command_family,
            "scope": self.scope,
            "exit_code": self.exit_code,
            "count": self.count,
        }

_GENERIC_CHECKS = [
    "Run focused tests for the changed scope",
    "Run type check (mypy) on changed source",
    "Run lint (ruff) on changed source",
    "chimera-memory verify  # check ledger integrity",
]

# ---------------------------------------------------------------------------
# Git changed-file detection
# ---------------------------------------------------------------------------


def infer_scopes_from_git(
    root: Path | str | None = None,
    *,
    include_untracked: bool = False,
) -> tuple[list[str], list[str]]:
    """Inspect git working-tree changes and return (changed_files, inferred_scope_paths).

    Reads staged + unstaged tracked changes. Does not stage, commit, or mutate git.
    Handles modified, added, deleted, renamed (R), copied (C) files.
    Paths with spaces are handled via git --porcelain quoting.

    Args:
        root: root directory (defaults to cwd)
        include_untracked: if True, include untracked (??) files

    Returns:
        changed_files: list of file paths
        inferred_scope_paths: deduplicated scope paths
    """
    import subprocess

    root_path = Path(root) if root is not None else Path.cwd()

    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root_path, check=False, text=True, capture_output=True,
        )
    except FileNotFoundError:
        return [], []  # git not installed

    if result.returncode != 0:
        return [], []  # not a git repo or other error

    changed: list[str] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        status = line[:2]
        if status.startswith("??"):
            if include_untracked:
                path = line[3:].strip().strip('"')
                if path:
                    changed.append(path)
            continue
        # Renamed: "R  old -> new" — take new path
        if " -> " in line:
            path = line.split(" -> ", 1)[1].strip().strip('"')
        else:
            path = line[3:].strip()
            # Remove git quoting for paths with spaces
            if path.startswith('"') and path.endswith('"'):
                path = path[1:-1]
        if path:
            changed.append(path)

    scopes: list[str] = []
    seen: set[str] = set()
    for path in changed:
        for prefix, scope in _SCOPE_PREFIX_MAP:
            if path.startswith(prefix):
                if scope not in seen:
                    seen.add(scope)
                    scopes.append(scope)
                break
        else:
            top = path.split("/")[0] if "/" in path else path
            if top and top not in seen and top not in (".git", ""):
                seen.add(top)
                scopes.append(top)

    return changed, scopes

def recommended_checks_for_scopes(scopes: list[str]) -> list[str]:
    """Return recommended check commands for the given inferred scopes.

    Returns _GENERIC_CHECKS if scopes is empty (no scope detected).
    """
    if not scopes:
        return list(_GENERIC_CHECKS)

    checks: list[str] = []
    for scope in scopes:
        matched = False
        for key, cmds in _SCOPE_CHECKS.items():
            # Exact key match
            if scope == key:
                for cmd in cmds:
                    if cmd not in checks:
                        checks.append(cmd)
                matched = True
                break
            # scope is a sub-directory of key (key is a directory prefix)
            if key.endswith("/") and scope.startswith(key):
                for cmd in cmds:
                    if cmd not in checks:
                        checks.append(cmd)
                matched = True
                break
        if not matched:
            # Unknown scope — use generic checks but warn
            for cmd in _GENERIC_CHECKS:
                if cmd not in checks:
                    checks.append(cmd)
    return checks


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------


@dataclass
class PreflightReport:
    schema_version: int = SCHEMA_VERSION
    source: str = "explicit_scope"  # explicit_scope | git_changes | mixed | none
    filters: dict[str, Any] = field(default_factory=dict)
    changed_files: list[str] = field(default_factory=list)
    inferred_scope_paths: list[str] = field(default_factory=list)
    matching_claim_count: int = 0
    recent_failures: list[dict[str, Any]] = field(default_factory=list)
    repair_loops: list[dict[str, Any]] = field(default_factory=list)
    recommended_checks: list[str] = field(default_factory=list)
    dq_caveats: list[str] = field(default_factory=list)
    m2b_readiness_level: str = "unknown"
    notes: dict[str, Any] = field(default_factory=dict)
    # v0.6 intelligence fields
    known_failures: list[KnownFailure] = field(default_factory=list)
    repair_loop_lessons: list[RepairLoopLesson] = field(default_factory=list)
    hygiene_warnings: list[HygieneWarning] = field(default_factory=list)
    failure_signatures: list[FailureSignature] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "filters": self.filters,
            "changed_files": self.changed_files,
            "inferred_scope_paths": self.inferred_scope_paths,
            "matching_claim_count": self.matching_claim_count,
            "recent_failures": self.recent_failures,
            "repair_loops": self.repair_loops,
            "recommended_checks": self.recommended_checks,
            "dq_caveats": self.dq_caveats,
            "m2b_readiness_level": self.m2b_readiness_level,
            "notes": self.notes,
            # v0.6
            "known_failures": [kf.to_dict() for kf in self.known_failures],
            "repair_loop_lessons": [rl.to_dict() for rl in self.repair_loop_lessons],
            "hygiene_warnings": [hw.to_dict() for hw in self.hygiene_warnings],
            "failure_signatures": [fs.to_dict() for fs in self.failure_signatures],
            "preflight_intelligence_note": (
                "Historical failure context only. Not M2B scoring, model ranking, "
                "routing, or statistical proof."
            ),
        }


def _scope_match_reason(
    claim_scope_paths: list[str] | None, filter_scopes: list[str]
) -> str | None:
    """Return match reason (exact/parent/child) or None if no match.

    Uses path-boundary matching to avoid chimera-memory matching chimera-memory-types.
    """
    if not filter_scopes or not claim_scope_paths:
        return None
    for fs in filter_scopes:
        fs_norm = fs.rstrip("/")
        for sp in claim_scope_paths:
            sp_norm = str(sp).rstrip("/")
            if sp_norm == fs_norm:
                return "exact"
            # parent: filter scope is parent of claim scope (fs is prefix of sp at boundary)
            if sp_norm.startswith(fs_norm + "/"):
                return "parent"
            # child: claim scope is parent of filter scope
            if fs_norm.startswith(sp_norm + "/"):
                return "child"
    return None


def _scope_matches(claim_scope_paths: list[str] | None, filter_scopes: list[str]) -> bool:
    """True if any filter scope boundary-matches any stored scope path."""
    if not filter_scopes:
        return True
    if not claim_scope_paths:
        return False
    return _scope_match_reason(claim_scope_paths, filter_scopes) is not None


def _lesson_text(command: str, effective_failure_origin: str, witness: str | None) -> str:
    """Return a conservative observed-pattern lesson string."""
    cmd_lower = command.lower()
    w = (witness or "").lower()

    if "mypy" in cmd_lower:
        return (
            "Observed pattern: type checks failed in this scope before. "
            "Re-run mypy after changing typed helpers, Optional fields, or report shapes."
        )
    if "pytest" in cmd_lower and effective_failure_origin == "invocation_artifact":
        return (
            "Observed hygiene issue: pytest -m expressions failed when passed through "
            "shell variable expansion. Run marker expressions directly."
        )
    if "pytest" in cmd_lower:
        return (
            "Observed pattern: tests failed in this scope before. "
            "Re-run the full test suite before closing the task."
        )
    if "m2b-readiness" in cmd_lower or "m2b_readiness" in cmd_lower:
        return (
            "Observed pattern: m2b-readiness output shape changed before. "
            "Check dq_cohort_summary, effective_group_summaries, and blocker output after changes."
        )
    if "preflight" in cmd_lower:
        return (
            "Observed pattern: preflight scope inference and report formatting are "
            "sensitive to path-boundary matching and optional fields."
        )
    if "ruff" in cmd_lower:
        return (
            "Observed pattern: ruff lint failed in this scope before. "
            "Run ruff check after adding new imports or refactoring long lines."
        )
    if "doctor" in cmd_lower:
        return (
            "Observed pattern: chimera-memory doctor had a count/state issue in this scope. "
            "Check errata-aware read models after ledger format changes."
        )
    if "quoting" in w or "not slow" in w or "invalid argument" in w.lower():
        return (
            "Observed hygiene issue: command invocation failed due to argument quoting or "
            "missing dependencies. Check tool availability and invocation syntax."
        )
    return (
        "Observed pattern: this command failed in this scope before. "
        "Re-run the recommended checks before closing the task."
    )


def _repair_status(
    failure_claim_id: str,
    repair_loop_id: str | None,
    errata_applied: bool,
    all_claims_by_loop: dict[str, list[Any]],
) -> str:
    """Determine repair status for a failure claim."""
    if errata_applied:
        return "classified_errata"
    if not repair_loop_id:
        return "open"
    loop_claims = all_claims_by_loop.get(repair_loop_id, [])
    for c in loop_claims:
        m = c.metadata or {}
        ph = str(m.get("repair_phase") or "")
        from chimera_memory_types.knowledge import ClaimStatus
        if c.claim_status == ClaimStatus.VALIDATED:
            if ph == "same_scope_after_fix":
                return "fixed_same_scope"
            if ph in ("regression_check", "baseline"):
                return "later_regression_validated"
    return "open"


def build_preflight(
    store: MemoryStore,
    *,
    scope_paths: list[str] | None = None,
    from_git: bool = False,
    include_untracked: bool = False,
    task_type: str | None = None,
    agent_id: str | None = None,
    model_version: str | None = None,
    failure_origin: str | None = None,
    verification_scope: str | None = None,
    limit: int = 10,
) -> PreflightReport:
    """Build a read-only preflight advisory report. No routing, no autonomy."""
    from chimera_memory.errata import effective_failure_origin, load_errata
    from chimera_memory.m2b_readiness import compute_m2b_readiness
    from chimera_memory.query import build_claim_read_model
    from chimera_memory.redaction import redact
    from chimera_memory_types.knowledge import ClaimStatus

    rm = build_claim_read_model(store)
    errata_map = load_errata(store.memory_dir)
    scopes = scope_paths or []

    # --- Determine source and infer scopes from git if requested ---
    changed_files: list[str] = []
    inferred: list[str] = []

    if from_git:
        changed_files, inferred = infer_scopes_from_git(
            store.memory_dir, include_untracked=include_untracked
        )
        # If explicit --scope-path also provided, merge with git-inferred
        if scopes:
            # Merge: explicit scope still applies but git scopes supplement
            for s in inferred:
                if s not in scopes:
                    scopes.append(s)
            source = "mixed"
        elif inferred:
            scopes = inferred
            source = "git_changes"
        else:
            source = "none"  # git available but no tracked changes
            scopes = []
    else:
        source = "explicit_scope" if scopes else "none"

    filters: dict[str, Any] = {}
    if scopes:
        filters["scope_paths"] = scopes
    if task_type:
        filters["task_type"] = task_type
    if agent_id:
        filters["agent_id"] = agent_id
    if model_version:
        filters["model_version"] = model_version
    if failure_origin:
        filters["failure_origin"] = failure_origin
    if verification_scope:
        filters["verification_scope"] = verification_scope

    # Filter settled claims
    candidates = rm.clean_claims
    if scopes:
        candidates = [
            c for c in candidates
            if _scope_matches((c.metadata or {}).get("scope_paths"), scopes)
        ]
    if task_type:
        candidates = [c for c in candidates if (c.metadata or {}).get("task_type") == task_type]
    if agent_id:
        candidates = [c for c in candidates if (c.metadata or {}).get("agent_id") == agent_id]
    if model_version:
        candidates = [
            c for c in candidates if (c.metadata or {}).get("model_version") == model_version
        ]
    if failure_origin:
        candidates = [
            c for c in candidates
            if effective_failure_origin(c, errata_map) == failure_origin
        ]
    if verification_scope:
        candidates = [
            c for c in candidates
            if (c.metadata or {}).get("verification_scope") == verification_scope
        ]

    # Recent failures (CONTRADICTED, effective origin not invocation_artifact)
    failures = [
        c for c in candidates
        if c.claim_status == ClaimStatus.CONTRADICTED
    ]
    failure_dicts = []
    for c in failures[-limit:]:
        m = c.metadata or {}
        eff_fo = effective_failure_origin(c, errata_map)
        evt_meta: dict[str, Any] = {}
        if c.settlement and c.settlement.events:
            evt_meta = c.settlement.events[-1].metadata or {}
        wrapped = evt_meta.get("wrapped_args") or []
        cmd = redact(" ".join(str(a) for a in wrapped)) if wrapped else c.title
        witness = evt_meta.get("stderr_excerpt") or evt_meta.get("stdout_excerpt") or ""
        failure_dicts.append({
            "claim_id": c.claim_id[:12],
            "command": cmd[:80],
            "effective_failure_origin": eff_fo,
            "verification_scope": m.get("verification_scope"),
            "repair_loop_id": m.get("repair_loop_id"),
            "repair_phase": m.get("repair_phase"),
            "errata_applied": eff_fo != m.get("failure_origin"),
            "witness": redact(str(witness).strip()[:120]) if witness else None,
        })

    # Repair loops from matching claims
    loops: dict[str, dict[str, int]] = {}
    for c in candidates:
        m = c.metadata or {}
        rl = m.get("repair_loop_id")
        if rl:
            loops.setdefault(str(rl), {"baseline": 0, "same_scope_after_fix": 0, "other": 0})
            ph = str(m.get("repair_phase") or "other")
            bucket = ph if ph in ("baseline", "same_scope_after_fix") else "other"
            loops[str(rl)][bucket] += 1
    loop_dicts = [
        {
            "repair_loop_id": lid,
            "baseline_count": lv["baseline"],
            "same_scope_after_fix_count": lv["same_scope_after_fix"],
            "complete": lv["baseline"] >= 1 and lv["same_scope_after_fix"] >= 1,
        }
        for lid, lv in sorted(loops.items())
    ]

    # Recommended checks from inferred scopes
    if scopes:
        checks = recommended_checks_for_scopes(scopes)
    else:
        checks = list(_GENERIC_CHECKS)  # no scope → generic advisory

    # DQ caveats
    caveats = [
        "Preflight is advisory only. No routing, autonomy, or statistical confidence implied.",
        "Evidence filtered by scope_paths — claims without scope_paths metadata may be excluded.",
    ]
    if errata_map:
        caveats.append(
            f"{len(errata_map)} errata correction(s) applied to effective failure_origin."
        )
    if not candidates:
        caveats.append("No matching evidence found. Run baseline verification to build evidence.")

    # M2B readiness level
    try:
        m2b_report = compute_m2b_readiness(store)
        m2b_level = m2b_report.readiness_level
    except Exception:
        m2b_level = "unknown"

    # ── v0.6: Build intelligence structures ──────────────────────────────────

    # Index all scope-matching claims by repair_loop_id for repair status lookup
    all_by_loop: dict[str, list[Any]] = {}
    for c in candidates:
        rl = (c.metadata or {}).get("repair_loop_id")
        if rl:
            all_by_loop.setdefault(str(rl), []).append(c)

    # known_failures: organic_real + controlled_real, max 10 most recent
    _PRODUCT_ORIGINS = {"organic_real", "controlled_real"}
    _HYGIENE_ORIGINS = {"invocation_artifact"}
    _EXCLUDED_ORIGINS = {"test_first_contract", "synthetic", None}

    scope_failures_all = [
        c for c in candidates
        if c.claim_status == ClaimStatus.CONTRADICTED
    ]

    known_failures: list[KnownFailure] = []
    hygiene_raw: list[tuple[str, str, str]] = []  # (pattern, claim_id, cmd)

    for c in reversed(scope_failures_all[-50:]):  # most recent first, bounded
        m = c.metadata or {}
        eff_fo = effective_failure_origin(c, errata_map)
        if eff_fo in _EXCLUDED_ORIGINS:
            continue
        intel_evt: dict[str, Any] = {}
        if c.settlement and c.settlement.events:
            intel_evt = c.settlement.events[-1].metadata or {}
        wrapped = intel_evt.get("wrapped_args") or []
        cmd = redact(" ".join(str(a) for a in wrapped)) if wrapped else c.title
        witness = intel_evt.get("stderr_excerpt") or intel_evt.get("stdout_excerpt") or ""
        witness_r = redact(str(witness).strip()[:120]) if witness else None
        sp = list(m.get("scope_paths") or [])
        match_reason = _scope_match_reason(sp or None, scopes) or "parent"

        if eff_fo in _PRODUCT_ORIGINS and len(known_failures) < 10:
            errata_applied = eff_fo != m.get("failure_origin")
            status = _repair_status(
                c.claim_id, m.get("repair_loop_id"), errata_applied, all_by_loop
            )
            known_failures.append(KnownFailure(
                claim_id=c.claim_id[:12],
                command=cmd[:80],
                scope_paths=sp,
                effective_failure_origin=str(eff_fo),
                repair_loop_id=m.get("repair_loop_id"),
                repair_status=status,
                lesson=_lesson_text(cmd, str(eff_fo), witness_r),
                witness_excerpt=witness_r,
                scope_match_reason=match_reason,
            ))
        elif eff_fo in _HYGIENE_ORIGINS:
            # group by command family for hygiene summary
            fam = cmd.split()[0] if cmd.split() else "unknown"
            hygiene_raw.append((fam, c.claim_id[:12], cmd[:60]))

    # hygiene_warnings: group by command family, max 5
    hygiene_groups: dict[str, list[tuple[str, str]]] = {}
    for fam, cid, cmd in hygiene_raw:
        hygiene_groups.setdefault(fam, []).append((cid, cmd))
    hygiene_warnings: list[HygieneWarning] = []
    for fam, items in list(hygiene_groups.items())[:5]:
        hygiene_warnings.append(HygieneWarning(
            pattern=fam,
            count=len(items),
            lesson=_lesson_text(fam, "invocation_artifact", None),
            example_claim_id=items[0][0],
        ))

    # repair_loop_lessons: from loops with scope-matching claims, max 5
    loop_lessons: list[RepairLoopLesson] = []
    for lid, loop_claims in sorted(all_by_loop.items()):
        base = sum(
            1 for c in loop_claims
            if c.claim_status == ClaimStatus.CONTRADICTED
            and str((c.metadata or {}).get("repair_phase") or "") in (
                "baseline", "repair_attempt"
            )
        )
        fix_v = sum(
            1 for c in loop_claims
            if c.claim_status == ClaimStatus.VALIDATED
            and str((c.metadata or {}).get("repair_phase") or "") in (
                "same_scope_after_fix", "regression_check"
            )
        )
        if base == 0 and fix_v == 0:
            continue
        if fix_v >= 1 and base >= 1:
            status = "fixed"
            lesson = (
                f"Loop had {base} failure(s) and {fix_v} fix validation(s). "
                f"Review the loop's repair phases for patterns."
            )
        elif fix_v >= 1:
            status = "has_validations"
            lesson = f"Loop has {fix_v} validation(s) with no recorded baseline failure."
        else:
            status = "open"
            lesson = f"Loop has {base} baseline failure(s) with no fix validation yet."
        loop_lessons.append(RepairLoopLesson(
            repair_loop_id=lid,
            baseline_failures=base,
            fix_validations=fix_v,
            status=status,
            lesson=lesson,
        ))
    # sort: fixed first
    loop_lessons.sort(key=lambda ln: (0 if ln.status == "fixed" else 1, ln.repair_loop_id))
    loop_lessons = loop_lessons[:5]

    # failure_signatures: group scope-matching product failures by (family, scope, exit_code)
    sig_groups: dict[tuple[str, str, int | None], int] = {}
    for kf in known_failures:
        fam = kf.command.split()[0] if kf.command.split() else "unknown"
        sc = kf.scope_paths[0] if kf.scope_paths else "unknown"
        # exit_code not in known_failures — use None
        key = (fam, sc, None)
        sig_groups[key] = sig_groups.get(key, 0) + 1
    failure_signatures = [
        FailureSignature(
            command_family=k[0], scope=k[1], exit_code=k[2], count=v
        )
        for k, v in sorted(sig_groups.items(), key=lambda x: -x[1])
    ][:10]

    return PreflightReport(
        source=source,
        filters=filters,
        changed_files=changed_files[:50],  # cap for readability
        inferred_scope_paths=inferred,
        matching_claim_count=len(candidates),
        recent_failures=failure_dicts,
        repair_loops=loop_dicts,
        recommended_checks=checks,
        dq_caveats=caveats,
        m2b_readiness_level=m2b_level,
        notes={
            "not_routing": "This is not a routing or gating decision.",
            "not_m2b": "M2B drift scoring is not built. Descriptive evidence retrieval only.",
            "advisory": "Review evidence and recommended checks before starting work.",
        },
        known_failures=known_failures,
        repair_loop_lessons=loop_lessons,
        hygiene_warnings=hygiene_warnings,
        failure_signatures=failure_signatures,
    )


def format_preflight_text(report: PreflightReport) -> str:
    lines = [
        "Chimera Memory Preflight Advisory",
        "",
        "Preflight is advisory only. No routing, autonomy, or statistical confidence implied.",
        "",
        f"Source:            {report.source}",
        f"Matching claims:   {report.matching_claim_count}",
        f"M2B readiness:     {report.m2b_readiness_level}",
        "",
    ]

    # Changed-scope detection block
    if report.source in ("git_changes", "mixed"):
        if report.changed_files:
            lines.append(f"Changed files detected ({len(report.changed_files)}):")
            for f in report.changed_files[:20]:
                lines.append(f"  {f}")
            if len(report.changed_files) > 20:
                lines.append(f"  … and {len(report.changed_files) - 20} more")
            lines.append("")
        if report.inferred_scope_paths:
            lines.append(f"Inferred scopes: {', '.join(report.inferred_scope_paths)}")
            lines.append("")
    elif report.source == "none":
        lines.append("No git changes detected. No scope inferred from git.")
        lines.append("")

    if report.filters:
        lines.append(f"Filters applied: {report.filters}")
        lines.append("")

    if report.recent_failures:
        lines.append(f"Recent failures ({len(report.recent_failures)}):")
        for failure in report.recent_failures:
            fdict: dict[str, object] = failure
            origin = str(fdict.get("effective_failure_origin") or "unknown")
            errata_mark = " [errata corrected]" if fdict.get("errata_applied") else ""
            cmd = str(fdict.get("command", ""))
            lines.append(f"  [{origin}{errata_mark}] {cmd}")
            witness = fdict.get("witness")
            if witness:
                lines.append(f"    witness: {str(witness)[:80]}")
        lines.append("")
    else:
        lines.append("Recent failures: none matching scope")
        lines.append("")

    if report.repair_loops:
        lines.append(f"Repair loops ({len(report.repair_loops)}):")
        for rl in report.repair_loops:
            complete = "✓" if rl["complete"] else "…"
            lines.append(
                f"  {complete} {rl['repair_loop_id']} "
                f"(baseline={rl['baseline_count']}, fix={rl['same_scope_after_fix_count']})"
            )
        lines.append("")

    # v0.6: intelligence sections
    if report.known_failures:
        lines.append(f"─── Historical failures ({len(report.known_failures)}) ───────────────")
        for kf in report.known_failures:
            _sym_map = {
                "fixed_same_scope": "✓ fixed", "later_regression_validated": "✓ validated",
                "classified_errata": "~ classified", "open": "○ open",
            }
            status_sym = _sym_map.get(kf.repair_status, kf.repair_status)
            lines.append(f"  [{status_sym}] {kf.command[:70]}")
            if kf.repair_loop_id:
                lines.append(f"    loop: {kf.repair_loop_id}")
            lines.append(f"    {kf.lesson}")
        lines.append("")

    if report.repair_loop_lessons:
        fixed = [ln for ln in report.repair_loop_lessons if ln.status == "fixed"]
        if fixed:
            lines.append("─── Repair-loop lessons ────────────────────────────────")
            for ln in fixed:
                lines.append(f"  {ln.repair_loop_id}: {ln.lesson}")
            lines.append("")

    if report.hygiene_warnings:
        lines.append("─── Hygiene warnings (invocation_artifact — not product defects) ───")
        for hw in report.hygiene_warnings:
            lines.append(f"  {hw.pattern} ({hw.count}×): {hw.lesson}")
        lines.append("")

    lines.append("Historical failure context only — not M2B scoring, model ranking, "
                 "routing, or statistical proof.")
    lines.append("")
    lines.append("Recommended verification:")
    for chk in report.recommended_checks:
        lines.append(f"  {chk}")
    lines.append("")

    lines.append("Advisory only — no routing, autonomy, or merge-gate implied.")
    lines.append("Caveats:")
    for cav in report.dq_caveats:
        lines.append(f"  - {cav}")

    return "\n".join(lines) + "\n"


def format_preflight_markdown(report: PreflightReport) -> str:
    """Format preflight report as GitHub-flavoured markdown."""
    text = format_preflight_text(report)
    return "# Chimera Memory Preflight Advisory\n\n```\n" + text.rstrip() + "\n```\n"
