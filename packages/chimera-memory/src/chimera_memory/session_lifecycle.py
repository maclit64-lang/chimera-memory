"""Session lifecycle: start_session / end_session.

Local-first, append-only. Writes start/end events to a single
`<memory_dir>/sessions.jsonl` (the same store the rest of chimera-memory uses).

Honest attribution: env fallback to CHIMERA_AGENT / CHIMERA_MODEL with
identity_source=ENV_VAR / confidence=MEDIUM. If the env vars are unset, defaults
are "unknown" / UNKNOWN — we never fake precision.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chimera_memory.adapters.git import capture_git_evidence
from chimera_memory.session import (
    AttributionConfidence,
    FinalStatus,
    IdentitySource,
    Session,
    new_session_id,
)
from chimera_memory.storage import MemoryStore


def start_session(
    *,
    repo_path: str | Path,
    branch: str,
    task_label: str,
    agent_app: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    harness_id: str | None = None,
    attribution_confidence: AttributionConfidence | None = None,
    identity_source: IdentitySource | None = None,
    root: str | Path | None = None,
    memory_dir: str | Path | None = None,
    store_path: str | Path | None = None,
) -> str:
    """Open a new session. Returns the session_id."""
    store = MemoryStore.from_paths(root=repo_path)
    store.initialize()

    # ----- Resolve agent_app: caller > CHIMERA_AGENT > "unknown" -----
    explicit_agent = agent_app is not None
    if agent_app is None:
        agent_app = os.environ.get("CHIMERA_AGENT")
    if agent_app is None:
        agent_app = "unknown"

    # ----- Resolve model: caller > CHIMERA_MODEL > "unknown" -----
    if model is None:
        model = os.environ.get("CHIMERA_MODEL")
    if model is None:
        model = "unknown"

    # ----- Resolve identity_source -----
    if identity_source is None:
        if explicit_agent:
            identity_source = IdentitySource.CLI_FLAG
        elif os.environ.get("CHIMERA_AGENT") or os.environ.get("CHIMERA_MODEL"):
            identity_source = IdentitySource.ENV_VAR
        else:
            identity_source = IdentitySource.UNKNOWN

    # ----- Resolve attribution_confidence -----
    if attribution_confidence is None:
        if identity_source is IdentitySource.CLI_FLAG:
            attribution_confidence = AttributionConfidence.HIGH
        elif identity_source is IdentitySource.ENV_VAR:
            attribution_confidence = AttributionConfidence.MEDIUM
        else:
            attribution_confidence = AttributionConfidence.UNKNOWN

    # ----- Refuse to start a second session while one is already open -----
    current = store.current_session()
    if current is not None:
        raise RuntimeError(
            f"Session {current['session_id']} is already open. "
            f"End it with `chimera-memory session end` before starting a new one."
        )

    # ----- Capture git state at start (best-effort) -----
    start_commit, start_dirty, start_files, start_branch_from_git = _capture_git(repo_path)
    session_branch = branch or start_branch_from_git or "unknown"

    sid = new_session_id()
    session = Session(
        session_id=sid,
        repo_path=str(repo_path),
        branch=session_branch,
        task_label=task_label,
        agent_app=agent_app,
        provider=provider,
        model=model,
        harness_id=harness_id,
        attribution_confidence=attribution_confidence,
        identity_source=identity_source,
        started_at=datetime.now(UTC).isoformat(),
        start_commit=start_commit,
        start_dirty_state=start_dirty,
        start_files_changed=start_files,
    )
    store.append_session_event({"event": "start", "session": session.to_dict()})
    return sid


def end_session(
    *,
    repo_path: str | Path | None = None,
    final_status: FinalStatus | None = None,
    root: str | Path | None = None,
    memory_dir: str | Path | None = None,
    store_path: str | Path | None = None,
) -> str:
    """Close the currently-open session. Returns the session_id.

    Locates the open session by probing the store at `repo_path` (or cwd if
    not given). On close, captures end-state git evidence, computes
    files-changed-during, and either honors the caller-supplied final_status
    or reconciles it from outcomes of claims tagged with this session_id.
    """
    open_session = _find_open_session(
        repo_path=repo_path, root=root, memory_dir=memory_dir, store_path=store_path
    )
    if open_session is None:
        raise RuntimeError(
            "No open session to end. Start one with `chimera-memory session start` first."
        )

    store = MemoryStore.from_paths(root=open_session.repo_path)

    # ----- Capture git state at end (best-effort) -----
    end_commit, end_dirty, end_files, _end_branch = _capture_git(open_session.repo_path)

    # ----- Compute files changed DURING this session -----
    # Exclude the session's own bookkeeping (.chimera-memory/*) — those are
    # ledger data, not "work" done during the session.
    def _is_ledger_path(p: str) -> bool:
        return ".chimera-memory/" in p or p.startswith(".chimera-memory") or p == ".chimera-memory"

    start_set = {p for p in (open_session.start_files_changed or []) if not _is_ledger_path(p)}
    end_set = {p for p in end_files if not _is_ledger_path(p)}
    new_during = end_set - start_set        # files that became dirty
    gone_during = start_set - end_set        # files that got committed/removed
    files_changed_during = len(new_during) + len(gone_during)

    # ----- Reconcile final_status if not explicitly provided -----
    if final_status is None:
        final_status = _reconcile_final_status(store, open_session.session_id)

    # ----- Build and write the end event -----
    closed_payload: dict[str, Any] = {
        **open_session.to_dict(),
        "ended_at": datetime.now(UTC).isoformat(),
        "end_commit": end_commit,
        "end_dirty_state": end_dirty,
        "end_files_changed": end_files,
        "files_changed_during": files_changed_during,
        "final_status": final_status.value,
    }
    closed = Session.from_dict(closed_payload)
    store.append_session_event({"event": "end", "session": closed.to_dict()})
    return closed.session_id


# -----------------------------------------------------------------------------
# helpers
# -----------------------------------------------------------------------------


def _find_open_session(
    *,
    repo_path: str | Path | None = None,
    root: str | Path | None = None,
    memory_dir: str | Path | None = None,
    store_path: str | Path | None = None,
) -> Session | None:
    """Locate the open session by probing the store. Returns None if not found."""
    if store_path is not None:
        probe = MemoryStore.from_paths(store_path=store_path)
    elif memory_dir is not None:
        probe = MemoryStore.from_paths(memory_dir=memory_dir)
    elif repo_path is not None:
        probe = MemoryStore.from_paths(root=repo_path)
    elif root is not None:
        probe = MemoryStore.from_paths(root=root)
    else:
        probe = MemoryStore.from_paths()  # cwd fallback for CLI

    current = probe.current_session()
    if current is None:
        return None
    return Session.from_dict(current)


def _capture_git(repo_path: str | Path) -> tuple[str, bool, list[str], str]:
    """Return (commit_sha, dirty_state, files_changed, branch).

    If git is unavailable, all are "unknown".
    """
    try:
        _evidence, meta = capture_git_evidence(root=repo_path, claim_time=datetime.now(UTC))
    except Exception:
        return "unknown", False, [], "unknown"
    if not meta.get("git_available", False):
        return "unknown", False, [], "unknown"
    commit = str(meta.get("commit_sha") or "unknown")
    dirty = bool(meta.get("dirty_state", False))
    raw_files = meta.get("files_changed")
    files = list(raw_files) if isinstance(raw_files, list) else []
    branch = str(meta.get("branch") or "unknown")
    return commit, dirty, files, branch


def _reconcile_final_status(store: MemoryStore, session_id: str) -> FinalStatus:
    """Derive final_status from claim_status of claims tagged with this session_id.

    Rule (ordered):
      - no claims for this session                     → UNKNOWN
      - any claim_status == CONTRADICTED               → FAILED
      - all settled claims are VALIDATED               → PASSED
      - mixed settled states (some VALIDATED, others)  → MIXED
      - no settled claims                              → UNKNOWN
    """
    claims = store.read_claims()
    session_claims = [
        c for c in claims
        if isinstance(c.metadata, dict) and c.metadata.get("session_id") == session_id
    ]
    if not session_claims:
        return FinalStatus.UNKNOWN

    from chimera_memory_types.knowledge import ClaimStatus

    settled = [
        c for c in session_claims
        if c.claim_status in {ClaimStatus.VALIDATED, ClaimStatus.CONTRADICTED}
    ]
    if not settled:
        return FinalStatus.UNKNOWN

    statuses = {c.claim_status for c in settled}
    if ClaimStatus.CONTRADICTED in statuses:
        return FinalStatus.FAILED
    if statuses == {ClaimStatus.VALIDATED}:
        return FinalStatus.PASSED
    return FinalStatus.MIXED


# -----------------------------------------------------------------------------
# query wrappers (public API)
# -----------------------------------------------------------------------------


def get_current_session(
    *,
    root: str | Path | None = None,
    memory_dir: str | Path | None = None,
    store_path: str | Path | None = None,
) -> dict[str, object] | None:
    """Return the open session's dict (or None if all closed).

    Resolves the store via the same convention as start_session.
    """
    store = MemoryStore.from_paths(root=root, memory_dir=memory_dir, store_path=store_path)
    return store.current_session()


def get_session(
    session_id: str,
    *,
    root: str | Path | None = None,
    memory_dir: str | Path | None = None,
    store_path: str | Path | None = None,
) -> dict[str, object] | None:
    """Return the latest event for a given session_id (or None)."""
    store = MemoryStore.from_paths(root=root, memory_dir=memory_dir, store_path=store_path)
    return store.get_session(session_id)


def list_sessions(
    *,
    root: str | Path | None = None,
    memory_dir: str | Path | None = None,
    store_path: str | Path | None = None,
) -> list[dict[str, object]]:
    """Return all closed sessions as a list of dicts (most recent first)."""
    store = MemoryStore.from_paths(root=root, memory_dir=memory_dir, store_path=store_path)
    return store.list_sessions()
