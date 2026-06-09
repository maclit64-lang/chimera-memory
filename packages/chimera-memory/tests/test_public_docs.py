"""Guard tests for public-facing docs and contribution hygiene."""
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[3]

# Contribution hygiene files
_BUG_TEMPLATE = _REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.md"
_FEATURE_TEMPLATE = _REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "feature_request.md"
_PR_TEMPLATE = _REPO_ROOT / ".github" / "pull_request_template.md"
_CONTRIBUTING = _REPO_ROOT / "CONTRIBUTING.md"

# Existing docs
_TRANSCRIPT = _REPO_ROOT / "docs" / "examples" / "fresh-install-smoke.md"
_README = _REPO_ROOT / "packages" / "chimera-memory" / "README.md"


# ─── Contribution template presence ───────────────────────────────────────────

def test_bug_report_template_exists():
    assert _BUG_TEMPLATE.exists(), "bug_report.md issue template must exist"


def test_feature_request_template_exists():
    assert _FEATURE_TEMPLATE.exists(), "feature_request.md issue template must exist"


def test_pr_template_exists():
    assert _PR_TEMPLATE.exists(), "pull_request_template.md must exist"


def test_contributing_md_exists():
    assert _CONTRIBUTING.exists(), "CONTRIBUTING.md must exist"


# ─── Bug report template content ──────────────────────────────────────────────

def test_bug_template_mentions_doctor():
    text = _BUG_TEMPLATE.read_text()
    assert "chimera-memory doctor" in text


def test_bug_template_mentions_verify():
    text = _BUG_TEMPLATE.read_text()
    assert "chimera-memory verify" in text


def test_bug_template_warns_no_chimera_memory_dir():
    text = _BUG_TEMPLATE.read_text()
    assert ".chimera-memory/" in text


def test_bug_template_includes_redaction_warning():
    text = _BUG_TEMPLATE.read_text()
    assert any(phrase in text.lower() for phrase in ["token", "credential", "secret", "api key"])


def test_bug_template_warns_no_absolute_paths():
    text = _BUG_TEMPLATE.read_text()
    assert "/Users/" in text or "/home/" in text


# ─── PR template content ──────────────────────────────────────────────────────

def test_pr_template_mentions_pytest():
    text = _PR_TEMPLATE.read_text()
    assert "pytest" in text


def test_pr_template_mentions_mypy():
    text = _PR_TEMPLATE.read_text()
    assert "mypy" in text


def test_pr_template_mentions_ruff():
    text = _PR_TEMPLATE.read_text()
    assert "ruff" in text


def test_pr_template_mentions_verify():
    text = _PR_TEMPLATE.read_text()
    assert "chimera-memory verify" in text


def test_pr_template_warns_no_ledger_files():
    text = _PR_TEMPLATE.read_text()
    assert ".chimera-memory/" in text


# ─── Safety: no private content in templates ──────────────────────────────────

def test_bug_template_no_private_paths():
    text = _BUG_TEMPLATE.read_text()
    assert "/Users/agbodaniel" not in text


def test_feature_template_no_private_paths():
    text = _FEATURE_TEMPLATE.read_text()
    assert "/Users/agbodaniel" not in text


def test_pr_template_no_private_paths():
    text = _PR_TEMPLATE.read_text()
    assert "/Users/agbodaniel" not in text


def test_contributing_no_private_paths():
    text = _CONTRIBUTING.read_text()
    assert "/Users/agbodaniel" not in text


# ─── Safety: no M2B overclaims in templates ───────────────────────────────────

def _has_m2b_overclaim(text: str) -> bool:
    """True if text positively claims M2B scoring/ranking/routing is built or working."""
    # Disallow phrases that claim the feature exists and works
    overclaim_phrases = [
        "M2B scoring is built",
        "M2B scoring works",
        "M2B scoring is available",
        "M2B scoring is implemented",
        "M2B scoring is functional",
        "model ranking is built",
        "model ranking works",
        "model routing is built",
        "model routing works",
    ]
    return any(phrase.lower() in text.lower() for phrase in overclaim_phrases)


def test_bug_template_no_m2b_scoring_overclaim():
    text = _BUG_TEMPLATE.read_text()
    assert not _has_m2b_overclaim(text), "bug template must not claim M2B scoring exists"


def test_feature_template_no_m2b_scoring_overclaim():
    text = _FEATURE_TEMPLATE.read_text()
    assert not _has_m2b_overclaim(text), "feature template must not claim M2B scoring exists"


def test_pr_template_no_m2b_scoring_overclaim():
    text = _PR_TEMPLATE.read_text()
    assert not _has_m2b_overclaim(text), "PR template must not claim M2B scoring exists"


def test_contributing_no_m2b_scoring_overclaim():
    text = _CONTRIBUTING.read_text()
    assert not _has_m2b_overclaim(text), "CONTRIBUTING must not claim M2B scoring exists"


# ─── CONTRIBUTING.md content ──────────────────────────────────────────────────

def test_contributing_mentions_doctor():
    text = _CONTRIBUTING.read_text()
    assert "chimera-memory doctor" in text


def test_contributing_mentions_verify():
    text = _CONTRIBUTING.read_text()
    assert "chimera-memory verify" in text


def test_contributing_mentions_tests():
    text = _CONTRIBUTING.read_text()
    assert "pytest" in text


def test_contributing_mentions_mypy():
    text = _CONTRIBUTING.read_text()
    assert "mypy" in text


def test_contributing_mentions_ruff():
    text = _CONTRIBUTING.read_text()
    assert "ruff" in text


def test_contributing_mentions_no_ledger_commit():
    text = _CONTRIBUTING.read_text()
    assert ".chimera-memory/" in text


def test_contributing_mentions_m2b_not_built():
    text = _CONTRIBUTING.read_text()
    # Should mention M2B exists as a concept (for non-goals section)
    assert "M2B" in text


# ─── Existing doc guard tests (kept from original) ───────────────────────────

def test_fresh_install_smoke_exists():
    assert _TRANSCRIPT.exists()


def test_fresh_install_smoke_contains_install():
    text = _TRANSCRIPT.read_text()
    assert "pip install chimera-memory" in text


def test_fresh_install_smoke_contains_init():
    text = _TRANSCRIPT.read_text()
    assert "chimera-memory init" in text


def test_fresh_install_smoke_contains_wrap():
    text = _TRANSCRIPT.read_text()
    assert "chimera-memory wrap" in text


def test_fresh_install_smoke_contains_receipt():
    text = _TRANSCRIPT.read_text()
    assert "chimera-memory receipt latest" in text


def test_fresh_install_smoke_contains_m2b_explain():
    text = _TRANSCRIPT.read_text()
    assert "m2b-readiness --explain" in text


def test_fresh_install_smoke_no_private_paths():
    text = _TRANSCRIPT.read_text()
    assert "/Users/agbodaniel" not in text
    assert "/home/" not in text or "placeholder" in text.lower()


def test_fresh_install_smoke_no_real_tokens():
    text = _TRANSCRIPT.read_text()
    assert "pypi-" not in text
    assert "ghp_" not in text


def test_readme_python_version_accurate():
    text = _README.read_text()
    assert "Python 3.12+" in text
    assert "Python 3.10+" not in text


def test_readme_no_broken_relative_docs_link():
    text = _README.read_text()
    assert "../../docs/prompts/" not in text


def test_readme_mentions_demo():
    text = _README.read_text()
    assert "chimera-memory demo" in text


def test_readme_mentions_checks():
    text = _README.read_text()
    assert "chimera-memory checks" in text


def test_readme_mentions_bundle_inspect():
    text = _README.read_text()
    assert "bundle inspect" in text


def test_readme_mentions_bundle_diff():
    text = _README.read_text()
    assert "bundle diff" in text


def test_readme_mentions_report():
    text = _README.read_text()
    assert "report.md" in text or "report.json" in text


def test_launch_walkthrough_exists():
    from pathlib import Path
    doc = Path(__file__).resolve().parents[3] / "docs" / "examples" / "public-launch-walkthrough.md"
    assert doc.exists()
    text = doc.read_text()
    assert "chimera-memory demo" in text
    assert "chimera-memory checks" in text
    assert "/Users/agbodaniel" not in text
    assert "pypi-" not in text


# ── v0.26.2 onboarding hardening guards ───────────────────────────────────────

_ALPHA_TRIAL = Path(__file__).resolve().parents[3] / "docs" / "alpha-trial.md"


def test_readme_mentions_python312():
    text = _README.read_text()
    assert "python3.12" in text or "Python 3.12" in text


def test_readme_mentions_scope_drift_not_test_failure():
    text = _README.read_text()
    assert "SCOPE_DRIFT" in text


def test_readme_mentions_committed_xray_mode():
    text = _README.read_text()
    assert "--base main --head HEAD" in text


def test_readme_mentions_uncommitted_xray_mode():
    text = _README.read_text()
    # Working-tree mode: xray generate without --base
    assert "xray generate --output" in text


def test_alpha_trial_doc_exists():
    assert _ALPHA_TRIAL.exists(), "docs/alpha-trial.md must exist"


def test_alpha_trial_mentions_python312():
    text = _ALPHA_TRIAL.read_text()
    assert "python3.12" in text or "Python 3.12" in text


def test_alpha_trial_mentions_scope_drift_not_failure():
    text = _ALPHA_TRIAL.read_text()
    assert "SCOPE_DRIFT does not mean" in text


def test_alpha_trial_mentions_both_xray_modes():
    text = _ALPHA_TRIAL.read_text()
    assert "--base main --head HEAD" in text
    assert "xray generate --output" in text


def test_alpha_trial_recommends_dot_scope_path():
    text = _ALPHA_TRIAL.read_text()
    assert 'scope_path = "."' in text


# ── v0.26.3 onboarding hardening guards ───────────────────────────────────────

def test_no_condensedlabs_in_docs() -> None:
    docs_root = Path(__file__).resolve().parents[3] / "docs"
    for path in docs_root.rglob("*.md"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert "condensedlabs/chimera-memory" not in text, (
            f"{path} contains forbidden URL 'condensedlabs/chimera-memory'"
        )


def test_alpha_trial_mentions_maclit64_url() -> None:
    text = _ALPHA_TRIAL.read_text()
    assert "maclit64-lang/chimera-memory" in text


def test_alpha_trial_mentions_git_init() -> None:
    text = _ALPHA_TRIAL.read_text()
    assert "git init" in text


def test_alpha_trial_mentions_session_start() -> None:
    text = _ALPHA_TRIAL.read_text()
    assert "session start" in text


def test_alpha_trial_explains_sessions_group_claims() -> None:
    text = _ALPHA_TRIAL.read_text()
    assert "session" in text.lower() and ("claim" in text.lower() or "receipt" in text.lower())


def test_alpha_trial_mentions_baseline_check() -> None:
    text = _ALPHA_TRIAL.read_text()
    assert "baseline" in text.lower()


def test_alpha_trial_pre_existing_not_organic_real() -> None:
    text = _ALPHA_TRIAL.read_text()
    assert "pre-existing" in text.lower() or "baseline noise" in text.lower()


def test_alpha_trial_falsifier_before_task() -> None:
    text = _ALPHA_TRIAL.read_text()
    assert "before starting" in text.lower() or "before the task" in text.lower()


def test_alpha_trial_build_typecheck_as_falsifier() -> None:
    text = _ALPHA_TRIAL.read_text()
    assert "falsifier" in text.lower() and ("build" in text.lower() or "typecheck" in text.lower())


def test_alpha_trial_distinguishes_falsifier_from_must_not_break() -> None:
    text = _ALPHA_TRIAL.read_text()
    assert "falsifiers" in text and "must_not_break" in text


def test_hooks_init_command_in_alpha_trial() -> None:
    text = _ALPHA_TRIAL.read_text()
    assert "hooks init" in text
