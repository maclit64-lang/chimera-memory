"""Proof Debt — a local, advisory summary of evidence debt (BIGREL-2).

Computed only from an existing X-Ray result (claims, verdict label, warning
counts). Adds no new detection and no new verdict semantics. It scores evidence
quality, not code correctness, and never claims the code is wrong or correct.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

PROOF_DEBT_SCHEMA_VERSION = 1

HONESTY_LINE = "Chimera Memory scores evidence quality, not code correctness."

# Deterministic severity order (lower rank = higher priority).
_SEVERITY: dict[str, int] = {
    "CONTRADICTED_CLAIM": 1,
    "UNSETTLED_CLAIM": 2,
    "REVIEW_REQUIRED_RECEIPT": 3,
    "LOCAL_RELAPSE_WARNING": 4,
    "TEST_INTEGRITY_WARNING": 5,
    "EVIDENCE_COVERAGE_WARNING": 6,
    "EVIDENCE_QUALITY_WARNING": 7,
    "EVIDENCE_DARK_SOURCE": 8,
    "SCOPE_DRIFT": 9,
}


def _item(category: str, ref: str, title: str, reason: str, next_step: str) -> dict[str, str]:
    return {
        "category": category,
        "ref": ref,
        "title": title,
        "reason": reason,
        "next_step": next_step,
    }


def compute_proof_debt(xray_result: Mapping[str, Any]) -> dict[str, Any]:
    """Summarize evidence debt from an X-Ray result.

    Returns ``{schema_version, summary, items}``. Built only from already-present
    fields; deterministic ordering by severity then ref then title.
    """
    counts = xray_result.get("counts", {})
    settled = xray_result.get("settled_claims", []) or []
    label = xray_result.get("verdict_label", "")

    items: list[dict[str, str]] = []

    for claim in settled:
        status = claim.get("status")
        ref = claim.get("claim_id") or "-"
        intent = claim.get("intent", "") or ""
        if status == "CONTRADICTED":
            items.append(
                _item(
                    "CONTRADICTED_CLAIM", ref, intent or "contradicted claim",
                    "the latest settlement contradicted the claim.",
                    "fix the claim or add new falsifier evidence.",
                )
            )
        elif status == "UNSETTLED":
            items.append(
                _item(
                    "UNSETTLED_CLAIM", ref, intent or "unsettled claim",
                    "the claim has no settled falsifier outcome.",
                    "settle the claim against its pre-committed checks.",
                )
            )

    if label == "REVIEW REQUIRED":
        items.append(
            _item(
                "REVIEW_REQUIRED_RECEIPT", "-", "receipt verdict is REVIEW REQUIRED",
                "the current receipt verdict asks for review.",
                "review the flagged changes and add targeted evidence.",
            )
        )

    for warn in xray_result.get("local_relapse_warnings", []) or []:
        items.append(
            _item(
                "LOCAL_RELAPSE_WARNING", warn.get("prior_claim_id", "-") or "-",
                warn.get("title", ""), warn.get("explanation", ""), warn.get("hint", ""),
            )
        )

    for warn in xray_result.get("test_integrity_warnings", []) or []:
        items.append(
            _item("TEST_INTEGRITY_WARNING", "-", warn.get("title", ""),
                  warn.get("explanation", ""), warn.get("hint", ""))
        )
    for warn in xray_result.get("evidence_coverage_warnings", []) or []:
        items.append(
            _item("EVIDENCE_COVERAGE_WARNING", "-", warn.get("title", ""),
                  warn.get("explanation", ""), warn.get("hint", ""))
        )
    for warn in xray_result.get("evidence_quality_warnings", []) or []:
        items.append(
            _item("EVIDENCE_QUALITY_WARNING", "-", warn.get("title", ""),
                  warn.get("explanation", ""), warn.get("hint", ""))
        )

    dark = int(counts.get("evidence_dark_source", 0))
    if dark > 0:
        items.append(
            _item(
                "EVIDENCE_DARK_SOURCE", "-", f"{dark} evidence-dark source file(s)",
                "changed source files carry no settled claim coverage.",
                "lock and settle a claim that covers these files.",
            )
        )
    drift = int(counts.get("scope_drift", 0))
    if drift > 0:
        items.append(
            _item(
                "SCOPE_DRIFT", "-", f"{drift} scope-drift file(s)",
                "settled changes fell outside the declared scope.",
                "review the scope drift or widen the claim scope.",
            )
        )

    items.sort(key=lambda it: (_SEVERITY[it["category"]], it["ref"], it["title"]))

    summary = {
        "unsettled_claims": int(counts.get("unsettled", 0)),
        "contradicted_claims": int(counts.get("contradicted", 0)),
        "review_required_receipts": 1 if label == "REVIEW REQUIRED" else 0,
        "local_relapse_warnings": int(counts.get("local_relapse_warnings", 0)),
        "evidence_quality_warnings": int(counts.get("evidence_quality_warnings", 0)),
        "test_integrity_warnings": int(counts.get("test_integrity_warnings", 0)),
        "evidence_coverage_warnings": int(counts.get("evidence_coverage_warnings", 0)),
        "evidence_dark_sources": dark,
        "scope_drift": drift,
    }
    return {"schema_version": PROOF_DEBT_SCHEMA_VERSION, "summary": summary, "items": items}


def render_proof_debt_text(debt: Mapping[str, Any]) -> str:
    """Render a compact, advisory text summary."""
    items = debt.get("items", [])
    if not items:
        return (
            "No proof debt found in the current ledger.\n\n"
            "This does not prove code is correct. It means no known evidence-debt "
            "signals were found."
        )

    s = debt["summary"]
    lines = [
        "Proof Debt",
        "",
        HONESTY_LINE,
        "",
        "Summary:",
        f"- Unsettled claims: {s['unsettled_claims']}",
        f"- Contradicted claims: {s['contradicted_claims']}",
        f"- Receipts requiring review: {s['review_required_receipts']}",
        f"- Local relapse signals: {s['local_relapse_warnings']}",
        f"- Evidence quality warnings: {s['evidence_quality_warnings']}",
        f"- Test integrity warnings: {s['test_integrity_warnings']}",
        f"- Evidence coverage warnings: {s['evidence_coverage_warnings']}",
        f"- Evidence-dark sources: {s['evidence_dark_sources']}",
        f"- Scope drift: {s['scope_drift']}",
        "",
        "Highest-priority items:",
    ]
    for n, it in enumerate(items, start=1):
        head = f"{n}. {it['ref']} — {it['title']}" if it["ref"] != "-" else f"{n}. {it['title']}"
        lines.append(head)
        if it["reason"]:
            lines.append(f"   Reason: {it['reason']}")
        if it["next_step"]:
            lines.append(f"   Next step: {it['next_step']}")
    return "\n".join(lines)
