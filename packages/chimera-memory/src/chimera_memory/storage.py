"""Chimera Memory storage layer.

Append-only JSONL persistence for claims and integrity chain entries.

Concurrency model: append_claim uses an exclusive file lock
(.chimera-memory/.append.lock) to serialize the read-count → write-claim →
write-integrity triplet. This prevents the race where two processes both
pre-compute the same line_number and produce an integrity gap or duplicate.

Uses filelock.FileLock for cross-platform advisory locking (macOS, Linux, Windows).
Non-claim writes (outcomes, scores, sessions) are not serialized — only
claims.jsonl integrity entries require this guarantee.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import filelock

from chimera_memory._index import ClaimIndex
from chimera_memory_types.knowledge import Claim


def resolve_memory_dir(
    *,
    root: str | Path | None = None,
    memory_dir: str | Path | None = None,
    store_path: str | Path | None = None,
) -> Path:
    if memory_dir is not None:
        return Path(memory_dir)
    if store_path is not None:
        path = Path(store_path)
        return path.parent if path.name == "claims.jsonl" else path
    if root is not None:
        return Path(root) / ".chimera-memory"
    return Path.cwd() / ".chimera-memory"


def ensure_storage(memory_dir: Path) -> None:
    memory_dir.mkdir(parents=True, exist_ok=True)


def append_claim(claim: Claim, memory_dir: Path) -> None:
    MemoryStore(memory_dir).append_claim(claim)


def read_claims(memory_dir: Path) -> list[Claim]:
    return MemoryStore(memory_dir).read_claims()


def latest_claim(memory_dir: Path, claim_id: str) -> Claim | None:
    return MemoryStore(memory_dir).latest_claim(claim_id)


def _append_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True))
        handle.write("\n")


@dataclass(frozen=True)
class MemoryStore:
    memory_dir: Path

    @classmethod
    def from_paths(
        cls,
        *,
        root: str | Path | None = None,
        memory_dir: str | Path | None = None,
        store_path: str | Path | None = None,
    ) -> MemoryStore:
        return cls(resolve_memory_dir(root=root, memory_dir=memory_dir, store_path=store_path))

    @property
    def claims_path(self) -> Path:
        return self.memory_dir / "claims.jsonl"

    @property
    def outcomes_path(self) -> Path:
        return self.memory_dir / "outcomes.jsonl"

    @property
    def scores_path(self) -> Path:
        return self.memory_dir / "scores.jsonl"

    @property
    def sessions_path(self) -> Path:
        return self.memory_dir / "sessions.jsonl"

    @property
    def claim_locks_path(self) -> Path:
        return self.memory_dir / "claim_locks.jsonl"

    @property
    def index_path(self) -> Path:
        return self.memory_dir / "index.sqlite"

    def ensure(self) -> None:
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        self.ensure()
        for path in (self.claims_path, self.outcomes_path, self.scores_path):
            path.touch(exist_ok=True)
        ClaimIndex(self.index_path)

    def append_jsonl(self, name: str, payload: dict[str, Any]) -> None:
        path = self.memory_dir / name
        self._require_inside_memory(path)
        _append_json(path, payload)

    def append_claim(self, claim: Claim) -> None:
        self.ensure()
        payload = claim.model_dump(mode="json")
        line = json.dumps(payload, sort_keys=True)
        claims_path = self.memory_dir / "claims.jsonl"
        claims_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.memory_dir / ".append.lock"

        from chimera_memory.append_state import AppendState, load_or_rebuild, save
        from chimera_memory.integrity import append_integrity_entry, hash_line

        record_hash = hash_line(line)

        # Exclusive file lock serializes: load-state → write-claim → write-integrity
        # → update-state → index. All within one lock acquisition.
        lock_path.touch(exist_ok=True)
        with filelock.FileLock(str(lock_path)):
            state = load_or_rebuild(self.memory_dir)
            line_number = state.last_line_number + 1

            with claims_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

            new_chain_hash = append_integrity_entry(
                memory_dir=self.memory_dir,
                source="claims.jsonl",
                line_number=line_number,
                record_hash=record_hash,
                prev_chain_hash=state.last_chain_hash,
            )

            save(self.memory_dir, AppendState(
                last_line_number=line_number,
                last_chain_hash=new_chain_hash,
                last_record_hash=record_hash,
            ))

            # Index update inside lock so index is consistent with canonical files.
            # If index fails, canonical ledger is already durable — index is best-effort.
            try:
                ClaimIndex(self.index_path).index(claim)
            except Exception:  # noqa: BLE001
                pass

        # Re-touch: filelock removes the file on release; keep it present for diagnostics.
        lock_path.touch(exist_ok=True)

    def append_outcome(self, payload: dict[str, Any]) -> None:
        self.append_jsonl("outcomes.jsonl", payload)

    def append_score(self, payload: dict[str, Any]) -> None:
        self.append_jsonl("scores.jsonl", payload)

    def append_session_event(self, payload: dict[str, Any]) -> None:
        """Append one session event (start or end) to sessions.jsonl.

        Append-only: never rewrites or mutates historical events.
        """
        self.ensure()
        self.append_jsonl("sessions.jsonl", payload)

    def read_claims(self) -> list[Claim]:
        return [
            Claim.model_validate(payload)
            for payload in self.read_jsonl("claims.jsonl")
        ]

    def read_outcomes(self) -> list[dict[str, Any]]:
        return self.read_jsonl("outcomes.jsonl")

    def read_scores(self) -> list[dict[str, Any]]:
        return self.read_jsonl("scores.jsonl")

    def latest_claim(self, claim_id: str) -> Claim | None:
        matches = [claim for claim in self.read_claims() if claim.claim_id == claim_id]
        return matches[-1] if matches else None

    def latest_claims(self) -> list[Claim]:
        claims: dict[str, Claim] = {}
        for claim in self.read_claims():
            claims[claim.claim_id] = claim
        return list(claims.values())

    def index_claim(self, claim: Claim) -> None:
        self.ensure()
        ClaimIndex(self.index_path).index(claim)

    def read_jsonl(self, name: str) -> list[dict[str, Any]]:
        path = self.memory_dir / name
        self._require_inside_memory(path)
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    def read_session_events(self) -> list[dict[str, Any]]:
        """Return all session events in insertion order."""
        return self.read_jsonl("sessions.jsonl")

    def append_claim_lock(self, payload: dict[str, Any]) -> None:
        """Append one claim-lock record to claim_locks.jsonl (append-only).

        Both the initial LOCKED record and later settlement records are appended
        as full records sharing the same ``claim_id``; the latest record for an
        id is authoritative. History is never mutated.
        """
        self.ensure()
        self.append_jsonl("claim_locks.jsonl", payload)

    def read_claim_locks(self) -> list[dict[str, Any]]:
        """Return all claim-lock records in insertion order."""
        return self.read_jsonl("claim_locks.jsonl")

    def latest_claim_lock(self, claim_id: str) -> dict[str, Any] | None:
        """Return the most recent claim-lock record for ``claim_id``, or None."""
        match: dict[str, Any] | None = None
        for record in self.read_claim_locks():
            if record.get("claim_id") == claim_id:
                match = record
        return match

    def latest_claim_locks(self) -> list[dict[str, Any]]:
        """Return the latest record per claim_id, in first-seen order."""
        order: list[str] = []
        latest: dict[str, dict[str, Any]] = {}
        for record in self.read_claim_locks():
            cid = record.get("claim_id")
            if not isinstance(cid, str):
                continue
            if cid not in latest:
                order.append(cid)
            latest[cid] = record
        return [latest[cid] for cid in order]

    def current_session(self) -> dict[str, Any] | None:
        """Return the open session's payload (or None if all closed).

        "Current" is derived from the event log, not a pointer file: a session is open
        if its `start` event is the most recent event for that session_id and no `end`
        event has been recorded for it. Returns the session dict (unwrapped from the event).
        """
        events = self.read_session_events()
        seen_session_ids: set[str] = set()
        for event in reversed(events):
            sid = event.get("session", {}).get("session_id")
            if sid is None or sid in seen_session_ids:
                continue
            seen_session_ids.add(sid)
            if event.get("event") == "end":
                # this session is closed; ignore and keep scanning
                continue
            return event.get("session")
        return None

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Return the latest session payload (start or end) for the given session_id, or None."""
        events = self.read_session_events()
        for event in reversed(events):
            if event.get("session", {}).get("session_id") == session_id:
                return event.get("session")
        return None

    def list_sessions(self) -> list[dict[str, Any]]:
        """Return all closed session payloads, most-recently-ended first.

        Open sessions (no end event) are excluded — they belong in current_session().
        Each entry is the session dict (unwrapped from the event), not the event wrapper.
        """
        events = self.read_session_events()
        # Walk forward; track latest event per sid; keep only those with an end.
        latest_per_sid: dict[str, dict[str, Any]] = {}
        for event in events:
            sid = event.get("session", {}).get("session_id")
            if sid is None:
                continue
            latest_per_sid[sid] = event
        closed: list[dict[str, Any]] = [
            ev["session"]
            for ev in latest_per_sid.values()
            if ev.get("event") == "end" and ev.get("session") is not None
        ]
        closed.sort(
            key=lambda s: s.get("ended_at") or "",
            reverse=True,
        )
        return closed

    def _require_inside_memory(self, path: Path) -> None:
        path.resolve().relative_to(self.memory_dir.resolve())
