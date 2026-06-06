"""Tests for CHIMERA_DQ_NO_WRITE=1 no-write wrap mode."""

from __future__ import annotations

import sys

import pytest

from chimera_memory.cli import main
from chimera_memory.storage import MemoryStore


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _init_with_session(tmp_path):
    main(["init"])
    main(["session", "start", "--branch", "t", "--task-label", "t",
          "--agent", "a", "--model", "m", "--harness-id", "h"])


# ---------------------------------------------------------------------------
# No-write mode: exit code passthrough + no ledger writes
# ---------------------------------------------------------------------------


def test_dq_no_write_propagates_exit_code(tmp_path, monkeypatch):
    """CHIMERA_DQ_NO_WRITE=1: wrap still exits with wrapped command exit code."""
    _init_with_session(tmp_path)
    monkeypatch.setenv("CHIMERA_DQ_NO_WRITE", "1")
    result = main(["wrap", "--failure-origin", "organic_real",
                   "--verification-scope", "package", "--scope-path", str(tmp_path),
                   "--", sys.executable, "-c", "import sys; sys.exit(3)"])
    assert result == 3


def test_dq_no_write_writes_zero_claims(tmp_path, monkeypatch):
    """CHIMERA_DQ_NO_WRITE=1: no claim written to ledger."""
    _init_with_session(tmp_path)
    monkeypatch.setenv("CHIMERA_DQ_NO_WRITE", "1")
    main(["wrap", "--failure-origin", "organic_real",
          "--verification-scope", "package", "--scope-path", str(tmp_path),
          "--", sys.executable, "-c", "print('ok')"])
    store = MemoryStore.from_paths(root=tmp_path)
    claims = store.read_claims()
    assert len(claims) == 0, f"expected 0 claims, got {len(claims)}"


def test_dq_no_write_prints_notice(tmp_path, monkeypatch, capsys):
    """CHIMERA_DQ_NO_WRITE=1: prints the no-write notice."""
    _init_with_session(tmp_path)
    monkeypatch.setenv("CHIMERA_DQ_NO_WRITE", "1")
    main(["wrap", "--failure-origin", "organic_real",
          "--verification-scope", "package", "--scope-path", str(tmp_path),
          "--", sys.executable, "-c", "print('ok')"])
    out = capsys.readouterr().out
    assert "CHIMERA_DQ_NO_WRITE" in out


# ---------------------------------------------------------------------------
# Normal mode (env var absent): still writes
# ---------------------------------------------------------------------------


def test_normal_wrap_writes_claim(tmp_path, monkeypatch):
    """Without CHIMERA_DQ_NO_WRITE, wrap writes a claim as normal."""
    monkeypatch.delenv("CHIMERA_DQ_NO_WRITE", raising=False)
    _init_with_session(tmp_path)
    main(["wrap", "--failure-origin", "organic_real",
          "--verification-scope", "package", "--scope-path", str(tmp_path),
          "--", sys.executable, "-c", "print('ok')"])
    store = MemoryStore.from_paths(root=tmp_path)
    claims = store.read_claims()
    assert len(claims) >= 1


# ---------------------------------------------------------------------------
# Exit-code test no longer needs test_first_contract workaround
# ---------------------------------------------------------------------------


def test_wrap_propagates_exit_code_no_ledger_pollution(tmp_path, monkeypatch):
    """Using CHIMERA_DQ_NO_WRITE=1 for the fixture: exit code propagates, zero ledger writes."""
    _init_with_session(tmp_path)
    monkeypatch.setenv("CHIMERA_DQ_NO_WRITE", "1")
    result = main(["wrap", "--failure-origin", "organic_real",
                   "--verification-scope", "package", "--scope-path", str(tmp_path),
                   "--", sys.executable, "-c", "import sys; sys.exit(7)"])
    assert result == 7
    store = MemoryStore.from_paths(root=tmp_path)
    assert len(store.read_claims()) == 0
