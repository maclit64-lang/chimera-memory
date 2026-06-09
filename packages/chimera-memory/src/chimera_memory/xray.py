"""Merge X-Ray — the PR_EVIDENCE product artifact for Chimera Memory.

Given a set of changed files (from ``git diff``) and the locked/settled claims
in the local ledger, the X-Ray answers, for one branch:

* What did the agent claim before editing?
* What falsifier was sealed?
* Did the claim settle?
* Which changed files are within a declared claim scope?
* Which changed files are evidence-dark (no settled claim coverage)?
* Did scope drift occur?
* What should the reviewer inspect first?

Honesty contract
----------------
The report shows *settled evidence*, not proof of correctness. Coverage is
path-based ("covered by declared claim scope"), never "guaranteed tested". Every
rendered report carries the non-claims caveat.

Recommended agent pattern
--------------------------
For PR reviews use commit-range mode to avoid untracked build/cache noise:

    chimera-memory xray generate --base main --head HEAD --output PR_EVIDENCE.md

Working-tree mode (default, no ``--base``) includes uncommitted and untracked
files. This is useful during active development but can surface build/cache
artefacts as evidence-dark entries.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chimera_memory.adapters.git import (
    git_changed_files_between,
    git_changed_files_since,
    git_head_sha,
)
from chimera_memory.claim_lock import (
    STATUS_CONTRADICTED,
    STATUS_LOCKED,
    STATUS_SCOPE_DRIFT,
    STATUS_UNSETTLED,
    STATUS_VALIDATED,
    exclude_ledger_paths,
    file_under_scope,
)
from chimera_memory.storage import MemoryStore

XRAY_SCHEMA_VERSION = 1

# Statuses that provide positive ("settled") path coverage.
_COVERING_STATUSES = {STATUS_VALIDATED, STATUS_SCOPE_DRIFT}
# Statuses that touch a file but do not provide clean coverage.
_WEAK_STATUSES = {STATUS_CONTRADICTED, STATUS_UNSETTLED}

CAVEAT = "This report shows settled evidence, not proof of correctness."

_RECOMMENDED_PR_PATTERN = (
    "chimera-memory xray generate --base main --head HEAD --output PR_EVIDENCE.md"
)

# Path patterns that strongly suggest build/cache artefacts rather than source.
# Used to classify evidence-dark files for reviewer clarity.
_CACHE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(^|/)__pycache__/"),
    re.compile(r"(^|/)\.pytest_cache/"),
    re.compile(r"(^|/)\.mypy_cache/"),
    re.compile(r"(^|/)\.ruff_cache/"),
    re.compile(r"(^|/)node_modules/"),
    re.compile(r"(^|/)dist/"),
    re.compile(r"(^|/)build/"),
    re.compile(r"(^|/)\.tox/"),
    re.compile(r"(^|/)\.(venv|env)/"),
    re.compile(r"\.pyc$"),
    re.compile(r"\.pyo$"),
    re.compile(r"\.so$"),
    re.compile(r"\.egg-info/"),
]


def _is_likely_cache(path: str) -> bool:
    norm = path.replace("\\", "/")
    return any(p.search(norm) for p in _CACHE_PATTERNS)


def classify_evidence_dark(files: list[str]) -> dict[str, list[str]]:
    """Split evidence-dark files into source and likely-cache buckets.

    Returns ``{"source_files": [...], "likely_cache_or_build": [...]}``.
    This lets the reviewer immediately see whether noise is real source
    or local build/cache artefacts.
    """
    source: list[str] = []
    cache: list[str] = []
    for f in files:
        (cache if _is_likely_cache(f) else source).append(f)
    return {"source_files": source, "likely_cache_or_build": cache}


def generate_xray(
    store: MemoryStore,
    *,
    root: Path | None = None,
    base: str | None = None,
    head: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the structured Merge X-Ray result (stable JSON shape).

    Change set resolution:
      * If ``base`` is given, diff ``base``..(``head`` or ``HEAD``).
        This is the recommended PR-review pattern: avoids untracked/unstaged
        build/cache artefacts.
      * Otherwise, use working-tree changes vs ``HEAD`` (local uncommitted work
        including untracked files). Useful during active dev but can include
        cache artefacts as evidence-dark entries.
    """
    root = root or Path.cwd()
    generated_at = (now or datetime.now(UTC)).isoformat()

    if base is not None:
        effective_head = head or "HEAD"
        changed_files = git_changed_files_between(base, effective_head, root)
        diff_mode = "range"
        diff_base = base
        diff_head = effective_head
        working_tree_warning = None
    else:
        changed_files = git_changed_files_since("HEAD", root)
        diff_mode = "working_tree"
        diff_base = git_head_sha(root) or "HEAD"
        diff_head = "WORKTREE"
        working_tree_warning = (
            "Working-tree mode includes uncommitted and untracked files. "
            "Build/cache artefacts may appear as evidence-dark entries. "
            f"For PR reviews use: {_RECOMMENDED_PR_PATTERN}"
        )
    changed_files = exclude_ledger_paths(changed_files)

    claims = store.latest_claim_locks()
    settled_claims = [c for c in claims if _status_of(c) != STATUS_LOCKED]
    post_hoc = len(claims) == 0

    # When no claim locks exist, check wrap-based outcomes (claims.jsonl/outcomes.jsonl).
    # wrap evidence is real and settled but lives in a separate storage path that
    # X-Ray cannot map to changed files without file-level scope.
    wrap_outcomes_count = 0
    if post_hoc:
        try:
            outcomes = store.read_outcomes()
            wrap_outcomes_count = sum(
                1 for o in outcomes
                if o.get("outcome", {}).get("observed") is True
            )
        except Exception:  # noqa: BLE001
            wrap_outcomes_count = 0

    settled_view: list[dict[str, Any]] = []
    for claim in claims:
        status = _status_of(claim)
        scope_path = claim.get("scope_path", ".")
        covered = [f for f in changed_files if file_under_scope(f, scope_path)]
        settled_view.append(
            {
                "claim_id": claim.get("claim_id"),
                "status": status,
                "intent": claim.get("intent", ""),
                "scope_path": scope_path,
                "predicted_outcome": claim.get("predicted_outcome", ""),
                "falsifiers": [e.get("command") for e in claim.get("falsifiers", [])],
                "must_not_break": [
                    e.get("command") for e in claim.get("must_not_break", [])
                ],
                "quality": claim.get("quality", {}),
                "attribution": claim.get("attribution", {}),
                "changed_files_in_scope": covered,
                "scope_drift_files": claim.get("settlement", {}).get(
                    "scope_drift_files", []
                ),
            }
        )

    # Classify each changed file against settled-claim coverage.
    covered_files: set[str] = set()
    weakly_covered: set[str] = set()
    for claim in settled_claims:
        status = _status_of(claim)
        scope_path = claim.get("scope_path", ".")
        for f in changed_files:
            if not file_under_scope(f, scope_path):
                continue
            if status in _COVERING_STATUSES:
                covered_files.add(f)
            elif status in _WEAK_STATUSES:
                weakly_covered.add(f)

    weakly_covered -= covered_files
    evidence_dark = sorted(
        f for f in changed_files if f not in covered_files and f not in weakly_covered
    )
    evidence_dark_classified = classify_evidence_dark(evidence_dark)

    # Scope drift across the change set.
    drift_set: set[str] = set()
    for claim in settled_claims:
        for f in claim.get("settlement", {}).get("scope_drift_files", []):
            if f in changed_files:
                drift_set.add(f)
    scope_drift = sorted(drift_set)

    contradicted = [c for c in settled_claims if _status_of(c) == STATUS_CONTRADICTED]
    unsettled = [c for c in settled_claims if _status_of(c) == STATUS_UNSETTLED]

    verdict = _build_verdict(
        post_hoc=post_hoc,
        changed_count=len(changed_files),
        evidence_dark=evidence_dark,
        evidence_dark_classified=evidence_dark_classified,
        scope_drift=scope_drift,
        contradicted=contradicted,
        unsettled=unsettled,
        diff_mode=diff_mode,
    )

    reviewer_focus = _build_reviewer_focus(
        evidence_dark_source=evidence_dark_classified["source_files"],
        evidence_dark_cache=evidence_dark_classified["likely_cache_or_build"],
        scope_drift=scope_drift,
        contradicted=contradicted,
        covered_files=sorted(covered_files),
    )

    return {
        "schema_version": XRAY_SCHEMA_VERSION,
        "generated_at": generated_at,
        "mode": "post_hoc" if post_hoc else "claim_locked",
        "diff": {
            "mode": diff_mode,
            "base": diff_base,
            "head": diff_head,
        },
        "working_tree_warning": working_tree_warning,
        "verdict": verdict,
        "changed_files": changed_files,
        "settled_claims": settled_view,
        "evidence_dark_files": evidence_dark,
        "evidence_dark_classified": evidence_dark_classified,
        "weakly_covered_files": sorted(weakly_covered),
        "scope_drift_files": scope_drift,
        "reviewer_focus": reviewer_focus,
        "wrap_outcomes_count": wrap_outcomes_count,
        "counts": {
            "changed_files": len(changed_files),
            "claims": len(claims),
            "settled_claims": len(settled_claims),
            "validated": sum(
                1 for c in settled_claims if _status_of(c) == STATUS_VALIDATED
            ),
            "contradicted": len(contradicted),
            "unsettled": len(unsettled),
            "evidence_dark": len(evidence_dark),
            "evidence_dark_source": len(evidence_dark_classified["source_files"]),
            "evidence_dark_cache": len(
                evidence_dark_classified["likely_cache_or_build"]
            ),
            "scope_drift": len(scope_drift),
        },
        "caveat": CAVEAT,
    }


def _status_of(claim: dict[str, Any]) -> str:
    return claim.get("settlement", {}).get("status", STATUS_LOCKED)


def _build_verdict(
    *,
    post_hoc: bool,
    changed_count: int,
    evidence_dark: list[str],
    evidence_dark_classified: dict[str, list[str]],
    scope_drift: list[str],
    contradicted: list[dict[str, Any]],
    unsettled: list[dict[str, Any]],
    diff_mode: str,
) -> str:
    dark_source = evidence_dark_classified["source_files"]
    dark_cache = evidence_dark_classified["likely_cache_or_build"]

    if post_hoc:
        suffix = (
            " Use `--base main --head HEAD` for PR reviews."
            if diff_mode == "working_tree"
            else ""
        )
        return (
            "Post-hoc review: no pre-edit claims were locked, so none of the "
            f"{changed_count} changed file(s) carry settled claim evidence. "
            f"Review all changes manually.{suffix}"
        )
    problems: list[str] = []
    if contradicted:
        problems.append(f"{len(contradicted)} contradicted claim(s)")
    if dark_source:
        problems.append(f"{len(dark_source)} evidence-dark source file(s)")
    if dark_cache:
        problems.append(
            f"{len(dark_cache)} likely-cache/build file(s) — noise from working-tree mode"
            if diff_mode == "working_tree"
            else f"{len(dark_cache)} likely-cache/build file(s)"
        )
    if scope_drift:
        problems.append(f"{len(scope_drift)} scope drift warning(s)")
    if unsettled:
        problems.append(f"{len(unsettled)} unsettled claim(s)")
    if problems:
        return "Review required: " + ", ".join(problems) + "."
    return (
        f"All {changed_count} changed file(s) are covered by settled claim "
        "scope. This is settled evidence, not proof of correctness."
    )


def _build_reviewer_focus(
    *,
    evidence_dark_source: list[str],
    evidence_dark_cache: list[str],
    scope_drift: list[str],
    contradicted: list[dict[str, Any]],
    covered_files: list[str],
) -> list[str]:
    focus: list[str] = []
    for claim in contradicted:
        focus.append(
            f"Investigate CONTRADICTED claim '{claim.get('intent', '')}' — "
            "a pre-committed check failed."
        )
    for f in scope_drift:
        focus.append(f"Review `{f}` manually — it changed outside the declared scope.")
    for f in evidence_dark_source:
        if f not in scope_drift:
            focus.append(f"Review `{f}` manually — no settled claim covers it.")
    if evidence_dark_cache:
        focus.append(
            f"Ignore the {len(evidence_dark_cache)} likely-cache/build file(s) listed "
            "under Evidence-Dark — they are local artefacts, not source changes. "
            f"Use `--base main --head HEAD` to exclude them: {_RECOMMENDED_PR_PATTERN}"
        )
    for f in covered_files:
        focus.append(
            f"Skim `{f}`; it has a settled claim, but this is not proof of correctness."
        )
    if not focus:
        focus.append("No high-risk changes detected; still review the diff normally.")
    return focus


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------
def render_markdown(xray: dict[str, Any]) -> str:
    """Render the X-Ray as the PR_EVIDENCE.md product artifact."""
    lines: list[str] = ["# PR Evidence — Merge X-Ray", ""]

    # Diff mode header — always show so reviewer knows what they're reading.
    diff = xray.get("diff", {})
    diff_mode = diff.get("mode", "unknown")
    diff_base = diff.get("base", "?")
    diff_head = diff.get("head", "?")
    if diff_mode == "range":
        lines += [
            f"> **Commit-range mode** — diff `{diff_base}`..`{diff_head}`.",
            "> Untracked/unstaged files are excluded. Recommended for PR reviews.",
            "",
        ]
    else:
        lines += [
            "> **Working-tree mode** — includes uncommitted and untracked files.",
            "> Build/cache artefacts may appear as evidence-dark entries.",
            f"> For PR reviews use: `{_RECOMMENDED_PR_PATTERN}`",
            "",
        ]

    # Warning box if present
    warning = xray.get("working_tree_warning")
    if warning and diff_mode == "working_tree":
        lines += [f"> ⚠️  {warning}", ""]

    lines += ["## Verdict", "", xray["verdict"], ""]

    # Settled claims
    lines += ["## Settled Claims", ""]
    settled = [c for c in xray["settled_claims"] if c["status"] != STATUS_LOCKED]
    if not settled:
        lines += ["_No settled claims for this change set._", ""]
    else:
        for claim in settled:
            lines += _render_claim_block(claim)

    # Wrap-based evidence note (post_hoc only)
    wrap_count = xray.get("wrap_outcomes_count", 0)
    if wrap_count > 0 and xray.get("mode") == "post_hoc":
        lines += [
            "## Wrap-Based Evidence (Not Linked to Diff)",
            "",
            f"{wrap_count} settled outcome(s) found in the wrap ledger (`chimera-memory wrap`).",
            "",
            "These outcomes are real settled evidence, but `chimera-memory xray` cannot map",
            "them to changed files because `wrap`-based claims carry no file-level scope.",
            "",
            "To get PR_EVIDENCE with linked claim coverage, use `claim lock` + `claim settle`",
            "instead of (or alongside) `chimera-memory wrap`:",
            "",
            "```bash",
            "chimera-memory claim lock --auto --json   # before editing",
            "# ... make your changes ...",
            "chimera-memory claim settle <claim_id>    # after changes",
            "chimera-memory xray generate --base main --head HEAD --output PR_EVIDENCE.md",
            "```",
            "",
        ]

    # Evidence-dark — split by classification
    lines += ["## Evidence-Dark Changes", ""]
    classified = xray.get("evidence_dark_classified", {})
    dark_source = classified.get("source_files", xray.get("evidence_dark_files", []))
    dark_cache = classified.get("likely_cache_or_build", [])

    if not dark_source and not dark_cache:
        lines += ["_No evidence-dark files._", ""]
    else:
        if dark_source:
            lines += [
                "These source files changed but have no settled claim coverage:",
                "",
            ]
            lines += [f"- `{f}`" for f in dark_source]
            lines += [""]
        if dark_cache:
            lines += [
                "These entries are likely build/cache artefacts (not source code):",
                "",
            ]
            lines += [f"- `{f}`" for f in dark_cache]
            if diff_mode == "working_tree":
                lines += [
                    "",
                    f"> To exclude cache artefacts, use: `{_RECOMMENDED_PR_PATTERN}`",
                ]
            lines += [""]

    # Scope drift
    lines += ["## Scope Drift", ""]
    if xray["scope_drift_files"]:
        lines += ["Files changed outside the declared claim scope(s):", ""]
        lines += [f"- `{f}`" for f in xray["scope_drift_files"]]
        lines += [""]
    else:
        lines += ["_No scope drift detected._", ""]

    # Weak / unsettled
    lines += ["## Weak / Unsettled Evidence", ""]
    weak_or_unsettled = [
        c
        for c in settled
        if c["status"] in (STATUS_CONTRADICTED, STATUS_UNSETTLED)
        or "WEAK_FALSIFIER" in c.get("quality", {}).get("warnings", [])
    ]
    weakly_covered = xray.get("weakly_covered_files", [])
    if not weak_or_unsettled and not weakly_covered:
        lines += ["_No weak or unsettled evidence._", ""]
    else:
        for claim in weak_or_unsettled:
            warnings = claim.get("quality", {}).get("warnings", [])
            warn_str = f" ({', '.join(warnings)})" if warnings else ""
            lines += [f"- **{claim['status']}** — {claim['intent']}{warn_str}"]
        if weakly_covered:
            lines += ["", "Files touched only by weak/unsettled claims:", ""]
            lines += [f"- `{f}`" for f in weakly_covered]
        lines += [""]

    # Reviewer focus
    lines += ["## Reviewer Focus", ""]
    for i, item in enumerate(xray["reviewer_focus"], start=1):
        lines.append(f"{i}. {item}")
    lines += [""]

    # Non-claims
    lines += [
        "## Non-Claims",
        "",
        CAVEAT,
        "",
        "It shows which claims settled against which checks at which declared "
        "scope. It does not prove the code is correct, secure, or complete, and "
        "it does not rank or route models.",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _render_claim_block(claim: dict[str, Any]) -> list[str]:
    lines = [f"### {claim['status']} — {claim['intent']}", ""]
    lines.append(f"- Scope: `{claim['scope_path']}`")
    falsifiers = claim.get("falsifiers") or []
    for cmd in falsifiers:
        lines.append(f"- Falsifier: `{_fmt_cmd(cmd)}`")
    for cmd in claim.get("must_not_break") or []:
        lines.append(f"- Must-not-break: `{_fmt_cmd(cmd)}`")
    in_scope = claim.get("changed_files_in_scope") or []
    if in_scope:
        lines.append("- Changed files under declared scope:")
        lines += [f"  - `{f}`" for f in in_scope]
    else:
        lines.append("- No changed files fall under this claim's declared scope.")
    lines.append("")
    return lines


def _fmt_cmd(cmd: Any) -> str:
    if isinstance(cmd, list):
        return " ".join(str(part) for part in cmd)
    return str(cmd)

