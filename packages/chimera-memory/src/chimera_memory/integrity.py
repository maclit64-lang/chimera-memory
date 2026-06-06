"""Chimera Memory I2A: local hash-chain integrity for claim records.

Each new claim appended to claims.jsonl gets a matching entry in integrity.jsonl.
The chain links entries via prev_chain_hash so any tampering is detectable.

Design constraints:
- stdlib only (hashlib, json, dataclasses, pathlib)
- no external crypto deps, no HMAC, no network
- historical records without chain entries → LEGACY_UNSIGNED (warning, not error)
- new records covered by chain → verified on demand
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

INTEGRITY_FILE = "integrity.jsonl"
CHAIN_VERSION = 1
_SENTINEL = object()  # sentinel for unset prev_chain_hash


# ---------------------------------------------------------------------------
# data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IntegrityEntry:
    version: int
    source: str          # e.g. "claims.jsonl"
    line_number: int     # 1-based line number in source file
    record_hash: str     # sha256 of the exact line bytes (without trailing newline)
    prev_chain_hash: str | None
    chain_hash: str      # sha256(version|source|line_number|record_hash|prev_chain_hash)


@dataclass(frozen=True)
class IntegrityError:
    line_number: int | None
    kind: str            # BROKEN_HASH | BROKEN_CHAIN | UNSIGNED_GAP | INVALID_ENTRY
    message: str


@dataclass
class IntegrityReport:
    status: str          # OK | LEGACY_UNSIGNED | BROKEN
    claims_total: int
    legacy_unsigned: int
    chained_records: int
    broken_records: int
    unsigned_gaps: int
    errors: list[IntegrityError] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "claims_total": self.claims_total,
            "legacy_unsigned": self.legacy_unsigned,
            "chained_records": self.chained_records,
            "broken_records": self.broken_records,
            "unsigned_gaps": self.unsigned_gaps,
            "errors": [asdict(e) for e in self.errors],
        }


# ---------------------------------------------------------------------------
# hashing helpers
# ---------------------------------------------------------------------------


def hash_line(line: str) -> str:
    """SHA-256 of the exact line string (UTF-8 encoded, without trailing newline)."""
    return hashlib.sha256(line.rstrip("\n").encode("utf-8")).hexdigest()


def _compute_chain_hash(
    version: int,
    source: str,
    line_number: int,
    record_hash: str,
    prev_chain_hash: str | None,
) -> str:
    parts = "|".join([
        str(version),
        source,
        str(line_number),
        record_hash,
        prev_chain_hash or "",
    ])
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# write path
# ---------------------------------------------------------------------------


def append_integrity_entry(
    memory_dir: Path,
    source: str,
    line_number: int,
    record_hash: str,
    *,
    prev_chain_hash: str | None = _SENTINEL,  # type: ignore[assignment]
) -> str:
    """Append one integrity entry chaining the given record into the ledger.

    If prev_chain_hash is supplied (from append_state cache), the O(N) scan of
    integrity.jsonl is skipped entirely. If omitted, falls back to scanning the
    file (legacy/fallback path).

    Returns the new chain_hash so callers can update their append_state cache.
    """
    integrity_path = memory_dir / INTEGRITY_FILE

    if prev_chain_hash is _SENTINEL:  # type: ignore[comparison-overlap]
        # Legacy fallback: scan the file to find the last chain hash.
        prev_chain_hash = None
        if integrity_path.exists():
            lines = integrity_path.read_text(encoding="utf-8").splitlines()
            for raw in reversed(lines):
                raw = raw.strip()
                if raw:
                    try:
                        last = json.loads(raw)
                        prev_chain_hash = last.get("chain_hash")
                    except (json.JSONDecodeError, KeyError):
                        pass
                    break

    chain_hash = _compute_chain_hash(
        CHAIN_VERSION, source, line_number, record_hash, prev_chain_hash
    )
    entry: dict[str, Any] = {
        "version": CHAIN_VERSION,
        "source": source,
        "line_number": line_number,
        "record_hash": record_hash,
        "prev_chain_hash": prev_chain_hash,
        "chain_hash": chain_hash,
    }
    with integrity_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
    return chain_hash


# ---------------------------------------------------------------------------
# verify path
# ---------------------------------------------------------------------------


def verify_integrity(memory_dir: Path) -> IntegrityReport:
    """Verify the integrity chain for claims.jsonl.

    Returns an IntegrityReport. Does not mutate any files.
    """
    claims_path = memory_dir / "claims.jsonl"
    integrity_path = memory_dir / INTEGRITY_FILE

    # Count raw claim lines
    if not claims_path.exists():
        return IntegrityReport(
            status="OK",
            claims_total=0,
            legacy_unsigned=0,
            chained_records=0,
            broken_records=0,
            unsigned_gaps=0,
        )

    claim_lines = claims_path.read_text(encoding="utf-8").splitlines()
    claims_total = len([ln for ln in claim_lines if ln.strip()])

    # No integrity file → all legacy
    if not integrity_path.exists():
        return IntegrityReport(
            status="LEGACY_UNSIGNED" if claims_total > 0 else "OK",
            claims_total=claims_total,
            legacy_unsigned=claims_total,
            chained_records=0,
            broken_records=0,
            unsigned_gaps=0,
        )

    # Load and parse integrity entries
    int_lines = integrity_path.read_text(encoding="utf-8").splitlines()
    entries: list[IntegrityEntry] = []
    errors: list[IntegrityError] = []

    for idx, raw in enumerate(int_lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            d = json.loads(raw)
            entries.append(IntegrityEntry(
                version=d["version"],
                source=d["source"],
                line_number=d["line_number"],
                record_hash=d["record_hash"],
                prev_chain_hash=d.get("prev_chain_hash"),
                chain_hash=d["chain_hash"],
            ))
        except (json.JSONDecodeError, KeyError) as exc:
            errors.append(IntegrityError(
                line_number=None,
                kind="INVALID_ENTRY",
                message=f"integrity.jsonl line {idx + 1}: {exc}",
            ))

    if errors:
        return IntegrityReport(
            status="BROKEN",
            claims_total=claims_total,
            legacy_unsigned=0,
            chained_records=0,
            broken_records=len(errors),
            unsigned_gaps=0,
            errors=errors,
        )

    if not entries:
        return IntegrityReport(
            status="LEGACY_UNSIGNED" if claims_total > 0 else "OK",
            claims_total=claims_total,
            legacy_unsigned=claims_total,
            chained_records=0,
            broken_records=0,
            unsigned_gaps=0,
        )

    # Determine the first covered line number
    first_covered = entries[0].line_number
    legacy_unsigned = first_covered - 1  # lines before first chain entry

    broken_records = 0
    unsigned_gaps = 0

    # Build a map from line_number → entry for fast lookup
    entry_map = {e.line_number: e for e in entries}

    # Check all entries in chain order
    for i, entry in enumerate(entries):
        # Verify prev_chain_hash linkage
        expected_prev = None if i == 0 else entries[i - 1].chain_hash
        if entry.prev_chain_hash != expected_prev:
            errors.append(IntegrityError(
                line_number=entry.line_number,
                kind="BROKEN_CHAIN",
                message=f"line {entry.line_number}: prev_chain_hash mismatch",
            ))
            broken_records += 1
            continue

        # Verify record_hash against actual claim line
        ln = entry.line_number  # 1-based
        if ln < 1 or ln > len(claim_lines):
            errors.append(IntegrityError(
                line_number=ln,
                kind="BROKEN_HASH",
                message=f"line {ln}: not found in claims.jsonl ({len(claim_lines)} lines)",
            ))
            broken_records += 1
            continue

        actual_line = claim_lines[ln - 1]
        actual_hash = hash_line(actual_line)
        if actual_hash != entry.record_hash:
            errors.append(IntegrityError(
                line_number=ln,
                kind="BROKEN_HASH",
                message=f"line {ln}: record_hash mismatch (file modified?)",
            ))
            broken_records += 1
            continue

        # Verify chain_hash
        expected_chain = _compute_chain_hash(
            entry.version, entry.source, entry.line_number,
            entry.record_hash, entry.prev_chain_hash,
        )
        if entry.chain_hash != expected_chain:
            errors.append(IntegrityError(
                line_number=ln,
                kind="BROKEN_CHAIN",
                message=f"line {ln}: chain_hash mismatch (integrity entry modified?)",
            ))
            broken_records += 1

    # Check for unsigned gaps: claim lines after first_covered that have no entry
    for ln in range(first_covered, claims_total + 1):
        if ln not in entry_map:
            errors.append(IntegrityError(
                line_number=ln,
                kind="UNSIGNED_GAP",
                message=f"line {ln}: claim exists after chain started but has no integrity entry",
            ))
            unsigned_gaps += 1

    chained_records = len(entries)

    if broken_records > 0 or unsigned_gaps > 0:
        status = "BROKEN"
    elif legacy_unsigned > 0:
        status = "LEGACY_UNSIGNED"
    else:
        status = "OK"

    return IntegrityReport(
        status=status,
        claims_total=claims_total,
        legacy_unsigned=legacy_unsigned,
        chained_records=chained_records,
        broken_records=broken_records,
        unsigned_gaps=unsigned_gaps,
        errors=errors,
    )


def integrity_report_to_summary(report: IntegrityReport) -> dict[str, object]:
    """Compact summary dict for embedding in receipts and status output."""
    return {
        "status": report.status,
        "claims_total": report.claims_total,
        "legacy_unsigned": report.legacy_unsigned,
        "chained_records": report.chained_records,
        "broken_records": report.broken_records,
        "unsigned_gaps": report.unsigned_gaps,
        "errors_count": len(report.errors),
    }
