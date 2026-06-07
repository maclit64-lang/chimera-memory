"""Tests for v0.7 agent onboarding: agent-guide, template dogfood, wrap warnings."""
from __future__ import annotations

from pathlib import Path


from chimera_memory.cli import main


# ── agent-guide ────────────────────────────────────────────────────────────────

def test_agent_guide_default_output(capsys):
    rc = main(["agent-guide"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "organic_real" in out
    assert "session start" in out
    assert "wrap" in out
    assert "receipt bundle" in out
    assert "M2B" in out
    assert "repair_loop_id" in out or "--repair-loop-id" in out
    assert "same_scope_after_fix" in out
    assert "fixed_same_scope" in out


def test_agent_guide_generic(capsys):
    rc = main(["agent-guide", "--agent", "generic"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "organic_real" in out
    assert "test_first_contract" in out
    assert "synthetic" in out


def test_agent_guide_kiro(capsys):
    rc = main(["agent-guide", "--agent", "kiro"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "kiro" in out
    assert "kiro-cli" in out


def test_agent_guide_codex(capsys):
    rc = main(["agent-guide", "--agent", "codex"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "codex" in out


def test_agent_guide_rejects_unknown_agent(capsys):
    rc = main(["agent-guide", "--agent", "unknown-bot"])
    assert rc != 0


def test_agent_guide_repair_phase_semantics(capsys):
    """Guide must not claim regression_check produces fixed_same_scope."""
    rc = main(["agent-guide"])
    assert rc == 0
    out = capsys.readouterr().out
    # same_scope_after_fix produces fixed_same_scope
    assert "same_scope_after_fix" in out
    assert "fixed_same_scope" in out
    # regression_check produces later_regression_validated (not fixed_same_scope)
    assert "later_regression_validated" in out


# ── template dogfood ───────────────────────────────────────────────────────────

def test_template_dogfood_required_commands(capsys):
    rc = main(["template", "dogfood", "--scope-path", "packages/chimera-memory"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "preflight" in out
    assert "session start" in out
    assert "wrap" in out
    assert "session end" in out
    assert "verify" in out
    assert "receipt bundle" in out
    assert "--include-preflight" in out


def test_template_dogfood_uses_provided_scope(capsys):
    rc = main(["template", "dogfood", "--scope-path", "packages/my-package"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "packages/my-package" in out


def test_template_dogfood_known_scope_has_real_checks(capsys):
    rc = main(["template", "dogfood", "--scope-path", "packages/chimera-memory"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "pytest" in out
    assert "mypy" in out
    assert "ruff" in out


def test_template_dogfood_unknown_scope_has_placeholders(capsys):
    rc = main(["template", "dogfood", "--scope-path", "packages/unknown-pkg"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "EDIT" in out


def test_template_no_subcommand(capsys):
    rc = main(["template"])
    # Should print help or error, not crash
    assert rc != 0 or "dogfood" in capsys.readouterr().out + capsys.readouterr().err


# ── wrap warnings ──────────────────────────────────────────────────────────────

def test_wrap_warns_missing_scope_path(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_DQ_NO_WRITE", "1")
    monkeypatch.chdir(tmp_path)
    rc = main([
        "wrap",
        "--failure-origin", "organic_real",
        "--", "python3", "-c", "print('ok')",
    ])
    err = capsys.readouterr().err
    assert "--scope-path not set" in err
    # warning is non-fatal; command ran (exit 0)
    assert rc == 0


def test_wrap_warns_missing_failure_origin(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_DQ_NO_WRITE", "1")
    monkeypatch.chdir(tmp_path)
    rc = main([
        "wrap",
        "--scope-path", str(tmp_path),
        "--", "python3", "-c", "print('ok')",
    ])
    err = capsys.readouterr().err
    assert "failure_origin is missing" in err
    assert rc == 0


def test_wrap_warns_repair_phase_without_loop_id(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_DQ_NO_WRITE", "1")
    monkeypatch.chdir(tmp_path)
    rc = main([
        "wrap",
        "--failure-origin", "organic_real",
        "--scope-path", str(tmp_path),
        "--repair-phase", "baseline",
        "--", "python3", "-c", "print('ok')",
    ])
    err = capsys.readouterr().err
    assert "repair-loop lessons will not be generated" in err
    assert rc == 0


def test_wrap_warning_no_change_to_exit_code_on_failure(capsys, tmp_path, monkeypatch):
    """Warnings must not swallow a failing command's exit code."""
    monkeypatch.setenv("CHIMERA_DQ_NO_WRITE", "1")
    monkeypatch.chdir(tmp_path)
    rc = main([
        "wrap",
        "--", "python3", "-c", "import sys; sys.exit(42)",
    ])
    assert rc == 42


def test_wrap_no_warning_when_all_flags_set(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_DQ_NO_WRITE", "1")
    monkeypatch.chdir(tmp_path)
    rc = main([
        "wrap",
        "--failure-origin", "organic_real",
        "--scope-path", str(tmp_path),
        "--verification-scope", "package",
        "--repair-loop-id", "test-loop",
        "--repair-phase", "baseline",
        "--", "python3", "-c", "print('ok')",
    ])
    err = capsys.readouterr().err
    # No anchoring or failure_origin warnings
    assert "--scope-path not set" not in err
    assert "failure_origin is missing" not in err
    # repair_phase warning suppressed because repair_loop_id is set
    assert "repair-loop lessons will not be generated" not in err
    assert rc == 0


# ── docs/prompts files ─────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).parents[3]  # packages/chimera-memory/tests -> repo root


def test_prompts_files_exist():
    prompts_dir = _REPO_ROOT / "docs" / "prompts"
    assert (prompts_dir / "kiro-dogfood.md").exists()
    assert (prompts_dir / "generic-agent-dogfood.md").exists()
    assert (prompts_dir / "release-closeout.md").exists()


def test_prompts_contain_required_concepts():
    prompts_dir = _REPO_ROOT / "docs" / "prompts"
    for fname in ("kiro-dogfood.md", "generic-agent-dogfood.md"):
        text = (prompts_dir / fname).read_text()
        assert "organic_real" in text
        assert "test_first_contract" in text
        assert "receipt bundle" in text
        assert "M2B" in text

    closeout = (prompts_dir / "release-closeout.md").read_text()
    assert "pytest" in closeout
    assert "mypy" in closeout
    assert "receipt bundle" in closeout


# ── README ─────────────────────────────────────────────────────────────────────

def test_readme_mentions_agent_guide():
    readme = (_REPO_ROOT / "packages" / "chimera-memory" / "README.md").read_text()
    assert "agent-guide" in readme


def test_readme_mentions_template_dogfood():
    readme = (_REPO_ROOT / "packages" / "chimera-memory" / "README.md").read_text()
    assert "template dogfood" in readme
