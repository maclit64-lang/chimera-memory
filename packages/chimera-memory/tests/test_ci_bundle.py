"""Tests for CI receipt bundle and GitHub Step Summary format."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from chimera_memory_types.finding import EvidenceRef, EvidenceRefType

from chimera_memory.cli import main
from chimera_memory.ledger import record_claim, settle_claim
from chimera_memory.session_lifecycle import end_session, start_session

_T0 = datetime(2026, 1, 1, 12, tzinfo=UTC)
_T1 = datetime(2026, 1, 1, 13, tzinfo=UTC)

_CLEAN = {
    "session_id": "sess-bundle-001",
    "harness_id": "github-actions",
    "attribution_confidence": "high",
    "identity_source": "cli_flag",
}


def _ev() -> EvidenceRef:
    return EvidenceRef(ref_type=EvidenceRefType.EXTERNAL, ref_id="r", available_at=_T0)


def _setup_session(root: Path, *, passing: bool = True) -> None:
    sid = start_session(
        repo_path=root, branch="ci-bundle-test", task_label="bundle test",
        agent_app="ci", model="github-actions",
    )
    cid = record_claim(
        title="t", summary="s", predicted=True, evidence=[_ev()],
        root=root, claim_time=_T0, agent_id="ci", model_version="gha",
        task_type="test", extra_metadata={**_CLEAN, "session_id": sid},
    )
    settle_claim(cid, passing, _T1, root=root)
    end_session(repo_path=root, final_status=None)


# ---------------------------------------------------------------------------
# receipt bundle tests
# ---------------------------------------------------------------------------


def test_bundle_creates_expected_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _setup_session(tmp_path)
    bundle_dir = tmp_path / "bundle"
    ret = main(["receipt", "bundle", "--output-dir", str(bundle_dir)])
    assert ret == 0
    assert (bundle_dir / "receipt.md").exists()
    assert (bundle_dir / "receipt.json").exists()
    assert (bundle_dir / "status.json").exists()
    assert (bundle_dir / "github-summary.md").exists()


def test_bundle_creates_output_dir_if_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _setup_session(tmp_path)
    new_dir = tmp_path / "deep" / "bundle"
    assert not new_dir.exists()
    ret = main(["receipt", "bundle", "--output-dir", str(new_dir)])
    assert ret == 0
    assert new_dir.exists()


def test_bundle_receipt_json_is_parseable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _setup_session(tmp_path)
    bundle_dir = tmp_path / "b"
    main(["receipt", "bundle", "--output-dir", str(bundle_dir)])
    parsed = json.loads((bundle_dir / "receipt.json").read_text())
    assert isinstance(parsed, dict)


def test_bundle_status_json_is_parseable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _setup_session(tmp_path)
    bundle_dir = tmp_path / "b"
    main(["receipt", "bundle", "--output-dir", str(bundle_dir)])
    parsed = json.loads((bundle_dir / "status.json").read_text())
    assert "clean_unique_claims" in parsed


def test_bundle_no_chimera_memory_data_copied(tmp_path: Path, monkeypatch) -> None:
    """Bundle dir must not contain .chimera-memory ledger files."""
    monkeypatch.chdir(tmp_path)
    _setup_session(tmp_path)
    bundle_dir = tmp_path / "b"
    main(["receipt", "bundle", "--output-dir", str(bundle_dir)])
    for f in bundle_dir.iterdir():
        assert f.name not in ("claims.jsonl", "integrity.jsonl", "index.sqlite")


def test_bundle_no_session_returns_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bundle_dir = tmp_path / "b"
    ret = main(["receipt", "bundle", "--output-dir", str(bundle_dir)])
    assert ret == 1


def test_bundle_redaction_in_files(tmp_path: Path, monkeypatch) -> None:
    """Fake secret in command output is redacted in bundle files."""
    monkeypatch.chdir(tmp_path)
    fake_secret = "sk-TESTbundleKeyABCDEFGHIJKLMNOP"
    main(["session", "start", "--branch", "b", "--task-label", "t",
          "--agent", "ci", "--model", "m", "--harness-id", "h"])
    main(["wrap", "--failure-origin", "organic_real", "--verification-scope", "package",
          "--", "python", "-c", f"print('token={fake_secret}')"])
    main(["session", "end", "--status", "PASSED"])
    bundle_dir = tmp_path / "bundle"
    main(["receipt", "bundle", "--output-dir", str(bundle_dir)])
    for f in bundle_dir.iterdir():
        assert fake_secret not in f.read_text(encoding="utf-8"), f"{f.name} contains raw secret"


# ---------------------------------------------------------------------------
# GitHub Step Summary format tests
# ---------------------------------------------------------------------------


def test_github_summary_format(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    _setup_session(tmp_path)
    ret = main(["receipt", "latest", "--format", "github-summary"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "Chimera Memory Receipt" in out


def test_github_summary_includes_command_counts(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    _setup_session(tmp_path)
    main(["receipt", "latest", "--format", "github-summary"])
    out = capsys.readouterr().out
    assert "Commands:" in out
    assert "validated" in out.lower() or "VALIDATED" in out


def test_github_summary_failure_shows_witness(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    main(["session", "start", "--branch", "b", "--task-label", "t",
          "--agent", "ci", "--model", "m", "--harness-id", "h"])
    main(["wrap", "--failure-origin", "organic_real", "--verification-scope", "package",
          "--", "python", "-c",
          "import sys; print('some failure output', file=sys.stderr); sys.exit(1)"])
    main(["session", "end", "--status", "FAILED"])
    main(["receipt", "latest", "--format", "github-summary"])
    out = capsys.readouterr().out
    # Should include failure details section
    assert "❌" in out or "CONTRADICTED" in out or "FAILED" in out


def test_github_summary_does_not_include_raw_stdout(tmp_path: Path, monkeypatch, capsys) -> None:
    """Summary should not include giant stdout — only command table and witness excerpt."""
    monkeypatch.chdir(tmp_path)
    # Command that produces lots of stdout
    main(["session", "start", "--branch", "b", "--task-label", "t",
          "--agent", "ci", "--model", "m", "--harness-id", "h"])
    main(["wrap", "--failure-origin", "organic_real", "--verification-scope", "package",
          "--", "python", "-c", "print('x' * 5000)"])
    main(["session", "end", "--status", "PASSED"])
    main(["receipt", "latest", "--format", "github-summary"])
    out = capsys.readouterr().out
    # GitHub summary should be bounded; 5000 'x' chars must not appear verbatim
    assert "x" * 200 not in out


def test_github_summary_to_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _setup_session(tmp_path)
    out_file = tmp_path / "summary.md"
    ret = main(["receipt", "latest", "--format", "github-summary", "--output", str(out_file)])
    assert ret == 0
    assert out_file.exists()
    content = out_file.read_text()
    assert "Chimera Memory Receipt" in content


# ---------------------------------------------------------------------------
# Preflight + bundle integration tests
# ---------------------------------------------------------------------------


def test_bundle_without_include_preflight_omits_preflight(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _setup_session(tmp_path)
    bundle_dir = tmp_path / "b"
    main(["receipt", "bundle", "--output-dir", str(bundle_dir)])
    assert not (bundle_dir / "preflight.json").exists()
    assert not (bundle_dir / "preflight.md").exists()


def test_bundle_with_include_preflight_creates_preflight_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _setup_session(tmp_path)
    bundle_dir = tmp_path / "b"
    main(["receipt", "bundle", "--output-dir", str(bundle_dir),
          "--include-preflight", "--scope-path", "packages/chimera-memory"])
    assert (bundle_dir / "preflight.json").exists()
    assert (bundle_dir / "preflight.md").exists()


def test_bundle_preflight_json_parseable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _setup_session(tmp_path)
    bundle_dir = tmp_path / "b"
    main(["receipt", "bundle", "--output-dir", str(bundle_dir),
          "--include-preflight", "--scope-path", "packages/chimera-memory"])
    parsed = json.loads((bundle_dir / "preflight.json").read_text())
    assert "matching_claim_count" in parsed


def test_bundle_github_summary_includes_preflight_section(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _setup_session(tmp_path)
    bundle_dir = tmp_path / "b"
    main(["receipt", "bundle", "--output-dir", str(bundle_dir),
          "--include-preflight", "--scope-path", "packages/chimera-memory"])
    summary = (bundle_dir / "github-summary.md").read_text()
    assert "Preflight Advisory" in summary or "preflight" in summary.lower()


def test_bundle_github_summary_no_preflight_when_not_requested(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _setup_session(tmp_path)
    bundle_dir = tmp_path / "b"
    main(["receipt", "bundle", "--output-dir", str(bundle_dir)])
    summary = (bundle_dir / "github-summary.md").read_text()
    assert "Preflight Advisory" not in summary


def test_bundle_with_no_git_changes_handles_empty_preflight(tmp_path: Path, monkeypatch) -> None:
    """Bundle with --include-preflight but no git changes still succeeds."""
    monkeypatch.chdir(tmp_path)
    _setup_session(tmp_path)
    bundle_dir = tmp_path / "b"
    # --from-git with no actual git changes should not crash
    ret = main(["receipt", "bundle", "--output-dir", str(bundle_dir),
                "--include-preflight", "--from-git"])
    assert ret == 0
    assert (bundle_dir / "preflight.json").exists()


def test_bundle_preflight_no_evidence_case(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _setup_session(tmp_path)
    bundle_dir = tmp_path / "b"
    main(["receipt", "bundle", "--output-dir", str(bundle_dir),
          "--include-preflight", "--scope-path", "packages/chimera-memory"])
    parsed = json.loads((bundle_dir / "preflight.json").read_text())
    # No evidence in test ledger; should still be parseable
    assert isinstance(parsed.get("matching_claim_count"), int)
