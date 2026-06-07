"""CHM-3B storage state validation hardening tests."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from chimera_memory_types.finding import EvidenceRef, EvidenceRefType

from chimera_memory.append_state import (
    AppendState,
    _read_integrity_tail,
    _state_matches_tail,
    load_or_rebuild,
    save,
)
from chimera_memory.integrity import verify_integrity
from chimera_memory.ledger import record_claim


def _ev(t: datetime) -> EvidenceRef:
    return EvidenceRef(ref_type=EvidenceRefType.EXTERNAL, ref_id="r", available_at=t)


def _record(root: Path, i: int = 0) -> str:
    t0 = datetime(2026, 1, 1, 12, tzinfo=UTC)
    return record_claim(
        title=f"c{i}", summary="s", predicted=True,
        evidence=[_ev(t0)], root=root, claim_time=t0,
        agent_id="a", task_type="test",
    )


# ---------------------------------------------------------------------------
# _read_integrity_tail unit tests
# ---------------------------------------------------------------------------


def test_tail_returns_none_for_missing_integrity(tmp_path: Path) -> None:
    assert _read_integrity_tail(tmp_path) is None


def test_tail_returns_none_for_empty_integrity(tmp_path: Path) -> None:
    (tmp_path / "integrity.jsonl").write_text("", encoding="utf-8")
    assert _read_integrity_tail(tmp_path) is None


def test_tail_returns_last_entry(tmp_path: Path) -> None:
    entries = [
        json.dumps({"line_number": 1, "chain_hash": "aaa", "record_hash": "rrr"}),
        json.dumps({"line_number": 2, "chain_hash": "bbb", "record_hash": "sss"}),
    ]
    (tmp_path / "integrity.jsonl").write_text("\n".join(entries) + "\n", encoding="utf-8")
    tail = _read_integrity_tail(tmp_path)
    assert tail is not None
    assert tail["line_number"] == 2
    assert tail["chain_hash"] == "bbb"


# ---------------------------------------------------------------------------
# _state_matches_tail unit tests
# ---------------------------------------------------------------------------


def test_state_matches_tail_true_when_consistent() -> None:
    state = AppendState(last_line_number=3, last_chain_hash="abc", last_record_hash="xyz")
    tail = {"line_number": 3, "chain_hash": "abc", "record_hash": "xyz"}
    assert _state_matches_tail(state, tail) is True


def test_state_matches_tail_false_wrong_line_number() -> None:
    state = AppendState(last_line_number=2, last_chain_hash="abc", last_record_hash=None)
    tail = {"line_number": 3, "chain_hash": "abc", "record_hash": "xyz"}
    assert _state_matches_tail(state, tail) is False


def test_state_matches_tail_false_wrong_chain_hash() -> None:
    state = AppendState(last_line_number=3, last_chain_hash="WRONG", last_record_hash=None)
    tail = {"line_number": 3, "chain_hash": "abc", "record_hash": "xyz"}
    assert _state_matches_tail(state, tail) is False


def test_state_matches_tail_false_wrong_record_hash() -> None:
    state = AppendState(last_line_number=3, last_chain_hash="abc", last_record_hash="WRONG")
    tail = {"line_number": 3, "chain_hash": "abc", "record_hash": "xyz"}
    assert _state_matches_tail(state, tail) is False


def test_state_matches_tail_none_tail_empty_chain() -> None:
    state = AppendState(last_line_number=0, last_chain_hash=None, last_record_hash=None)
    assert _state_matches_tail(state, None) is True


def test_state_matches_tail_none_tail_nonempty_chain_fails() -> None:
    state = AppendState(last_line_number=1, last_chain_hash="abc", last_record_hash=None)
    assert _state_matches_tail(state, None) is False


# ---------------------------------------------------------------------------
# Self-healing integration tests
# ---------------------------------------------------------------------------


def test_stale_line_number_self_heals(tmp_path: Path) -> None:
    """Stale state with wrong line_number → append self-heals and verify is clean."""
    mem = tmp_path / ".chimera-memory"
    for i in range(3):
        _record(tmp_path, i)

    # Corrupt state: wrong line_number
    state = load_or_rebuild(mem)
    bad = AppendState(
        last_line_number=1,  # wrong — should be 3
        last_chain_hash=state.last_chain_hash,
        last_record_hash=state.last_record_hash,
    )
    save(mem, bad)

    # Next append must self-heal (load_or_rebuild detects mismatch via tail check)
    _record(tmp_path, 99)

    report = verify_integrity(mem)
    assert report.broken_records == 0
    assert report.unsigned_gaps == 0
    assert report.claims_total == 4


def test_stale_chain_hash_self_heals(tmp_path: Path) -> None:
    """Stale state with wrong chain_hash → append self-heals."""
    mem = tmp_path / ".chimera-memory"
    for i in range(2):
        _record(tmp_path, i)

    state = load_or_rebuild(mem)
    bad = AppendState(
        last_line_number=state.last_line_number,
        last_chain_hash="deadbeef" * 8,  # wrong chain_hash
        last_record_hash=state.last_record_hash,
    )
    save(mem, bad)

    _record(tmp_path, 99)

    report = verify_integrity(mem)
    assert report.broken_records == 0


def test_stale_record_hash_self_heals(tmp_path: Path) -> None:
    """Stale state with wrong record_hash → append self-heals."""
    mem = tmp_path / ".chimera-memory"
    for i in range(2):
        _record(tmp_path, i)

    state = load_or_rebuild(mem)
    bad = AppendState(
        last_line_number=state.last_line_number,
        last_chain_hash=state.last_chain_hash,
        last_record_hash="wronghash" * 4,  # wrong record_hash
    )
    save(mem, bad)

    _record(tmp_path, 99)

    report = verify_integrity(mem)
    assert report.broken_records == 0


def test_corrupt_json_state_self_heals(tmp_path: Path) -> None:
    """Corrupt append_state.json → rebuild and append cleanly."""
    mem = tmp_path / ".chimera-memory"
    _record(tmp_path, 0)
    (mem / "append_state.json").write_text("{bad json!!!", encoding="utf-8")
    _record(tmp_path, 1)
    assert verify_integrity(mem).broken_records == 0


def test_missing_state_self_heals(tmp_path: Path) -> None:
    """Missing append_state.json → rebuild and append cleanly."""
    mem = tmp_path / ".chimera-memory"
    for i in range(2):
        _record(tmp_path, i)
    (mem / "append_state.json").unlink()
    _record(tmp_path, 99)
    assert verify_integrity(mem).broken_records == 0


def test_legacy_unsigned_behavior_unchanged(tmp_path: Path) -> None:
    """A ledger with no integrity.jsonl still verifies as LEGACY_UNSIGNED."""
    mem = tmp_path / ".chimera-memory"
    mem.mkdir()
    (mem / "claims.jsonl").write_text('{"claim_id": "legacy"}\n', encoding="utf-8")
    # No integrity.jsonl → LEGACY_UNSIGNED
    report = verify_integrity(mem)
    assert report.status == "LEGACY_UNSIGNED"
    assert report.broken_records == 0


def test_valid_state_not_rebuilt_on_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When state matches integrity tail, _rebuild_from_canonical is NOT called."""
    import chimera_memory.append_state as _as_mod

    rebuild_calls: list[int] = []
    orig = _as_mod._rebuild_from_canonical

    def tracking(mem: Path) -> AppendState:
        rebuild_calls.append(1)
        return orig(mem)

    monkeypatch.setattr(_as_mod, "_rebuild_from_canonical", tracking)

    mem = tmp_path / ".chimera-memory"
    # First append — state missing, will rebuild once
    _record(tmp_path, 0)
    rebuild_calls.clear()

    # Second and third appends — state valid and matches tail, no rebuild
    _record(tmp_path, 1)
    _record(tmp_path, 2)

    assert rebuild_calls == [], (
        f"_rebuild_from_canonical called {len(rebuild_calls)} times on warm state"
    )


# ---------------------------------------------------------------------------
# Performance guard
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_append_1000_claims_within_time_budget(tmp_path: Path) -> None:
    """1000 appends with state validation must stay well under 10 seconds.

    This is a performance benchmark, not a correctness test.
    Marked slow because wall-clock timing is load-sensitive.
    Run explicitly with: pytest -m slow
    """
    t0 = datetime(2026, 1, 1, 12, tzinfo=UTC)
    ev = _ev(t0)
    start = time.perf_counter()
    for i in range(1000):
        record_claim(
            title=f"t{i}", summary="s", predicted=True,
            evidence=[ev], root=tmp_path, claim_time=t0,
            agent_id="a", task_type="test",
        )
    elapsed = time.perf_counter() - start
    assert elapsed < 10.0, f"1000 appends took {elapsed:.2f}s — expected < 10s"
