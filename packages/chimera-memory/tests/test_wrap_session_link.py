"""Slice 5: auto-link wrap claims to the active session via metadata.session_id.

When `wrap` runs while a session is open, the claim's metadata must include
`session_id` so the receipt can later correlate claims to the session.
"""
from __future__ import annotations

from pathlib import Path

from chimera_memory.cli import main
from chimera_memory.storage import MemoryStore


def _init_store(tmp_path: Path) -> MemoryStore:
    store = MemoryStore.from_paths(root=tmp_path)
    store.initialize()
    return store


def _seed_passing_test(tmp_path: Path) -> None:
    """Write a tiny passing test so `pytest -q` exits 0."""
    (tmp_path / "test_pass.py").write_text("def test_pass():\n    assert True\n")


def _run(argv: list[str], tmp_path, monkeypatch) -> int:
    monkeypatch.chdir(tmp_path)
    return main(argv)


def _claim_session_id(tmp_path) -> str | None:
    """Read the most recent claim's metadata.session_id (or None)."""
    store = MemoryStore.from_paths(root=tmp_path)
    claims = store.read_claims()
    if not claims:
        return None
    return (claims[-1].metadata or {}).get("session_id")


# -----------------------------------------------------------------------------
# tests
# -----------------------------------------------------------------------------


def test_wrap_without_session_does_not_set_session_id(tmp_path, monkeypatch) -> None:
    """No open session → no session_id in claim metadata."""
    _init_store(tmp_path)
    _seed_passing_test(tmp_path)
    code = _run(["wrap", "pytest", "-q", "test_pass.py"], tmp_path, monkeypatch)
    assert code == 0
    sid = _claim_session_id(tmp_path)
    assert sid is None


def test_wrap_with_active_session_includes_session_id(tmp_path, monkeypatch) -> None:
    """Active session → session_id in claim metadata matches the open session."""
    _init_store(tmp_path)
    _seed_passing_test(tmp_path)
    _run(
        ["session", "start", "--branch", "main", "--task-label", "t",
         "--agent", "a", "--model", "m"],
        tmp_path, monkeypatch,
    )
    store = MemoryStore.from_paths(root=tmp_path)
    current = store.current_session()
    assert current is not None
    open_sid = current["session_id"]

    code = _run(["wrap", "pytest", "-q", "test_pass.py"], tmp_path, monkeypatch)
    assert code == 0
    claim_sid = _claim_session_id(tmp_path)
    assert claim_sid == open_sid


def test_wrap_does_not_break_existing_extra_metadata(tmp_path, monkeypatch) -> None:
    """Auto-link must merge with existing extra_metadata, not replace it."""
    _init_store(tmp_path)
    _seed_passing_test(tmp_path)
    _run(
        ["session", "start", "--branch", "main", "--task-label", "t",
         "--agent", "a", "--model", "m"],
        tmp_path, monkeypatch,
    )
    _run(["wrap", "pytest", "-q", "test_pass.py"], tmp_path, monkeypatch)

    store = MemoryStore.from_paths(root=tmp_path)
    claims = store.read_claims()
    assert claims
    meta = claims[-1].metadata or {}
    # session_id was added
    assert "session_id" in meta
    # but the original `git` metadata (set by _wrap_pytest) is still there
    assert "git" in meta


def test_wrap_session_id_is_stable_across_wraps_in_same_session(
    tmp_path, monkeypatch
) -> None:
    """Multiple wraps in the same session all share the same session_id."""
    _init_store(tmp_path)
    _seed_passing_test(tmp_path)
    _run(
        ["session", "start", "--branch", "main", "--task-label", "t",
         "--agent", "a", "--model", "m"],
        tmp_path, monkeypatch,
    )
    store = MemoryStore.from_paths(root=tmp_path)
    open_sid = store.current_session()["session_id"]

    for _ in range(2):
        _run(["wrap", "pytest", "-q", "test_pass.py"], tmp_path, monkeypatch)

    claims = store.read_claims()
    # settle_claim appends an updated record, so each wrap → 2 rows. Dedup by claim_id
    # and keep the first occurrence (the proposed record, which carries the auto-link).
    seen: set[str] = set()
    sids: list[str | None] = []
    for c in claims:
        cid = getattr(c, "claim_id", None) or (c.metadata or {}).get("claim_id")
        if cid in seen:
            continue
        seen.add(cid)
        sids.append((c.metadata or {}).get("session_id"))
    assert sids == [open_sid, open_sid]


# =============================================================================
# C1 tests — session attribution propagation
# =============================================================================


def _latest_claim_metadata(tmp_path: Path) -> dict:
    store = MemoryStore.from_paths(root=tmp_path)
    claims = store.read_claims()
    assert claims, "no claims recorded"
    return claims[-1].metadata or {}


def test_wrap_inherits_active_session_attribution(tmp_path, monkeypatch) -> None:
    """Active session attribution is inherited by the wrapped claim."""
    from chimera_memory.session_lifecycle import start_session

    _init_store(tmp_path)
    _seed_passing_test(tmp_path)
    monkeypatch.chdir(tmp_path)

    sid = start_session(
        repo_path=tmp_path,
        branch="main",
        task_label="c1-test",
        agent_app="claude-code",
        model="claude-sonnet-4.6",
        harness_id="claude-code-cli",
    )
    # agent provided → identity_source=cli_flag, attribution_confidence=high

    _run(["wrap", "pytest", "-q", "test_pass.py"], tmp_path, monkeypatch)

    meta = _latest_claim_metadata(tmp_path)
    assert meta["session_id"] == sid
    assert meta["agent_id"] == "claude-code"
    assert meta["model_version"] == "claude-sonnet-4.6"
    assert meta["harness_id"] == "claude-code-cli"
    assert meta["attribution_confidence"] == "high"
    assert meta["identity_source"] == "cli_flag"


def test_wrap_explicit_flags_override_session_attribution(tmp_path, monkeypatch) -> None:
    """Explicit --agent/--model/--task-type flags override active session values."""
    from chimera_memory.session_lifecycle import start_session

    _init_store(tmp_path)
    _seed_passing_test(tmp_path)
    monkeypatch.chdir(tmp_path)

    sid = start_session(
        repo_path=tmp_path,
        branch="main",
        task_label="override-test",
        agent_app="kiro",
        model="unknown",
    )

    _run(
        ["wrap", "--agent", "codex", "--model", "gpt-5", "--task-type", "schema",
         "pytest", "-q", "test_pass.py"],
        tmp_path, monkeypatch,
    )

    meta = _latest_claim_metadata(tmp_path)
    assert meta["session_id"] == sid
    assert meta["agent_id"] == "codex"
    assert meta["model_version"] == "gpt-5"
    assert meta["task_type"] == "schema"


def test_wrap_without_active_session_preserves_existing_defaults(tmp_path, monkeypatch) -> None:
    """No active session → backward-compatible defaults are preserved."""
    _init_store(tmp_path)
    _seed_passing_test(tmp_path)

    _run(["wrap", "pytest", "-q", "test_pass.py"], tmp_path, monkeypatch)

    meta = _latest_claim_metadata(tmp_path)
    assert "session_id" not in meta
    assert meta["agent_id"] == "unknown-agent"
    assert meta.get("model_version") is None
    assert meta["task_type"] == "test"


def test_wrap_unknown_session_model_stays_unknown(tmp_path, monkeypatch) -> None:
    """model='unknown' in session is stored as 'unknown', not converted to None."""
    from chimera_memory.session_lifecycle import start_session

    _init_store(tmp_path)
    _seed_passing_test(tmp_path)
    monkeypatch.chdir(tmp_path)

    start_session(
        repo_path=tmp_path,
        branch="main",
        task_label="unknown-model",
        agent_app="claude-code",
        model="unknown",
    )

    _run(["wrap", "pytest", "-q", "test_pass.py"], tmp_path, monkeypatch)

    meta = _latest_claim_metadata(tmp_path)
    assert meta["model_version"] == "unknown"
    assert meta["model_version"] is not None
    assert meta["agent_id"] == "claude-code"


def test_wrap_inherits_session_harness_id(tmp_path, monkeypatch) -> None:
    """Wrap inherits harness_id from an active session that was started with --harness-id."""
    from chimera_memory.session_lifecycle import start_session

    _init_store(tmp_path)
    _seed_passing_test(tmp_path)
    monkeypatch.chdir(tmp_path)

    start_session(
        repo_path=tmp_path,
        branch="main",
        task_label="harness-test",
        agent_app="kiro",
        model="claude-sonnet-4.6",
        harness_id="kiro-cli",
    )

    _run(["wrap", "pytest", "-q", "test_pass.py"], tmp_path, monkeypatch)

    meta = _latest_claim_metadata(tmp_path)
    assert meta["harness_id"] == "kiro-cli"


def test_wrap_task_type_flag_records_metadata(tmp_path, monkeypatch) -> None:
    """--task-type schema records task_type=schema in claim metadata."""
    _init_store(tmp_path)
    _seed_passing_test(tmp_path)

    _run(
        ["wrap", "--task-type", "schema", "pytest", "-q", "test_pass.py"],
        tmp_path, monkeypatch,
    )

    meta = _latest_claim_metadata(tmp_path)
    assert meta["task_type"] == "schema"
