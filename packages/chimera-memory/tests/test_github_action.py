from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ACTION = _REPO_ROOT / "action.yml"
_EXAMPLE_WF = _REPO_ROOT / "docs" / "examples" / "github-actions" / "pr-evidence.yml"

yaml = pytest.importorskip("yaml")


def _action() -> dict:
    return yaml.safe_load(_ACTION.read_text())


def test_action_file_exists() -> None:
    assert _ACTION.exists(), "repo-root action.yml must exist"


def test_action_is_composite() -> None:
    assert _action()["runs"]["using"] == "composite"


def test_action_declares_expected_inputs() -> None:
    inputs = _action()["inputs"]
    for name in ("base", "head", "output", "comment", "fail-on", "python-version"):
        assert name in inputs, f"action.yml must declare input '{name}'"


def test_action_default_output_is_pr_evidence() -> None:
    assert _action()["inputs"]["output"]["default"] == "PR_EVIDENCE.md"


def test_action_default_python_is_312() -> None:
    assert str(_action()["inputs"]["python-version"]["default"]) == "3.12"


def test_action_fail_on_defaults_to_never() -> None:
    # CI gating is out of scope for this ticket; advisory only.
    assert _action()["inputs"]["fail-on"]["default"] == "never"


def test_action_runs_xray_generate() -> None:
    text = _ACTION.read_text()
    assert "chimera-memory xray generate" in text


def test_action_installs_chimera_memory() -> None:
    text = _ACTION.read_text()
    assert "pip install" in text and "chimera-memory" in text


def test_action_uploads_artifact_always() -> None:
    steps = _action()["runs"]["steps"]
    upload = [s for s in steps if "upload-artifact" in str(s.get("uses", ""))]
    assert upload, "action must upload the receipt as an artifact"
    assert any(s.get("if") == "always()" for s in upload), (
        "artifact upload must run with if: always() (fork-safe)"
    )


def test_action_writes_step_summary() -> None:
    text = _ACTION.read_text()
    assert "GITHUB_STEP_SUMMARY" in text


def test_action_comment_step_is_fork_safe() -> None:
    steps = _action()["runs"]["steps"]
    comment_steps = [
        s for s in steps if "github-script" in str(s.get("uses", ""))
    ]
    assert comment_steps, "action must have a PR-comment step"
    # The comment step must not hard-fail the job on forks / missing perms.
    assert any(s.get("continue-on-error") is True for s in comment_steps)


def test_action_has_no_hardcoded_secrets() -> None:
    text = _ACTION.read_text().lower()
    # No baked tokens; GitHub injects the token automatically for github-script.
    for leak in ("ghp_", "github_pat_", "pypi-", "password:", "token: ghp"):
        assert leak not in text


def test_action_preserves_honesty_rule() -> None:
    text = _ACTION.read_text().lower()
    assert "evidence quality, not code correctness" in text
    for forbidden in (
        "production-ready",
        "guaranteed",
        "certified",
        "approved to merge",
        "the agent lied",
    ):
        assert forbidden not in text


def test_example_workflow_exists_and_is_copy_pasteable() -> None:
    assert _EXAMPLE_WF.exists()
    wf = yaml.safe_load(_EXAMPLE_WF.read_text())
    # `on: pull_request` round-trips to either the string or {pull_request: None}.
    assert "pull_request" in str(wf.get(True, wf.get("on")))
    assert wf["permissions"]["pull-requests"] == "write"
    text = _EXAMPLE_WF.read_text()
    assert "maclit64-lang/chimera-memory@" in text
    assert "fetch-depth: 0" in text


def test_example_workflow_no_private_paths() -> None:
    text = _EXAMPLE_WF.read_text()
    assert "/Users/agbodaniel" not in text


_README = _REPO_ROOT / "packages" / "chimera-memory" / "README.md"


def test_readme_points_to_github_action() -> None:
    """The package README makes the reusable Action discoverable for PR/CI use."""
    text = _README.read_text()
    assert "maclit64-lang/chimera-memory@" in text, "README must show the Action usage"
    assert "pull_request" in text, "README must show the PR trigger"
    assert "docs/examples/github-actions/pr-evidence.yml" in text, (
        "README must link to the full example workflow"
    )


def test_readme_action_mention_is_honest() -> None:
    """The README Action mention keeps the honesty rule and avoids overclaims."""
    text = _README.read_text().lower()
    assert "evidence quality, not code correctness" in text
    for forbidden in (
        "production-ready",
        "guaranteed",
        "certified",
        "approved to merge",
        "the agent lied",
    ):
        assert forbidden not in text


def test_action_wires_fail_on_into_gate() -> None:
    """The Action passes its fail-on input into an xray --fail-on gate command."""
    text = _ACTION.read_text()
    assert "--fail-on" in text
    assert "${{ inputs.fail-on }}" in text


def test_action_gate_default_is_non_failing() -> None:
    assert _action()["inputs"]["fail-on"]["default"] == "never"


def test_action_gate_message_is_honest() -> None:
    text = _ACTION.read_text().lower()
    assert "evidence policy, not code correctness" in text


def test_example_workflow_documents_optional_stricter_gate() -> None:
    text = _EXAMPLE_WF.read_text()
    assert "fail-on: never" in text  # advisory default shown
    assert "fail-on: warnings" in text  # optional stricter policy shown
