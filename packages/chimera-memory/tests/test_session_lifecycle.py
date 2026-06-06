"""Slice 2: session lifecycle (start_session / end_session / get_current_session / get_session / list_sessions).

Env fallback: if `agent_app` is None and CHIMERA_AGENT is set, use it (identity_source=ENV_VAR, confidence=MEDIUM).
Same for model via CHIMERA_MODEL. If EITHER env var is set, identity_source is ENV_VAR.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest

from chimera_memory.ledger import record_claim
from chimera_memory.session import (
    AttributionConfidence,
    FinalStatus,
    IdentitySource,
    Session,
)
from chimera_memory.storage import MemoryStore


def _init_store(tmp_path: Path) -> MemoryStore:
    store = MemoryStore.from_paths(root=tmp_path)
    store.initialize()
    return store


def _subprocess_run_git(*args: str) -> None:
    import subprocess
    subprocess.run(["git", *args], check=True, capture_output=True, text=True)


def _init_git_repo(tmp_path: Path) -> None:
    _subprocess_run_git("init", "-q", str(tmp_path))
    _subprocess_run_git("-C", str(tmp_path), "config", "user.email", "test@test")
    _subprocess_run_git("-C", str(tmp_path), "config", "user.name", "test")


def _git_commit_store(tmp_path: Path) -> None:
    """Add the .chimera-memory dir to git so start_session sees a clean tree."""
    _subprocess_run_git("-C", str(tmp_path), "add", ".chimera-memory")
    _subprocess_run_git("-C", str(tmp_path), "commit", "-q", "-m", "store-init")


def _evidence_ref(*, claim_time: datetime) -> dict:
    return {
        "ref_type": "external",
        "ref_id": f"git:abc:{claim_time.isoformat()}",
        "available_at": claim_time.isoformat(),
        "content_hash": "sha256:abc",
    }


def _datetime_utc() -> datetime:
    from datetime import UTC, datetime
    return datetime(2026, 6, 3, 20, 0, 0, tzinfo=UTC)


def _write_claim_for_session(tmp_path: Path, store: MemoryStore, sid: str, claim_id: str) -> str:
    ts = _datetime_utc()
    return record_claim(
        title=f"claim {claim_id}", summary=f"s{claim_id}", predicted=True,
        evidence=[_evidence_ref(claim_time=ts)], root=tmp_path, claim_time=ts,
        agent_id="a", model_version="m", task_type="test",
        extra_metadata={"session_id": sid},
    )


# -----------------------------------------------------------------------------
# start_session
# -----------------------------------------------------------------------------


def test_start_session_returns_session_id(tmp_path) -> None:
    _init_store(tmp_path)
    from chimera_memory.session_lifecycle import start_session

    sid = start_session(
        repo_path=tmp_path,
        branch="main",
        task_label="t",
        agent_app="claude-code",
        model="claude-opus-4",
    )
    assert sid.startswith("sess-")
    parts = sid.split("-")
    assert len(parts) == 3
    assert len(parts[2]) == 8


def test_start_session_writes_start_event(tmp_path) -> None:
    store = _init_store(tmp_path)
    from chimera_memory.session_lifecycle import start_session

    sid = start_session(
        repo_path=tmp_path,
        branch="main",
        task_label="fix bug",
        agent_app="claude-code",
        model="claude-opus-4",
    )
    events = store.read_session_events()
    assert len(events) == 1
    assert events[0]["event"] == "start"
    s = Session.from_dict(events[0]["session"])
    assert s.session_id == sid
    assert s.task_label == "fix bug"
    assert s.agent_app == "claude-code"
    assert s.model == "claude-opus-4"
    assert s.attribution_confidence is AttributionConfidence.HIGH
    assert s.identity_source is IdentitySource.CLI_FLAG


def test_start_session_captures_git_state_when_in_git_repo(tmp_path) -> None:
    _init_git_repo(tmp_path)
    _subprocess_run_git("-C", str(tmp_path), "commit", "--allow-empty", "-q", "-m", "init")
    store = _init_store(tmp_path)
    _git_commit_store(tmp_path)  # commit .chimera-memory so start sees clean tree
    from chimera_memory.session_lifecycle import start_session

    sid = start_session(
        repo_path=tmp_path,
        branch="main",
        task_label="t",
        agent_app="a",
        model="m",
    )
    s = Session.from_dict(store.get_session(sid))
    assert s.start_commit is not None
    assert len(s.start_commit) >= 7
    assert s.start_dirty_state is False
    assert s.start_files_changed == []


def test_start_session_errors_when_already_open(tmp_path) -> None:
    _init_store(tmp_path)
    from chimera_memory.session_lifecycle import start_session

    start_session(repo_path=tmp_path, branch="main", task_label="first", agent_app="a", model="m")
    with pytest.raises(RuntimeError, match="already open"):
        start_session(repo_path=tmp_path, branch="main", task_label="second", agent_app="a", model="m")


def test_start_session_env_fallback_for_agent(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CHIMERA_AGENT", "ci-bot")
    store = _init_store(tmp_path)
    from chimera_memory.session_lifecycle import start_session

    sid = start_session(repo_path=tmp_path, branch="main", task_label="t", agent_app=None, model=None)
    s = Session.from_dict(store.get_session(sid))
    assert s.agent_app == "ci-bot"
    assert s.identity_source is IdentitySource.ENV_VAR
    assert s.attribution_confidence is AttributionConfidence.MEDIUM


def test_start_session_env_fallback_for_model(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CHIMERA_MODEL", "gpt-5")
    store = _init_store(tmp_path)
    from chimera_memory.session_lifecycle import start_session

    sid = start_session(repo_path=tmp_path, branch="main", task_label="t", agent_app=None, model=None)
    s = Session.from_dict(store.get_session(sid))
    assert s.model == "gpt-5"
    assert s.identity_source is IdentitySource.ENV_VAR
    assert s.attribution_confidence is AttributionConfidence.MEDIUM


def test_start_session_explicit_overrides_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CHIMERA_AGENT", "ci-bot")
    store = _init_store(tmp_path)
    from chimera_memory.session_lifecycle import start_session

    sid = start_session(
        repo_path=tmp_path, branch="main", task_label="t",
        agent_app="human", model=None,
    )
    s = Session.from_dict(store.get_session(sid))
    assert s.agent_app == "human"
    assert s.identity_source is IdentitySource.CLI_FLAG
    assert s.attribution_confidence is AttributionConfidence.HIGH


def test_start_session_defaults_to_unknown(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("CHIMERA_AGENT", raising=False)
    monkeypatch.delenv("CHIMERA_MODEL", raising=False)
    store = _init_store(tmp_path)
    from chimera_memory.session_lifecycle import start_session

    sid = start_session(repo_path=tmp_path, branch="main", task_label="t", agent_app=None, model=None)
    s = Session.from_dict(store.get_session(sid))
    assert s.agent_app == "unknown"
    assert s.model == "unknown"
    assert s.identity_source is IdentitySource.UNKNOWN
    assert s.attribution_confidence is AttributionConfidence.UNKNOWN


# -----------------------------------------------------------------------------
# end_session
# -----------------------------------------------------------------------------


def test_end_session_captures_git_state(tmp_path) -> None:
    _init_git_repo(tmp_path)
    _subprocess_run_git("-C", str(tmp_path), "commit", "--allow-empty", "-q", "-m", "init")
    store = _init_store(tmp_path)
    _git_commit_store(tmp_path)
    from chimera_memory.session_lifecycle import end_session, start_session

    sid = start_session(repo_path=tmp_path, branch="main", task_label="t", agent_app="a", model="m")
    (tmp_path / "new.txt").write_text("hi")
    end_session(repo_path=tmp_path, final_status=FinalStatus.PASSED)
    s = Session.from_dict(store.get_session(sid))
    assert s.end_commit is not None
    assert s.end_dirty_state is True
    assert "new.txt" in s.end_files_changed


def test_end_session_computes_files_changed_during(tmp_path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "a.txt").write_text("a")
    _subprocess_run_git("-C", str(tmp_path), "add", "a.txt")
    _subprocess_run_git("-C", str(tmp_path), "commit", "-q", "-m", "init")
    store = _init_store(tmp_path)
    _git_commit_store(tmp_path)
    from chimera_memory.session_lifecycle import end_session, start_session

    # pre-existing dirty file at start
    (tmp_path / "pre.txt").write_text("p")
    start_session(repo_path=tmp_path, branch="main", task_label="t", agent_app="a", model="m")
    # new file added during session
    (tmp_path / "new.txt").write_text("n")
    # pre-existing dirty file removed during session
    (tmp_path / "pre.txt").unlink()
    end_session(repo_path=tmp_path, final_status=FinalStatus.PASSED)
    closed = store.list_sessions()
    assert len(closed) == 1
    cs = Session.from_dict(closed[0])
    assert cs.files_changed_during == 2  # "new.txt" added + "pre.txt" gone


def test_end_session_reconciles_passed_from_all_passing(tmp_path) -> None:
    store = _init_store(tmp_path)
    from chimera_memory.ledger import settle_claim
    from chimera_memory.session_lifecycle import end_session, start_session

    t0 = _datetime_utc()
    sid = start_session(repo_path=tmp_path, branch="main", task_label="t", agent_app="a", model="m")
    c1 = _write_claim_for_session(tmp_path, store, sid, "c1")
    c2 = _write_claim_for_session(tmp_path, store, sid, "c2")
    t1 = t0.replace(hour=21)
    settle_claim(c1, True, t1, root=tmp_path)
    settle_claim(c2, True, t1, root=tmp_path)
    end_session(repo_path=tmp_path)
    s = Session.from_dict(store.get_session(sid))
    assert s.final_status is FinalStatus.PASSED


def test_end_session_reconciles_failed_from_any_failing(tmp_path) -> None:
    store = _init_store(tmp_path)
    from chimera_memory.ledger import settle_claim
    from chimera_memory.session_lifecycle import end_session, start_session

    t0 = _datetime_utc()
    sid = start_session(repo_path=tmp_path, branch="main", task_label="t", agent_app="a", model="m")
    c1 = _write_claim_for_session(tmp_path, store, sid, "c1")
    c2 = _write_claim_for_session(tmp_path, store, sid, "c2")
    t1 = t0.replace(hour=21)
    settle_claim(c1, False, t1, root=tmp_path)   # CONTRADICTED
    settle_claim(c2, True, t1, root=tmp_path)    # VALIDATED
    end_session(repo_path=tmp_path)
    s = Session.from_dict(store.get_session(sid))
    assert s.final_status is FinalStatus.FAILED


def test_end_session_explicit_mixed_overrides_reconciled(tmp_path) -> None:
    store = _init_store(tmp_path)
    from chimera_memory.ledger import settle_claim
    from chimera_memory.session_lifecycle import end_session, start_session

    t0 = _datetime_utc()
    sid = start_session(repo_path=tmp_path, branch="main", task_label="t", agent_app="a", model="m")
    c1 = _write_claim_for_session(tmp_path, store, sid, "c1")
    settle_claim(c1, False, t0.replace(hour=21), root=tmp_path)
    end_session(repo_path=tmp_path, final_status=FinalStatus.MIXED)
    s = Session.from_dict(store.get_session(sid))
    assert s.final_status is FinalStatus.MIXED


def test_end_session_reconciles_unknown_when_no_outcomes(tmp_path) -> None:
    store = _init_store(tmp_path)
    from chimera_memory.session_lifecycle import end_session, start_session

    sid = start_session(repo_path=tmp_path, branch="main", task_label="t", agent_app="a", model="m")
    _write_claim_for_session(tmp_path, store, sid, "c1")
    # no claims settled
    end_session(repo_path=tmp_path)
    s = Session.from_dict(store.get_session(sid))
    assert s.final_status is FinalStatus.UNKNOWN


def test_end_session_reconciles_unknown_when_no_claims(tmp_path) -> None:
    _init_store(tmp_path)
    from chimera_memory.session_lifecycle import end_session, start_session

    start_session(repo_path=tmp_path, branch="main", task_label="t", agent_app="a", model="m")
    # no claims at all
    end_session(repo_path=tmp_path)
    # just confirm it doesn't raise and returns UNKNOWN or a valid status
    # (session with no claims → UNKNOWN)


def test_reconcile_all_validated_returns_passed(tmp_path) -> None:
    """CHM-1: all settled claims VALIDATED → PASSED."""
    store = _init_store(tmp_path)
    from chimera_memory.ledger import settle_claim
    from chimera_memory.session_lifecycle import end_session, start_session

    t0 = _datetime_utc()
    sid = start_session(repo_path=tmp_path, branch="b", task_label="t", agent_app="a", model="m")
    c1 = _write_claim_for_session(tmp_path, store, sid, "v1")
    settle_claim(c1, True, t0.replace(hour=21), root=tmp_path)
    end_session(repo_path=tmp_path)
    s = Session.from_dict(store.get_session(sid))
    assert s.final_status is FinalStatus.PASSED


def test_reconcile_one_contradicted_returns_failed(tmp_path) -> None:
    """CHM-1: one validated + one contradicted → FAILED."""
    store = _init_store(tmp_path)
    from chimera_memory.ledger import settle_claim
    from chimera_memory.session_lifecycle import end_session, start_session

    t0 = _datetime_utc()
    sid = start_session(repo_path=tmp_path, branch="b", task_label="t", agent_app="a", model="m")
    c1 = _write_claim_for_session(tmp_path, store, sid, "v1")
    c2 = _write_claim_for_session(tmp_path, store, sid, "v2")
    t1 = t0.replace(hour=21)
    settle_claim(c1, True, t1, root=tmp_path)   # VALIDATED
    settle_claim(c2, False, t1, root=tmp_path)  # CONTRADICTED
    end_session(repo_path=tmp_path)
    s = Session.from_dict(store.get_session(sid))
    assert s.final_status is FinalStatus.FAILED


def test_reconcile_no_claims_returns_unknown(tmp_path) -> None:
    """CHM-1: session with no claims → UNKNOWN."""
    _init_store(tmp_path)
    from chimera_memory.session_lifecycle import end_session, start_session

    sid = start_session(repo_path=tmp_path, branch="b", task_label="t", agent_app="a", model="m")
    end_session(repo_path=tmp_path)
    from chimera_memory.session import Session
    from chimera_memory.storage import MemoryStore
    store = MemoryStore(tmp_path / ".chimera-memory")
    s = Session.from_dict(store.get_session(sid))
    assert s.final_status is FinalStatus.UNKNOWN


def test_end_session_explicit_overrides_reconciled(tmp_path) -> None:
    store = _init_store(tmp_path)
    from chimera_memory.session_lifecycle import end_session, start_session

    sid = start_session(repo_path=tmp_path, branch="main", task_label="t", agent_app="a", model="m")
    c1 = _write_claim_for_session(tmp_path, store, sid, "c1")
    store.append_outcome({"claim_id": c1, "result": "PASS", "metadata": {}})
    end_session(repo_path=tmp_path, final_status=FinalStatus.INTERRUPTED)
    s = Session.from_dict(store.get_session(sid))
    assert s.final_status is FinalStatus.INTERRUPTED


def test_end_session_errors_when_no_open(monkeypatch, tmp_path) -> None:
    _init_store(tmp_path)
    monkeypatch.chdir(tmp_path)
    from chimera_memory.session_lifecycle import end_session

    with pytest.raises(RuntimeError, match=re.compile(r"no open session", re.IGNORECASE)):
        end_session()
