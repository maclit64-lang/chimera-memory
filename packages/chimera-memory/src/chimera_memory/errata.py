"""Chimera Memory claim errata — additive corrections to claim metadata.

Claim records are append-only and must never be mutated. When a claim was
originally labeled with an incorrect failure_origin (e.g. a shell quoting mistake
recorded as organic_real), an errata record can correct the classification for
DQ-aware computations (m2b-readiness, organic-only reliability) without touching
historical ledger files.

Storage: .chimera-memory/errata.jsonl (append-only)
Schema: {claim_id, corrected_failure_origin, reason, note, created_at}

Errata are additive, auditable, and do NOT delete or hide the original claim.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ERRATA_FILE = "errata.jsonl"


def add_errata(
    memory_dir: Path,
    claim_id: str,
    corrected_failure_origin: str,
    reason: str,
    note: str = "",
) -> None:
    """Append an errata record to errata.jsonl. Does not modify claims.jsonl."""
    from chimera_memory.data_quality import validate_failure_origin

    validate_failure_origin(corrected_failure_origin)
    entry: dict[str, Any] = {
        "claim_id": claim_id,
        "corrected_failure_origin": corrected_failure_origin,
        "reason": reason,
        "note": note,
        "created_at": datetime.now(UTC).isoformat(),
    }
    path = memory_dir / ERRATA_FILE
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def load_errata(memory_dir: Path) -> dict[str, dict[str, Any]]:
    """Return {claim_id: errata_record} for the most recent errata per claim."""
    path = memory_dir / ERRATA_FILE
    if not path.exists():
        return {}
    result: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            result[rec["claim_id"]] = rec  # last write wins
        except (json.JSONDecodeError, KeyError):
            pass
    return result


def apply_errata(claim: Any, errata_map: dict[str, dict[str, Any]]) -> str | None:
    """Return corrected failure_origin for a claim if errata exists, else None."""
    rec = errata_map.get(claim.claim_id)
    if rec:
        return str(rec["corrected_failure_origin"])
    return None


def effective_metadata(
    claim: Any,
    errata_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return effective metadata for a claim with errata corrections applied.

    Returns a dict with:
      raw: the original claim metadata
      effective: claim metadata with errata override applied (if any)
      errata_applied: True if any correction was applied
      corrected_failure_origin: the corrected value if applied, else None
      errata_reason: correction reason if applied, else None
    """
    raw = claim.metadata or {}
    errata_rec = errata_map.get(claim.claim_id)
    if errata_rec:
        eff = dict(raw)
        eff["failure_origin"] = errata_rec["corrected_failure_origin"]
        return {
            "raw": raw,
            "effective": eff,
            "errata_applied": True,
            "corrected_failure_origin": errata_rec["corrected_failure_origin"],
            "errata_reason": errata_rec.get("reason"),
        }
    return {
        "raw": raw,
        "effective": raw,
        "errata_applied": False,
        "corrected_failure_origin": None,
        "errata_reason": None,
    }


def effective_failure_origin(claim: Any, errata_map: dict[str, dict[str, Any]]) -> str | None:
    """Return effective failure_origin (errata-corrected if available)."""
    corrected = apply_errata(claim, errata_map)
    if corrected is not None:
        return corrected
    return (claim.metadata or {}).get("failure_origin")
