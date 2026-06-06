"""Tests for the live chimera-memory CI workflow structure and safety."""

from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/chimera-memory-ci.yml")
DOCS = Path("docs/strategy/chimera-memory-live-ci-dogfood-v0-4.md")


# ---------------------------------------------------------------------------
# Workflow presence and trigger
# ---------------------------------------------------------------------------


def test_live_workflow_exists() -> None:
    assert WORKFLOW.exists(), "live chimera-memory CI workflow must exist"


def test_workflow_has_workflow_dispatch() -> None:
    assert "workflow_dispatch" in WORKFLOW.read_text()


# ---------------------------------------------------------------------------
# Safety: no secrets, no publish
# ---------------------------------------------------------------------------


def test_workflow_no_publish_token() -> None:
    content = WORKFLOW.read_text().lower()
    for bad in ("uv_publish_token", "pypi_token", "pypi-", "uv publish"):
        assert bad not in content, f"workflow must not contain: {bad!r}"


def test_workflow_no_publish_command() -> None:
    content = WORKFLOW.read_text()
    assert "uv publish" not in content
    assert "twine upload" not in content


def test_workflow_no_git_push() -> None:
    content = WORKFLOW.read_text()
    assert "git push" not in content
    assert "git tag" not in content


# ---------------------------------------------------------------------------
# Required CI operations
# ---------------------------------------------------------------------------


def test_workflow_mentions_preflight() -> None:
    content = WORKFLOW.read_text()
    assert "chimera-memory preflight" in content


def test_workflow_mentions_receipt_bundle_include_preflight() -> None:
    content = WORKFLOW.read_text()
    assert "receipt bundle" in content
    assert "--include-preflight" in content


def test_workflow_mentions_upload_artifact() -> None:
    assert "upload-artifact" in WORKFLOW.read_text()


def test_workflow_uses_if_always_for_receipts() -> None:
    content = WORKFLOW.read_text()
    assert content.count("if: always()") >= 2


def test_workflow_mentions_github_step_summary() -> None:
    assert "GITHUB_STEP_SUMMARY" in WORKFLOW.read_text()


def test_workflow_mentions_evidence_bundle() -> None:
    assert "evidence bundle" in WORKFLOW.read_text()


# ---------------------------------------------------------------------------
# Docs content
# ---------------------------------------------------------------------------


def test_live_ci_docs_exist() -> None:
    assert DOCS.exists(), "live CI dogfood docs must exist"


def test_docs_mention_workflow_dispatch_reason() -> None:
    content = DOCS.read_text().lower()
    assert "workflow_dispatch" in content
    assert "apfs" in content or "startup_failure" in content


def test_docs_mention_no_hosted_cloud() -> None:
    content = DOCS.read_text().lower()
    assert "not built" in content
    assert "hosted" in content or "cloud" in content


def test_docs_mention_source_none() -> None:
    content = DOCS.read_text()
    assert "source: none" in content


def test_docs_mention_exit_code() -> None:
    content = DOCS.read_text().lower()
    assert "exit" in content and "code" in content


def test_docs_raw_ledger_not_uploaded() -> None:
    content = DOCS.read_text()
    assert ".chimera-memory/" in content and "not" in content.lower()
