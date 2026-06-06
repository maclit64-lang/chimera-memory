"""F4-lite: tests for chimera-memory failures command."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from chimera_memory.cli import main
from chimera_memory.ledger import record_claim, settle_claim
from chimera_memory.storage import MemoryStore


def _init(tmp_path: Path) -> MemoryStore:
    store = MemoryStore.from_paths(root=tmp_path)
    store.initialize()
    return store


def _ev(t: datetime) -> dict:
    return {"ref_type": "external", "ref_id": "git:abc", "available_at": t}


def _add_claim(
    tmp_path: Path,
    *,
    passed: bool,
    task_type: str = "test",
    agent_id: str = "kiro",
    session_id: str = "sess-test-001",
    offset: int = 0,
) -> str:
    t0 = datetime(2026, 6, 1, 12, tzinfo=UTC) + timedelta(seconds=offset)
    t1 = t0 + timedelta(seconds=5)
    cid = record_claim(
        title=f"command will pass ({task_type})",
        summary="s",
        predicted=True,
        evidence=[_ev(t0)],
        root=tmp_path,
        claim_time=t0,
        agent_id=agent_id,
        model_version="claude-sonnet-4.6",
        task_type=task_type,
        extra_metadata={
            "session_id": session_id,
            "attribution_confidence": "high",
            "identity_source": "cli_flag",
            "harness_id": "kiro-cli",
        },
    )
    settle_claim(
        cid, passed, t1, root=tmp_path,
        event_metadata={"exit_code": 0 if passed else 7, "wrapped_args": ["python", "-c", "test"]},
    )
    return cid


def _run(argv: list[str], tmp_path: Path, monkeypatch) -> int:
    monkeypatch.chdir(tmp_path)
    return main(argv)


# ---------------------------------------------------------------------------
# Test 1 — failures command lists contradicted claims
# ---------------------------------------------------------------------------


def test_failures_command_lists_contradicted_claims(
    tmp_path, monkeypatch, capsys
) -> None:
    _init(tmp_path)
    _add_claim(tmp_path, passed=True, task_type="test", offset=0)
    _add_claim(tmp_path, passed=False, task_type="lint", offset=100)

    code = _run(["failures"], tmp_path, monkeypatch)
    assert code == 0
    out = capsys.readouterr().out
    assert "1 failure" in out
    assert "lint" in out
    assert "kiro" in out
    # validated claim (task_type=test) should not appear as a failure entry
    # The output has exactly 1 failure entry, which is the lint one
    assert out.count("task:") == 1


# ---------------------------------------------------------------------------
# Test 2 — failures command deduplicates proposed and settled records
# ---------------------------------------------------------------------------


def test_failures_command_deduplicates_proposed_and_settled_records(
    tmp_path, monkeypatch, capsys
) -> None:
    _init(tmp_path)
    # proposed + contradicted settle = 2 raw records, 1 unique claim
    _add_claim(tmp_path, passed=False, task_type="lint", offset=0)

    store = MemoryStore.from_paths(root=tmp_path)
    assert len(store.read_claims()) == 2  # 2 raw records

    code = _run(["failures"], tmp_path, monkeypatch)
    assert code == 0
    out = capsys.readouterr().out
    assert "1 failure" in out  # not 2


# ---------------------------------------------------------------------------
# Test 3 — failures command empty store is clean
# ---------------------------------------------------------------------------


def test_failures_command_empty_store_is_clean(
    tmp_path, monkeypatch, capsys
) -> None:
    _init(tmp_path)
    code = _run(["failures"], tmp_path, monkeypatch)
    assert code == 0
    out = capsys.readouterr().out
    assert "no contradicted" in out.lower()


# ---------------------------------------------------------------------------
# Test 4 — failures JSON flag outputs parseable JSON
# ---------------------------------------------------------------------------


def test_failures_json_flag_outputs_parseable_json(
    tmp_path, monkeypatch, capsys
) -> None:
    _init(tmp_path)
    _add_claim(tmp_path, passed=False, task_type="lint", offset=0)

    code = _run(["failures", "--json"], tmp_path, monkeypatch)
    assert code == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["count"] == 1
    assert isinstance(payload["failures"], list)
    f = payload["failures"][0]
    assert f["status"] == "contradicted"
    assert f["task_type"] == "lint"


# ---------------------------------------------------------------------------
# Test 5 — failures include session attribution metadata
# ---------------------------------------------------------------------------


def test_failures_include_session_attribution_metadata(
    tmp_path, monkeypatch, capsys
) -> None:
    _init(tmp_path)
    _add_claim(tmp_path, passed=False, task_type="lint", agent_id="kiro",
               session_id="sess-attr-test", offset=0)

    code = _run(["failures", "--json"], tmp_path, monkeypatch)
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    f = payload["failures"][0]
    assert f["session_id"] == "sess-attr-test"
    assert f["agent_id"] == "kiro"
    assert f["model_version"] == "claude-sonnet-4.6"
    assert f["harness_id"] == "kiro-cli"
    assert f["task_type"] == "lint"
    assert f["exit_code"] == 7


# ---------------------------------------------------------------------------
# F1B tests — witness in failures command
# ---------------------------------------------------------------------------


def _add_claim_with_witness(
    tmp_path: Path,
    *,
    passed: bool = False,
    task_type: str = "lint",
    stderr: str = "lint exploded",
    stdout: str = "",
) -> str:
    t0 = datetime(2026, 6, 1, 12, tzinfo=UTC)
    t1 = t0 + timedelta(seconds=5)
    cid = record_claim(
        title="cmd", summary="s", predicted=True, evidence=[_ev(t0)],
        root=tmp_path, claim_time=t0,
        agent_id="kiro", model_version="claude-sonnet-4.6", task_type=task_type,
        extra_metadata={"session_id": "sess-w-001", "attribution_confidence": "high",
                        "identity_source": "cli_flag"},
    )
    settle_claim(
        cid, passed, t1, root=tmp_path,
        event_metadata={
            "exit_code": 0 if passed else 7,
            "wrapped_args": ["python", "-c", "test"],
            "stderr_excerpt": stderr,
            "stdout_excerpt": stdout,
        },
    )
    return cid


def test_failures_command_shows_stderr_excerpt(
    tmp_path, monkeypatch, capsys
) -> None:
    _init(tmp_path)
    _add_claim_with_witness(tmp_path, passed=False, stderr="lint exploded")
    code = _run(["failures"], tmp_path, monkeypatch)
    assert code == 0
    out = capsys.readouterr().out
    assert "lint exploded" in out


def test_failures_json_includes_output_excerpts(
    tmp_path, monkeypatch, capsys
) -> None:
    _init(tmp_path)
    _add_claim_with_witness(tmp_path, passed=False, stderr="bad output", stdout="some stdout")
    code = _run(["failures", "--json"], tmp_path, monkeypatch)
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    f = payload["failures"][0]
    assert "stderr_excerpt" in f
    assert "bad output" in f["stderr_excerpt"]
    assert "stdout_excerpt" in f


def test_failures_output_uses_command_identity(
    tmp_path, monkeypatch, capsys
) -> None:
    """failures text output shows the actual command, not a generic placeholder."""
    _init(tmp_path)
    _add_claim_with_witness(
        tmp_path, passed=False, task_type="lint", stderr="error: bad code"
    )
    code = _run(["failures"], tmp_path, monkeypatch)
    assert code == 0
    out = capsys.readouterr().out
    # The command field should contain the real wrapped_args, not a generic string
    assert "command:" in out
    assert "python" in out  # from _add_claim_with_witness wrapped_args


# ---------------------------------------------------------------------------
# G3 tests — ANSI stripping in failures output
# ---------------------------------------------------------------------------


def test_failures_command_strips_ansi_codes_from_witness_output(
    tmp_path, monkeypatch, capsys
) -> None:
    _init(tmp_path)
    # Store a claim with ANSI codes in the witness (simulates pre-strip records)
    _add_claim_with_witness(
        tmp_path, passed=False, stderr="\x1b[31mtype error\x1b[0m", stdout=""
    )
    code = _run(["failures"], tmp_path, monkeypatch)
    assert code == 0
    out = capsys.readouterr().out
    # The raw \x1b sequence should not appear in the text output
    assert "\x1b" not in out


def test_failures_json_strips_ansi_codes_from_witness_output(
    tmp_path, monkeypatch, capsys
) -> None:
    _init(tmp_path)
    _add_claim_with_witness(
        tmp_path, passed=False, stderr="\x1b[31mtype error\x1b[0m", stdout=""
    )
    code = _run(["failures", "--json"], tmp_path, monkeypatch)
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    stderr_val = payload["failures"][0]["stderr_excerpt"]
    assert "\x1b" not in stderr_val
