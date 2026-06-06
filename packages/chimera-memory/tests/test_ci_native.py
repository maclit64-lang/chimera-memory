"""Tests for v0.2.0 CI-native docs: workflow example and CI artifact contract."""

from __future__ import annotations

import sys
from pathlib import Path

WORKFLOW = Path("docs/examples/github-actions/chimera-memory-ci.yml")
CI_DOC = Path("docs/strategy/chimera-memory-ci-native-v0-2.md")


# ---------------------------------------------------------------------------
# Exit-code passthrough (behavioral)
# ---------------------------------------------------------------------------


def test_wrap_propagates_exit_code_on_failure(tmp_path, monkeypatch) -> None:
    """chimera-memory wrap exits with the wrapped command's exit code.

    Uses CHIMERA_DQ_NO_WRITE=1 so this test fixture does not write to the
    live ledger. No --failure-origin workaround needed.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CHIMERA_DQ_NO_WRITE", "1")
    from chimera_memory.cli import main as _main
    _main(["init"])
    _main(["session", "start", "--branch", "t", "--task-label", "t",
           "--agent", "a", "--model", "m", "--harness-id", "h"])
    result = _main([
        "wrap", "--failure-origin", "organic_real",
        "--verification-scope", "package", "--scope-path", str(tmp_path),
        "--", sys.executable, "-c", "import sys; sys.exit(3)",
    ])
    assert result == 3, f"wrap must propagate exit code; got {result}"


# ---------------------------------------------------------------------------
# Workflow file presence and content
# ---------------------------------------------------------------------------


def test_workflow_example_exists() -> None:
    assert WORKFLOW.exists(), "GitHub Actions example workflow must exist"


def test_workflow_mentions_preflight_from_git() -> None:
    content = WORKFLOW.read_text()
    assert "preflight" in content and "--from-git" in content


def test_workflow_mentions_receipt_bundle_include_preflight() -> None:
    content = WORKFLOW.read_text()
    assert "receipt bundle" in content
    assert "--include-preflight" in content


def test_workflow_mentions_upload_artifact() -> None:
    assert "upload-artifact" in WORKFLOW.read_text()


def test_workflow_mentions_github_step_summary() -> None:
    assert "GITHUB_STEP_SUMMARY" in WORKFLOW.read_text()


def test_workflow_has_if_always_for_artifact_and_summary() -> None:
    content = WORKFLOW.read_text()
    # if: always() must appear (for artifact upload and summary steps)
    assert content.count("if: always()") >= 2


def test_workflow_has_no_hardcoded_secrets() -> None:
    content = WORKFLOW.read_text().lower()
    for bad in ("pypi-", "ghp_", "github_token =", "api_key =", "secret ="):
        assert bad not in content, f"workflow must not contain hardcoded secret: {bad}"


def test_workflow_documents_exit_code_contract() -> None:
    content = WORKFLOW.read_text()
    assert "exit" in content.lower() or "exit code" in content.lower()


# ---------------------------------------------------------------------------
# CI docs content
# ---------------------------------------------------------------------------


def test_ci_doc_exists() -> None:
    assert CI_DOC.exists(), "CI-native v0.2 doc must exist"


def test_ci_doc_mentions_exit_code_passthrough() -> None:
    content = CI_DOC.read_text().lower()
    assert "exit" in content and "code" in content


def test_ci_doc_mentions_source_none() -> None:
    content = CI_DOC.read_text()
    assert "source: none" in content or "source:none" in content


def test_ci_doc_mentions_no_hosted_cloud() -> None:
    content = CI_DOC.read_text().lower()
    assert "not built" in content
    assert "hosted" in content or "cloud" in content


def test_ci_doc_mentions_if_always() -> None:
    assert "always()" in CI_DOC.read_text()


def test_ci_doc_mentions_key_json_commands() -> None:
    content = CI_DOC.read_text()
    for cmd in ("status --json", "m2b-readiness --json", "preflight --json",
                "evidence import"):
        assert cmd in content, f"CI doc must document JSON contract: {cmd!r}"


def test_ci_doc_mentions_artifact_files() -> None:
    content = CI_DOC.read_text()
    for fname in ("receipt.json", "github-summary.md", "preflight.json",
                  "failures.json", "verify.json"):
        assert fname in content, f"CI doc must list artifact file: {fname}"


def test_ci_doc_mentions_redaction() -> None:
    assert "redact" in CI_DOC.read_text().lower()


def test_ci_doc_mentions_m2b_not_for_ci_gating() -> None:
    content = CI_DOC.read_text().lower()
    assert "not built" in content or "do not gate" in content
