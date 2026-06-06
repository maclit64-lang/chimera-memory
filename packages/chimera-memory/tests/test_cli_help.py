"""G2: Tests that CLI --help text contains useful descriptions."""
from __future__ import annotations

from chimera_memory.cli import main


def _help(argv: list[str], capsys) -> str:
    try:
        main(argv)
    except SystemExit:
        pass
    return capsys.readouterr().out


def test_top_level_help_describes_core_commands(capsys) -> None:
    out = _help(["--help"], capsys)
    assert "local-first reliability ledger" in out.lower() or "chimera memory" in out.lower()
    assert "wrap" in out
    assert "status" in out
    assert "failures" in out
    assert "receipt" in out
    assert "session" in out


def test_wrap_help_explains_generic_command_and_task_type(capsys) -> None:
    out = _help(["wrap", "--help"], capsys)
    assert "VALIDATED" in out
    assert "CONTRADICTED" in out
    assert "task-type" in out or "task_type" in out
    assert "--" in out  # separator hint


def test_status_help_explains_clean_claim_gate(capsys) -> None:
    out = _help(["status", "--help"], capsys)
    # status description should mention clean claims or gate
    assert "clean" in out.lower() or "gate" in out.lower() or "report" in out.lower()


def test_failures_help_explains_contradicted_claims(capsys) -> None:
    out = _help(["failures", "--help"], capsys)
    assert "CONTRADICTED" in out or "contradicted" in out.lower()


def test_receipt_help_mentions_markdown(capsys) -> None:
    out = _help(["receipt", "latest", "--help"], capsys)
    assert "markdown" in out.lower()


def test_session_start_help_mentions_unknown_model_and_harness(capsys) -> None:
    out = _help(["session", "start", "--help"], capsys)
    assert "unknown" in out.lower()
    assert "harness" in out.lower()


def test_verify_help_explains_integrity_chain(capsys) -> None:
    out = _help(["verify", "--help"], capsys)
    assert "integrity" in out.lower() or "chain" in out.lower() or "legacy" in out.lower()


def test_export_help_explains_engine_ready_jsonl(capsys) -> None:
    out = _help(["export", "--help"], capsys)
    assert "jsonl" in out.lower() or "engine" in out.lower() or "evidence" in out.lower()


def test_export_help_mentions_clean_only_and_session_id(capsys) -> None:
    out = _help(["export", "--help"], capsys)
    assert "clean" in out.lower()
    assert "session" in out.lower()
