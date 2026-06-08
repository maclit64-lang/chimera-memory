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
"""
from __future__ import annotations

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
      * Otherwise, use working-tree changes vs ``HEAD`` (local uncommitted work).
    """
    root = root or Path.cwd()
    generated_at = (now or datetime.now(UTC)).isoformat()

    if base is not None:
        effective_head = head or "HEAD"
        changed_files = git_changed_files_between(base, effective_head, root)
        diff_mode = "range"
        diff_base = base
        diff_head = effective_head
    else:
        changed_files = git_changed_files_since("HEAD", root)
        diff_mode = "working_tree"
        diff_base = git_head_sha(root) or "HEAD"
        diff_head = "WORKTREE"
    changed_files = exclude_ledger_paths(changed_files)

    claims = store.latest_claim_locks()
    settled_claims = [c for c in claims if _status_of(c) != STATUS_LOCKED]
    post_hoc = len(claims) == 0

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

    # Scope drift across the change set: files outside a claim's scope that a
    # settle run flagged, restricted to files actually in this change set.
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
        scope_drift=scope_drift,
        contradicted=contradicted,
        unsettled=unsettled,
    )

    reviewer_focus = _build_reviewer_focus(
        evidence_dark=evidence_dark,
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
        "verdict": verdict,
        "changed_files": changed_files,
        "settled_claims": settled_view,
        "evidence_dark_files": evidence_dark,
        "weakly_covered_files": sorted(weakly_covered),
        "scope_drift_files": scope_drift,
        "reviewer_focus": reviewer_focus,
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
    scope_drift: list[str],
    contradicted: list[dict[str, Any]],
    unsettled: list[dict[str, Any]],
) -> str:
    if post_hoc:
        return (
            "Post-hoc review: no pre-edit claims were locked, so none of the "
            f"{changed_count} changed file(s) carry settled claim evidence. "
            "Review all changes manually."
        )
    problems: list[str] = []
    if contradicted:
        problems.append(f"{len(contradicted)} contradicted claim(s)")
    if evidence_dark:
        problems.append(f"{len(evidence_dark)} evidence-dark file(s)")
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
    evidence_dark: list[str],
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
    for f in evidence_dark:
        if f in scope_drift:
            continue
        focus.append(f"Review `{f}` manually — no settled claim covers it.")
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

    lines += ["## Verdict", "", xray["verdict"], ""]

    # Settled claims
    lines += ["## Settled Claims", ""]
    settled = [
        c for c in xray["settled_claims"] if c["status"] != STATUS_LOCKED
    ]
    if not settled:
        lines += ["_No settled claims for this change set._", ""]
    else:
        for claim in settled:
            lines += _render_claim_block(claim)

    # Evidence-dark
    lines += ["## Evidence-Dark Changes", ""]
    if xray["evidence_dark_files"]:
        lines += ["These files changed but have no settled claim coverage:", ""]
        lines += [f"- `{f}`" for f in xray["evidence_dark_files"]]
        lines += [""]
    else:
        lines += ["_No evidence-dark files._", ""]

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
            lines += [
                f"- **{claim['status']}** — {claim['intent']}{warn_str}",
            ]
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
