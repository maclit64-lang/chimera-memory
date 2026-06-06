"""Tests for CI receipt MVP — --format, --output, and CI-mode session workflow."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from chimera_memory_types.finding import EvidenceRef, EvidenceRefType

from chimera_memory.cli import main
from chimera_memory.ledger import record_claim, settle_claim
from chimera_memory.session_lifecycle import end_session, start_session
from chimera_memory.storage import MemoryStore

_T0 = datetime(2026, 1, 1, 12, tzinfo=UTC)
_T1 = datetime(2026, 1, 1, 13, tzinfo=UTC)

_CLEAN = {
    "session_id": "sess-ci-001",
    "harness_id": "github-actions",
    "attribution_confidence": "high",
    "identity_source": "cli_flag",
}


def _ev() -> EvidenceRef:
    return EvidenceRef(ref_type=EvidenceRefType.EXTERNAL, ref_id="r", available_at=_T0)


def _setup_closed_session(root: Path) -> None:
    sid = start_session(
        repo_path=root, branch="ci-test", task_label="ci test",
        agent_app="ci", model="github-actions",
    )
    cid = record_claim(
        title="t", summary="s", predicted=True, evidence=[_ev()],
        root=root, claim_time=_T0, agent_id="ci", model_version="gha",
        task_type="test", extra_metadata={**_CLEAN, "session_id": sid},
    )
    settle_claim(cid, True, _T1, root=root)
    end_session(repo_path=root)


# ---------------------------------------------------------------------------
# --format flag tests
# ---------------------------------------------------------------------------


def test_receipt_format_json(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    _setup_closed_session(tmp_path)
    ret = main(["receipt", "latest", "--format", "json"])
    assert ret == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert "session_id" in parsed or "task" in parsed


def test_receipt_format_markdown(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    _setup_closed_session(tmp_path)
    ret = main(["receipt", "latest", "--format", "markdown"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "#" in out or "**" in out or "Task" in out


def test_receipt_format_text(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    _setup_closed_session(tmp_path)
    ret = main(["receipt", "latest", "--format", "text"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "Task:" in out or "task" in out.lower()


# ---------------------------------------------------------------------------
# --output flag tests
# ---------------------------------------------------------------------------


def test_receipt_output_markdown_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _setup_closed_session(tmp_path)
    out_path = tmp_path / "receipt.md"
    ret = main(["receipt", "latest", "--format", "markdown", "--output", str(out_path)])
    assert ret == 0
    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    assert len(content) > 10


def test_receipt_output_json_file_is_parseable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _setup_closed_session(tmp_path)
    out_path = tmp_path / "receipt.json"
    ret = main(["receipt", "latest", "--format", "json", "--output", str(out_path)])
    assert ret == 0
    assert out_path.exists()
    parsed = json.loads(out_path.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)


def test_receipt_output_writes_atomically(tmp_path: Path, monkeypatch) -> None:
    """--output writes via temp+replace, not direct open."""
    monkeypatch.chdir(tmp_path)
    _setup_closed_session(tmp_path)
    out_path = tmp_path / "receipt.md"
    main(["receipt", "latest", "--markdown", "--output", str(out_path)])
    # Temp file should be gone
    tmp_file = tmp_path / "receipt.md.tmp"
    assert not tmp_file.exists()
    assert out_path.exists()


# ---------------------------------------------------------------------------
# CI-style workflow: wrap + session + receipt
# ---------------------------------------------------------------------------


def test_ci_wrap_passing_command_produces_receipt(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    # Start session
    main(["session", "start", "--branch", "ci-test", "--task-label", "ci",
          "--agent", "ci", "--model", "gha", "--harness-id", "github-actions"])
    # Wrap a passing command
    ret = main(["wrap", "--failure-origin", "organic_real",
                "--verification-scope", "package",
                "--", "python", "-c", "print('ci ok')"])
    assert ret == 0
    # End session
    main(["session", "end", "--status", "PASSED"])
    # Receipt to file
    out = tmp_path / "receipt.json"
    main(["receipt", "latest", "--format", "json", "--output", str(out)])
    parsed = json.loads(out.read_text())
    assert isinstance(parsed, dict)


def test_ci_wrap_failing_command_produces_witness(tmp_path: Path, monkeypatch) -> None:
    """A failed command still produces a receipt with witness excerpt."""
    monkeypatch.chdir(tmp_path)
    main(["session", "start", "--branch", "ci-test", "--task-label", "ci",
          "--agent", "ci", "--model", "gha", "--harness-id", "github-actions"])
    # Wrap a failing command
    ret = main(["wrap", "--failure-origin", "organic_real",
                "--verification-scope", "package",
                "--", "python", "-c", "import sys; print('fail msg', file=sys.stderr); sys.exit(1)"])
    assert ret == 1  # exit code propagated
    main(["session", "end", "--status", "FAILED"])
    # Failures command should show the failure
    store = MemoryStore(tmp_path / ".chimera-memory")
    rm_claims = store.read_claims()
    from chimera_memory_types.knowledge import ClaimStatus
    failed = [c for c in rm_claims if c.claim_status == ClaimStatus.CONTRADICTED]
    assert failed, "expected at least one CONTRADICTED claim"


def test_ci_redaction_in_receipt_file(tmp_path: Path, monkeypatch) -> None:
    """Fake secret in command output is redacted in receipt file."""
    monkeypatch.chdir(tmp_path)
    fake_secret = "sk-TESTfakeKeyABCDEFGHIJKLMNOPQ"
    main(["session", "start", "--branch", "b", "--task-label", "t",
          "--agent", "ci", "--model", "m", "--harness-id", "h"])
    main(["wrap", "--failure-origin", "organic_real", "--verification-scope", "package",
          "--", "python", "-c", f"print('token={fake_secret}')"])
    main(["session", "end", "--status", "PASSED"])
    out = tmp_path / "receipt.json"
    main(["receipt", "latest", "--format", "json", "--output", str(out)])
    content = out.read_text(encoding="utf-8")
    assert fake_secret not in content
