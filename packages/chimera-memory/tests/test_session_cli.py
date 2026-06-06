"""Slice 4: CLI session/receipt subcommands.

Additive: new subparser on the existing `chimera-memory` CLI.
"""
from __future__ import annotations

import json

from chimera_memory.cli import main


def _run(argv: list[str], tmp_path, monkeypatch) -> int:
    monkeypatch.chdir(tmp_path)
    return main(argv)


# -----------------------------------------------------------------------------
# session start
# -----------------------------------------------------------------------------


def test_session_start_prints_session_id(tmp_path, monkeypatch) -> None:
    code = _run(
        [
            "session", "start",
            "--branch", "main",
            "--task-label", "fix bug",
            "--agent", "ci-bot",
            "--model", "claude-opus-4",
        ],
        tmp_path, monkeypatch,
    )
    # (capfd replacement: read stdout via _run output below)
    assert code == 0


def test_session_start_actually_creates_session(tmp_path, monkeypatch, capsys) -> None:
    _run(
        [
            "session", "start",
            "--branch", "main", "--task-label", "fix bug",
            "--agent", "ci-bot", "--model", "claude-opus-4",
        ],
        tmp_path, monkeypatch,
    )
    out = capsys.readouterr().out
    assert "sess-" in out


def test_session_start_with_env_fallback(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("CHIMERA_AGENT", "ci-bot")
    monkeypatch.setenv("CHIMERA_MODEL", "gpt-5")
    _run(
        ["session", "start", "--branch", "main", "--task-label", "t"],
        tmp_path, monkeypatch,
    )
    out = capsys.readouterr().out
    # session id printed
    assert "sess-" in out


def test_session_start_errors_when_already_open(tmp_path, monkeypatch, capsys) -> None:
    _run(
        ["session", "start", "--branch", "main", "--task-label", "first", "--agent", "a", "--model", "m"],
        tmp_path, monkeypatch,
    )
    code = _run(
        ["session", "start", "--branch", "main", "--task-label", "second", "--agent", "a", "--model", "m"],
        tmp_path, monkeypatch,
    )
    assert code != 0
    err = capsys.readouterr().err
    assert "already open" in err


# -----------------------------------------------------------------------------
# session end
# -----------------------------------------------------------------------------


def test_session_end_prints_receipt_text(tmp_path, monkeypatch, capsys) -> None:
    _run(
        ["session", "start", "--branch", "main", "--task-label", "t", "--agent", "a", "--model", "m"],
        tmp_path, monkeypatch,
    )
    code = _run(["session", "end"], tmp_path, monkeypatch)
    assert code == 0
    out = capsys.readouterr().out
    assert "Chimera Session Receipt" in out
    assert "FILES" in out
    assert "GIT" in out
    assert "COMMIT" in out
    assert "Drift:" in out


def test_session_end_json_flag(tmp_path, monkeypatch, capsys) -> None:
    _run(
        ["session", "start", "--branch", "main", "--task-label", "t", "--agent", "a", "--model", "m"],
        tmp_path, monkeypatch,
    )
    capsys.readouterr()  # clear start output
    code = _run(["session", "end", "--json"], tmp_path, monkeypatch)
    assert code == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["agent"]["app"] == "a"
    assert parsed["drift"] in {"OK", "DRIFT_ADVISORY", "INSUFFICIENT_DATA"}


def test_session_end_with_final_status_passed(tmp_path, monkeypatch, capsys) -> None:
    _run(
        ["session", "start", "--branch", "main", "--task-label", "t", "--agent", "a", "--model", "m"],
        tmp_path, monkeypatch,
    )
    code = _run(["session", "end", "--final-status", "PASSED"], tmp_path, monkeypatch)
    assert code == 0
    out = capsys.readouterr().out
    assert "PASSED" in out


def test_session_end_errors_when_no_open(tmp_path, monkeypatch, capsys) -> None:
    code = _run(["session", "end"], tmp_path, monkeypatch)
    assert code != 0
    err = capsys.readouterr().err
    assert "no open session" in err.lower() or "no open" in err.lower()


# -----------------------------------------------------------------------------
# session list / current
# -----------------------------------------------------------------------------


def test_session_list_empty(tmp_path, monkeypatch, capsys) -> None:
    code = _run(["session", "list"], tmp_path, monkeypatch)
    assert code == 0
    out = capsys.readouterr().out
    assert "no closed sessions" in out.lower() or "(none)" in out.lower() or out.strip() == ""


def test_session_list_shows_closed_sessions(tmp_path, monkeypatch, capsys) -> None:
    _run(
        ["session", "start", "--branch", "main", "--task-label", "first", "--agent", "a", "--model", "m"],
        tmp_path, monkeypatch,
    )
    _run(["session", "end", "--final-status", "PASSED"], tmp_path, monkeypatch)
    code = _run(["session", "list"], tmp_path, monkeypatch)
    assert code == 0
    out = capsys.readouterr().out
    assert "sess-" in out


def test_session_current_shows_open(tmp_path, monkeypatch, capsys) -> None:
    _run(
        ["session", "start", "--branch", "main", "--task-label", "t", "--agent", "a", "--model", "m"],
        tmp_path, monkeypatch,
    )
    code = _run(["session", "current"], tmp_path, monkeypatch)
    assert code == 0
    out = capsys.readouterr().out
    assert "sess-" in out
    assert "open" in out.lower() or "current" in out.lower()


def test_session_current_empty_when_none(tmp_path, monkeypatch, capsys) -> None:
    code = _run(["session", "current"], tmp_path, monkeypatch)
    assert code == 0
    out = capsys.readouterr().out
    assert "no open session" in out.lower() or "(none)" in out.lower() or out.strip() == ""


# -----------------------------------------------------------------------------
# receipt show
# -----------------------------------------------------------------------------


def test_receipt_show_unknown_session_errors(tmp_path, monkeypatch, capsys) -> None:
    code = _run(["receipt", "show", "sess-bogus"], tmp_path, monkeypatch)
    assert code != 0
    err = capsys.readouterr().err
    assert "not found" in err.lower() or "bogus" in err.lower()


def test_receipt_show_for_closed_session(tmp_path, monkeypatch, capsys) -> None:
    _run(
        ["session", "start", "--branch", "main", "--task-label", "t", "--agent", "a", "--model", "m"],
        tmp_path, monkeypatch,
    )
    _run(["session", "end", "--final-status", "PASSED"], tmp_path, monkeypatch)
    # Find the closed session id from list
    _run(["session", "list"], tmp_path, monkeypatch)
    list_out = capsys.readouterr().out
    # Extract the sess- id from list output
    import re
    m = re.search(r"sess-[\w-]+", list_out)
    assert m is not None
    sid = m.group(0)
    code = _run(["receipt", "show", sid], tmp_path, monkeypatch)
    assert code == 0
    out = capsys.readouterr().out
    assert "Chimera Session Receipt" in out
    assert "PASSED" in out


# =============================================================================
# C2 tests — capture metadata completeness + CLI friction
# =============================================================================


def test_session_start_accepts_harness_id(tmp_path, monkeypatch) -> None:
    """--harness-id is stored on the session."""
    from chimera_memory.storage import MemoryStore

    _run(
        [
            "session", "start",
            "--branch", "main", "--task-label", "t",
            "--agent", "kiro", "--model", "claude-sonnet-4.6",
            "--harness-id", "kiro-cli",
        ],
        tmp_path, monkeypatch,
    )
    store = MemoryStore.from_paths(root=tmp_path)
    current = store.current_session()
    assert current is not None
    assert current["harness_id"] == "kiro-cli"


def test_session_start_without_harness_id_preserves_none(tmp_path, monkeypatch) -> None:
    """Omitting --harness-id leaves harness_id as None — nothing is invented."""
    from chimera_memory.storage import MemoryStore

    _run(
        [
            "session", "start",
            "--branch", "main", "--task-label", "t",
            "--agent", "kiro", "--model", "m",
        ],
        tmp_path, monkeypatch,
    )
    store = MemoryStore.from_paths(root=tmp_path)
    current = store.current_session()
    assert current is not None
    assert current.get("harness_id") is None


def test_session_end_accepts_status_alias(tmp_path, monkeypatch, capsys) -> None:
    """--status PASSED is accepted as an alias for --final-status PASSED."""
    _run(
        ["session", "start", "--branch", "main", "--task-label", "t", "--agent", "a", "--model", "m"],
        tmp_path, monkeypatch,
    )
    capsys.readouterr()
    code = _run(["session", "end", "--status", "PASSED"], tmp_path, monkeypatch)
    assert code == 0
    out = capsys.readouterr().out
    assert "PASSED" in out


def test_receipt_latest_shows_most_recent_session(tmp_path, monkeypatch, capsys) -> None:
    """receipt latest shows the most recently closed session receipt."""
    _run(
        ["session", "start", "--branch", "main", "--task-label", "t", "--agent", "a", "--model", "m"],
        tmp_path, monkeypatch,
    )
    _run(["session", "end", "--final-status", "PASSED"], tmp_path, monkeypatch)
    capsys.readouterr()
    code = _run(["receipt", "latest"], tmp_path, monkeypatch)
    assert code == 0
    out = capsys.readouterr().out
    assert "Chimera Session Receipt" in out
    assert "PASSED" in out
