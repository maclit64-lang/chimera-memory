"""F1A: Tests for generic command wrapping by exit code."""
from __future__ import annotations

import sys
from pathlib import Path

from chimera_memory_types.knowledge import ClaimStatus

from chimera_memory.cli import main
from chimera_memory.session_lifecycle import start_session
from chimera_memory.storage import MemoryStore


def _init(tmp_path: Path) -> MemoryStore:
    store = MemoryStore.from_paths(root=tmp_path)
    store.initialize()
    return store


def _latest_settled_claim(tmp_path: Path):
    store = MemoryStore.from_paths(root=tmp_path)
    claims = store.latest_claims()
    settled = [c for c in claims if c.claim_status in (
        ClaimStatus.VALIDATED, ClaimStatus.CONTRADICTED
    )]
    assert settled, "no settled claims found"
    return settled[-1]


def _run(argv: list[str], tmp_path: Path, monkeypatch) -> int:
    monkeypatch.chdir(tmp_path)
    return main(argv)


# ---------------------------------------------------------------------------
# Test 1 — generic command success → VALIDATED
# ---------------------------------------------------------------------------


def test_wrap_generic_command_success_records_validated_claim(
    tmp_path, monkeypatch
) -> None:
    _init(tmp_path)
    code = _run(
        ["wrap", "--task-type", "cli", "--", sys.executable, "-c", "print('ok')"],
        tmp_path, monkeypatch,
    )
    assert code == 0
    claim = _latest_settled_claim(tmp_path)
    assert claim.claim_status == ClaimStatus.VALIDATED
    meta = claim.metadata or {}
    assert meta["task_type"] == "cli"
    # wrapped_args stored in settlement event
    evt_meta = claim.settlement.events[-1].metadata
    assert sys.executable in " ".join(str(a) for a in evt_meta["wrapped_args"])


# ---------------------------------------------------------------------------
# Test 2 — generic command failure → CONTRADICTED (the most important test)
# ---------------------------------------------------------------------------


def test_wrap_generic_command_failure_records_contradicted_claim(
    tmp_path, monkeypatch
) -> None:
    _init(tmp_path)
    code = _run(
        ["wrap", "--task-type", "lint", "--", sys.executable, "-c", "raise SystemExit(3)"],
        tmp_path, monkeypatch,
    )
    assert code == 3
    claim = _latest_settled_claim(tmp_path)
    assert claim.claim_status == ClaimStatus.CONTRADICTED
    evt_meta = claim.settlement.events[-1].metadata
    assert evt_meta["exit_code"] == 3


# ---------------------------------------------------------------------------
# Test 3 — generic command inherits active session attribution
# ---------------------------------------------------------------------------


def test_wrap_generic_command_inherits_session_attribution(
    tmp_path, monkeypatch
) -> None:
    _init(tmp_path)
    monkeypatch.chdir(tmp_path)
    sid = start_session(
        repo_path=tmp_path,
        branch="main",
        task_label="t",
        agent_app="kiro",
        model="claude-sonnet-4.6",
        harness_id="kiro-cli",
    )
    _run(
        ["wrap", "--task-type", "cli", "--", sys.executable, "-c", "print('ok')"],
        tmp_path, monkeypatch,
    )
    claim = _latest_settled_claim(tmp_path)
    meta = claim.metadata or {}
    assert meta["session_id"] == sid
    assert meta["agent_id"] == "kiro"
    assert meta["model_version"] == "claude-sonnet-4.6"
    assert meta["harness_id"] == "kiro-cli"
    assert meta["attribution_confidence"] == "high"
    assert meta["identity_source"] == "cli_flag"
    assert meta["task_type"] == "cli"


# ---------------------------------------------------------------------------
# Test 4 — existing pytest wrap backward compatibility
# ---------------------------------------------------------------------------


def test_pytest_wrap_backward_compatibility(tmp_path, monkeypatch) -> None:
    _init(tmp_path)
    (tmp_path / "test_ok.py").write_text("def test_ok(): assert True\n")
    code = _run(["wrap", "pytest", "-q", "test_ok.py"], tmp_path, monkeypatch)
    assert code == 0
    claim = _latest_settled_claim(tmp_path)
    assert claim.claim_status == ClaimStatus.VALIDATED


# ---------------------------------------------------------------------------
# Test 5 — double-dash separator is stripped
# ---------------------------------------------------------------------------


def test_wrap_double_dash_separator_stripped(tmp_path, monkeypatch) -> None:
    """'--' before the command is stripped and does not appear in wrapped_args."""
    _init(tmp_path)
    code = _run(
        ["wrap", "--task-type", "cli", "--", sys.executable, "-c", "print('ok')"],
        tmp_path, monkeypatch,
    )
    assert code == 0
    claim = _latest_settled_claim(tmp_path)
    evt_meta = claim.settlement.events[-1].metadata
    # '--' should not appear in wrapped_args
    assert "--" not in evt_meta["wrapped_args"]


# ---------------------------------------------------------------------------
# F1B tests — output excerpts
# ---------------------------------------------------------------------------


def test_wrap_generic_failure_stores_stderr_excerpt(tmp_path, monkeypatch) -> None:
    _init(tmp_path)
    code = _run(
        [
            "wrap", "--task-type", "lint", "--",
            sys.executable, "-c",
            "import sys; print('lint exploded', file=sys.stderr); raise SystemExit(7)",
        ],
        tmp_path, monkeypatch,
    )
    assert code == 7
    claim = _latest_settled_claim(tmp_path)
    evt_meta = claim.settlement.events[-1].metadata
    assert evt_meta["exit_code"] == 7
    assert "lint exploded" in evt_meta.get("stderr_excerpt", "")


def test_wrap_generic_success_stores_stdout_excerpt(tmp_path, monkeypatch) -> None:
    _init(tmp_path)
    code = _run(
        ["wrap", "--task-type", "cli", "--", sys.executable, "-c", "print('all good')"],
        tmp_path, monkeypatch,
    )
    assert code == 0
    claim = _latest_settled_claim(tmp_path)
    evt_meta = claim.settlement.events[-1].metadata
    assert evt_meta["exit_code"] == 0
    assert "all good" in evt_meta.get("stdout_excerpt", "")


def test_wrap_generic_output_excerpt_is_bounded(tmp_path, monkeypatch) -> None:
    """Stored excerpt must not exceed the configured cap (2000 chars)."""
    _init(tmp_path)
    _run(
        [
            "wrap", "--task-type", "cli", "--",
            sys.executable, "-c", "print('x' * 10000)",
        ],
        tmp_path, monkeypatch,
    )
    claim = _latest_settled_claim(tmp_path)
    evt_meta = claim.settlement.events[-1].metadata
    assert len(evt_meta.get("stdout_excerpt", "")) <= 2000


# ---------------------------------------------------------------------------
# F5A tests — command identity / title quality
# ---------------------------------------------------------------------------


def test_wrap_generic_command_title_contains_command(tmp_path, monkeypatch) -> None:
    """Generic wrap claim title is derived from the actual command, not a generic placeholder."""
    _init(tmp_path)
    _run(
        ["wrap", "--task-type", "cli", "--", sys.executable, "-c", "print('title-ok')"],
        tmp_path, monkeypatch,
    )
    claim = _latest_settled_claim(tmp_path)
    # Title should contain the executable and not be a generic "command will pass"
    assert sys.executable in claim.title or "python" in claim.title.lower()
    # Title is not the old generic placeholder
    assert claim.title != "pytest will pass"
    assert "will pass" in claim.title  # prediction suffix present


def test_wrap_pytest_command_title_contains_target(tmp_path, monkeypatch) -> None:
    """Pytest wrap claim title includes 'pytest' and the target path."""
    _init(tmp_path)
    (tmp_path / "test_target.py").write_text("def test_ok(): assert True\n")
    _run(["wrap", "--task-type", "test", "pytest", "-q", "test_target.py"], tmp_path, monkeypatch)
    claim = _latest_settled_claim(tmp_path)
    assert "pytest" in claim.title
    assert "test_target.py" in claim.title


def test_wrap_preserves_full_command_in_metadata(tmp_path, monkeypatch) -> None:
    """Full command args are preserved in settlement event metadata as wrapped_args."""
    _init(tmp_path)
    args = [sys.executable, "-c", "print('identity-check')"]
    _run(["wrap", "--task-type", "cli", "--"] + args, tmp_path, monkeypatch)
    claim = _latest_settled_claim(tmp_path)
    evt_meta = claim.settlement.events[-1].metadata
    wrapped = evt_meta.get("wrapped_args", [])
    assert args == wrapped


# ---------------------------------------------------------------------------
# G3 tests — ANSI stripping in output excerpts
# ---------------------------------------------------------------------------


def test_wrap_generic_failure_strips_ansi_from_stderr_excerpt(
    tmp_path, monkeypatch
) -> None:
    _init(tmp_path)
    code = _run(
        [
            "wrap", "--task-type", "lint", "--",
            sys.executable, "-c",
            r"import sys; print('\x1b[31mred error\x1b[0m', file=sys.stderr); raise SystemExit(7)",
        ],
        tmp_path, monkeypatch,
    )
    assert code == 7
    claim = _latest_settled_claim(tmp_path)
    excerpt = claim.settlement.events[-1].metadata.get("stderr_excerpt", "")
    assert "red error" in excerpt
    assert "\x1b" not in excerpt


def test_wrap_generic_success_strips_ansi_from_stdout_excerpt(
    tmp_path, monkeypatch
) -> None:
    _init(tmp_path)
    code = _run(
        [
            "wrap", "--task-type", "cli", "--",
            sys.executable, "-c",
            r"print('\x1b[32mgreen ok\x1b[0m')",
        ],
        tmp_path, monkeypatch,
    )
    assert code == 0
    claim = _latest_settled_claim(tmp_path)
    excerpt = claim.settlement.events[-1].metadata.get("stdout_excerpt", "")
    assert "green ok" in excerpt
    assert "\x1b" not in excerpt
