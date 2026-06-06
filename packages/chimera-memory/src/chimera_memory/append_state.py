"""Append-state cache for O(1) claim/integrity appends.

Stores derived state (last line number, last chain hash) so append_claim
avoids re-reading the full claims.jsonl and integrity.jsonl on every write.

This is a cache/accelerator only — NOT the source of truth.
canonical source of truth: claims.jsonl + integrity.jsonl
verify always reads the canonical files, ignoring this cache.

Validation: before trusting a loaded state, we read only the last line of
integrity.jsonl (O(1) via seek-from-end) and compare. If mismatch, we rebuild
from canonical files (O(N) fallback). This closes the stale-valid-JSON caveat.

If the cache is missing, corrupt, stale, or mismatched it is rebuilt from
canonical files.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_STATE_FILE = "append_state.json"


@dataclass
class AppendState:
    last_line_number: int        # number of non-empty lines currently in claims.jsonl
    last_chain_hash: str | None  # chain_hash of the last integrity entry (None if none)
    last_record_hash: str | None # record_hash of the last claim (for mismatch check)

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_line_number": self.last_line_number,
            "last_chain_hash": self.last_chain_hash,
            "last_record_hash": self.last_record_hash,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AppendState:
        return cls(
            last_line_number=int(d["last_line_number"]),
            last_chain_hash=d.get("last_chain_hash"),
            last_record_hash=d.get("last_record_hash"),
        )


def _rebuild_from_canonical(memory_dir: Path) -> AppendState:
    """Rebuild append state by scanning canonical files. O(N) but only on fallback."""
    claims_path = memory_dir / "claims.jsonl"
    integrity_path = memory_dir / "integrity.jsonl"

    last_line_number = 0
    last_record_hash: str | None = None
    if claims_path.exists():
        lines = claims_path.read_text(encoding="utf-8").splitlines()
        non_empty = [ln for ln in lines if ln.strip()]
        last_line_number = len(non_empty)
        if non_empty:
            last_record_hash = hashlib.sha256(
                non_empty[-1].rstrip("\n").encode("utf-8")
            ).hexdigest()

    last_chain_hash: str | None = None
    if integrity_path.exists():
        int_lines = integrity_path.read_text(encoding="utf-8").splitlines()
        for raw in reversed(int_lines):
            raw = raw.strip()
            if raw:
                try:
                    last_chain_hash = json.loads(raw).get("chain_hash")
                except (json.JSONDecodeError, KeyError):
                    pass
                break

    return AppendState(
        last_line_number=last_line_number,
        last_chain_hash=last_chain_hash,
        last_record_hash=last_record_hash,
    )


def _read_integrity_tail(memory_dir: Path) -> dict[str, object] | None:
    """Read only the last non-empty line of integrity.jsonl — O(1) via seek.

    Returns the parsed dict, or None if the file is missing/empty/unparseable.
    Never reads the full file.
    """
    integrity_path = memory_dir / "integrity.jsonl"
    if not integrity_path.exists():
        return None
    try:
        size = integrity_path.stat().st_size
        if size == 0:
            return None
        chunk_size = min(4096, size)
        with integrity_path.open("rb") as fh:
            fh.seek(-chunk_size, 2)  # seek from end
            tail = fh.read().decode("utf-8", errors="replace")
        for raw in reversed(tail.splitlines()):
            raw = raw.strip()
            if raw:
                result: dict[str, object] = json.loads(raw)
                return result
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError):
        pass
    return None


def _state_matches_tail(state: AppendState, tail: dict[str, object] | None) -> bool:
    """Return True if state is consistent with the integrity.jsonl tail entry.

    If tail is None (no integrity entries), validates state reflects empty chain.
    """
    if tail is None:
        # No integrity entries yet — valid only if chain is empty.
        return state.last_chain_hash is None
    try:
        line_ok = int(str(tail["line_number"])) == state.last_line_number
        chain_ok = tail.get("chain_hash") == state.last_chain_hash
        record_ok = (
            state.last_record_hash is None
            or tail.get("record_hash") == state.last_record_hash
        )
        return line_ok and chain_ok and record_ok
    except (KeyError, TypeError, ValueError):
        return False


def load_or_rebuild(memory_dir: Path) -> AppendState:
    """Load cached append state, validating against integrity tail; rebuild if needed.

    Fast path (valid state AND matches integrity.jsonl tail): O(1).
    Slow path (any mismatch, missing, or corrupt): O(N) rebuild.
    """
    state_path = memory_dir / _STATE_FILE
    if state_path.exists():
        try:
            d = json.loads(state_path.read_text(encoding="utf-8"))
            state = AppendState.from_dict(d)
            tail = _read_integrity_tail(memory_dir)
            if _state_matches_tail(state, tail):
                return state
            # Stale or mismatched — fall through to rebuild
        except (json.JSONDecodeError, KeyError, ValueError):
            pass  # corrupt → rebuild
    return _rebuild_from_canonical(memory_dir)


def save(memory_dir: Path, state: AppendState) -> None:
    """Atomically write append state cache via temp-file rename."""
    state_path = memory_dir / _STATE_FILE
    tmp_path = memory_dir / f".{_STATE_FILE}.tmp"
    tmp_path.write_text(json.dumps(state.to_dict(), sort_keys=True), encoding="utf-8")
    os.replace(tmp_path, state_path)  # atomic on POSIX; best-effort on Windows
