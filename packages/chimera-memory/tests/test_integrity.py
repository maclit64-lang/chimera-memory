"""I2A: unit tests for the integrity hash-chain module."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from chimera_memory_types.finding import EvidenceRefType

from chimera_memory.integrity import (
    verify_integrity,
)
from chimera_memory.ledger import record_claim, settle_claim
from chimera_memory.storage import MemoryStore


def _init(tmp_path: Path) -> MemoryStore:
    store = MemoryStore.from_paths(root=tmp_path)
    store.initialize()
    return store


def _ev(t: datetime) -> dict:
    return {"ref_type": EvidenceRefType.EXTERNAL, "ref_id": "git:abc", "available_at": t}


def _add_claim(tmp_path: Path, offset: int = 0) -> str:
    t0 = datetime(2026, 6, 1, 12, tzinfo=UTC) + timedelta(seconds=offset)
    t1 = t0 + timedelta(seconds=5)
    cid = record_claim(
        title="test claim",
        summary="s",
        predicted=True,
        evidence=[_ev(t0)],
        root=tmp_path,
        claim_time=t0,
        agent_id="kiro",
        model_version="claude-sonnet-4.6",
        task_type="test",
    )
    settle_claim(cid, True, t1, root=tmp_path)
    return cid


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


def test_verify_empty_store_is_ok(tmp_path) -> None:
    _init(tmp_path)
    report = verify_integrity(tmp_path / ".chimera-memory")
    assert report.status == "OK"
    assert report.claims_total == 0


def test_verify_legacy_claims_without_chain_reports_legacy_unsigned(tmp_path) -> None:
    """Stores that predate integrity.jsonl show LEGACY_UNSIGNED, not BROKEN."""
    _init(tmp_path)
    # Write a claim line directly without integrity
    claims_path = tmp_path / ".chimera-memory" / "claims.jsonl"
    claims_path.write_text('{"claim_id": "old-1", "title": "old"}\n', encoding="utf-8")

    report = verify_integrity(tmp_path / ".chimera-memory")
    assert report.status == "LEGACY_UNSIGNED"
    assert report.legacy_unsigned == 1
    assert report.broken_records == 0


def test_append_integrity_entry_chains_new_claim_records(tmp_path) -> None:
    """record_claim triggers integrity chain; verify passes."""
    _init(tmp_path)
    _add_claim(tmp_path, offset=0)
    _add_claim(tmp_path, offset=100)

    report = verify_integrity(tmp_path / ".chimera-memory")
    assert report.broken_records == 0
    assert report.unsigned_gaps == 0
    assert report.chained_records > 0


def test_verify_detects_claim_line_tampering(tmp_path) -> None:
    """Editing a claim line after integrity is written → BROKEN."""
    _init(tmp_path)
    _add_claim(tmp_path)

    claims_path = tmp_path / ".chimera-memory" / "claims.jsonl"
    lines = claims_path.read_text(encoding="utf-8").splitlines()
    # Tamper the first line
    lines[0] = lines[0].replace('"title":', '"TAMPERED":')
    claims_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = verify_integrity(tmp_path / ".chimera-memory")
    assert report.status == "BROKEN"
    assert report.broken_records > 0


def test_verify_detects_chain_entry_tampering(tmp_path) -> None:
    """Editing integrity.jsonl → BROKEN."""
    _init(tmp_path)
    _add_claim(tmp_path)

    integrity_path = tmp_path / ".chimera-memory" / "integrity.jsonl"
    lines = integrity_path.read_text(encoding="utf-8").splitlines()
    # Tamper the record_hash in the first entry
    entry = json.loads(lines[0])
    entry["record_hash"] = "deadbeef" * 8
    lines[0] = json.dumps(entry, sort_keys=True)
    integrity_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = verify_integrity(tmp_path / ".chimera-memory")
    assert report.status == "BROKEN"
    assert report.broken_records > 0


def test_verify_detects_unsigned_gap_after_chain_started(tmp_path) -> None:
    """A new claim appended without integrity entry after chain started → UNSIGNED_GAP."""
    _init(tmp_path)
    _add_claim(tmp_path, offset=0)  # gets integrity entry

    # Append a raw claim line without calling record_claim (bypasses integrity)
    claims_path = tmp_path / ".chimera-memory" / "claims.jsonl"
    with claims_path.open("a", encoding="utf-8") as fh:
        fh.write('{"claim_id": "ghost", "title": "no integrity"}\n')

    report = verify_integrity(tmp_path / ".chimera-memory")
    assert report.status == "BROKEN"
    assert report.unsigned_gaps > 0


def test_verify_json_shape_is_stable(tmp_path) -> None:
    """to_dict() has stable keys matching spec."""
    _init(tmp_path)
    _add_claim(tmp_path)
    report = verify_integrity(tmp_path / ".chimera-memory")
    d = report.to_dict()
    for key in ("status", "claims_total", "legacy_unsigned", "chained_records",
                "broken_records", "unsigned_gaps", "errors"):
        assert key in d
    assert isinstance(d["errors"], list)


def test_verify_no_unsigned_gap_when_two_claims_appended_sequentially(tmp_path) -> None:
    """Two claims appended back-to-back must each get their own integrity entry.

    Regression test for the K1 race: if line_number is computed after the write
    by re-reading the file, two near-simultaneous appends can both record the
    same line_number, leaving the first claim with no integrity entry (UNSIGNED_GAP)
    and the second with two conflicting entries (BROKEN_CHAIN).
    """
    _init(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)

    t0 = datetime(2026, 6, 1, 12, tzinfo=UTC)

    cid1 = record_claim(
        title="claim A", summary="s", predicted=True, evidence=[_ev(t0)],
        root=tmp_path, claim_time=t0, agent_id="agent-a", task_type="test",
    )
    cid2 = record_claim(
        title="claim B", summary="s", predicted=True,
        evidence=[_ev(t0 + timedelta(seconds=1))],
        root=tmp_path, claim_time=t0 + timedelta(seconds=1),
        agent_id="agent-b", task_type="lint",
    )

    report = verify_integrity(tmp_path / ".chimera-memory")
    assert report.unsigned_gaps == 0, (
        f"Expected no unsigned gaps but got {report.unsigned_gaps}: "
        f"{[e.message for e in report.errors]}"
    )
    assert report.broken_records == 0, (
        f"Expected no broken records but got {report.broken_records}: "
        f"{[e.message for e in report.errors]}"
    )
    assert report.status in ("OK", "LEGACY_UNSIGNED")


def test_integrity_line_number_uses_pre_write_count(tmp_path) -> None:
    """append_claim must record the line number based on count BEFORE the write.

    Regression: if line_number = count_after_write, concurrent appends both
    see the same post-write count and both record the same line_number,
    leaving one claim with no entry (UNSIGNED_GAP) and one with a duplicate
    entry whose stored_hash mismatches (BROKEN_CHAIN).

    This test simulates the failure by directly calling append_integrity_entry
    with a post-write count and verifying that the store is broken.
    """
    from chimera_memory.integrity import append_integrity_entry, hash_line

    memory_dir = tmp_path / ".chimera-memory"
    memory_dir.mkdir()
    claims_path = memory_dir / "claims.jsonl"

    # Write two lines (simulating two claims)
    line_a = '{"claim_id": "aaaa", "title": "A"}'
    line_b = '{"claim_id": "bbbb", "title": "B"}'
    claims_path.write_text(line_a + "\n" + line_b + "\n", encoding="utf-8")

    # Simulate the buggy post-write pattern: both calls read count=2 after both writes
    # Entry for line_a records line_number=2 (wrong — should be 1)
    append_integrity_entry(memory_dir, "claims.jsonl", 2, hash_line(line_a))
    # Entry for line_b also records line_number=2
    append_integrity_entry(memory_dir, "claims.jsonl", 2, hash_line(line_b))

    report = verify_integrity(memory_dir)
    # This should be broken: line 1 has no entry (UNSIGNED_GAP),
    # and line 2 has two entries with conflicting hashes (BROKEN_CHAIN)
    assert report.status == "BROKEN"
    assert report.unsigned_gaps >= 1 or report.broken_records >= 1



def test_append_claim_lock_prevents_interleaved_line_numbers(tmp_path) -> None:
    """Two sequential append_claim calls must produce contiguous, non-duplicate
    integrity line_number entries.

    Regression test for K5 race: if the read-count → write-claim → write-integrity
    triplet is not atomic, two near-simultaneous appends both pre-compute the same
    line_number, causing one UNSIGNED_GAP and one entry with the wrong hash.
    """
    _init(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    t0 = datetime(2026, 6, 1, 12, tzinfo=UTC)

    # Simulate rapid-fire sequential appends (the lockfile must serialize these)
    for i in range(5):
        record_claim(
            title=f"claim {i}", summary="s", predicted=True,
            evidence=[_ev(t0 + timedelta(seconds=i))],
            root=tmp_path, claim_time=t0 + timedelta(seconds=i),
            agent_id="test-agent", task_type="test",
        )

    report = verify_integrity(tmp_path / ".chimera-memory")
    assert report.unsigned_gaps == 0, (
        f"Expected no unsigned gaps after rapid appends: "
        f"{[e.message for e in report.errors]}"
    )
    assert report.broken_records == 0, (
        f"Expected no broken records: {[e.message for e in report.errors]}"
    )
    assert report.status in ("OK", "LEGACY_UNSIGNED")


def test_append_claim_creates_lockfile(tmp_path) -> None:
    """append_claim must create the .append.lock advisory file."""
    _init(tmp_path)
    t0 = datetime(2026, 6, 1, 12, tzinfo=UTC)
    record_claim(
        title="t", summary="s", predicted=True, evidence=[_ev(t0)],
        root=tmp_path, claim_time=t0, agent_id="kiro", task_type="test",
    )
    lock_path = tmp_path / ".chimera-memory" / ".append.lock"
    assert lock_path.exists(), "Lock file should be created by append_claim"


def test_simulated_concurrent_append_without_lock_produces_broken_integrity(tmp_path) -> None:
    """Directly simulate the race to prove it creates BROKEN integrity.

    Two appends both pre-compute the same line_number (the buggy pattern),
    producing one unsigned gap and one entry with a mismatched hash.
    """
    from chimera_memory.integrity import append_integrity_entry, hash_line

    memory_dir = tmp_path / ".chimera-memory"
    memory_dir.mkdir()
    claims_path = memory_dir / "claims.jsonl"

    line_a = '{"claim_id": "aaaa", "title": "A"}'
    line_b = '{"claim_id": "bbbb", "title": "B"}'

    # Simulate both processes reading count=0 before either writes
    # Both compute line_number=1
    claims_path.write_text(line_a + "\n" + line_b + "\n", encoding="utf-8")

    # Both write integrity for line 1 with their own hash (simulating the race)
    append_integrity_entry(memory_dir, "claims.jsonl", 1, hash_line(line_a))
    append_integrity_entry(memory_dir, "claims.jsonl", 1, hash_line(line_b))

    report = verify_integrity(memory_dir)
    # Should be BROKEN: line 2 has no entry, line 1 has two entries
    assert report.status == "BROKEN"
