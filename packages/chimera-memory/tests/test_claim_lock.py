"""Tests for the claim-locked evidence foundation (v0.22)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from chimera_memory.claim_lock import (
    ClaimError,
    ClaimSpec,
    assess_quality,
    compute_payload_hash,
    file_under_scope,
    lock_claim,
    load_spec_from_toml,
    safe_command_from_string,
    settle_claim,
    validate_command_list,
)
from chimera_memory.cli import main
from chimera_memory.storage import MemoryStore

_PASS = [sys.executable, "-c", "import sys; sys.exit(0)"]
_FAIL = [sys.executable, "-c", "import sys; sys.exit(1)"]


def _git(tmp_path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)


def _init_repo(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t.dev")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "packages" / "cart").mkdir(parents=True)
    (tmp_path / "packages" / "payments").mkdir(parents=True)
    (tmp_path / "packages" / "cart" / "checkout.py").write_text("x = 1\n")
    (tmp_path / "packages" / "payments" / "refund.py").write_text("y = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _spec(**kw) -> ClaimSpec:
    return ClaimSpec(
        intent=kw.get("intent", "fix checkout null deref"),
        scope_path=kw.get("scope_path", "packages/cart"),
        predicted_outcome=kw.get("predicted_outcome", "all pass"),
        falsifiers=kw.get("falsifiers", [list(_PASS)]),
        must_not_break=kw.get("must_not_break", []),
    )


# ── command normalisation ─────────────────────────────────────────────────
def test_validate_command_list_accepts_list_with_inline_semicolon() -> None:
    # shell=False => list elements are literal argv; ';' is safe inside one token
    cmd = validate_command_list(["python", "-c", "import sys; sys.exit(0)"])
    assert cmd == ["python", "-c", "import sys; sys.exit(0)"]


def test_validate_command_list_rejects_shell_string() -> None:
    with pytest.raises(ClaimError):
        validate_command_list("pytest tests/")


def test_validate_command_list_rejects_empty() -> None:
    with pytest.raises(ClaimError):
        validate_command_list([])


def test_safe_command_from_string_parses_tokens() -> None:
    assert safe_command_from_string("pytest tests/test_a.py") == [
        "pytest",
        "tests/test_a.py",
    ]


def test_safe_command_from_string_rejects_metacharacters() -> None:
    with pytest.raises(ClaimError):
        safe_command_from_string("pytest && rm -rf /")


# ── sealing + quality ─────────────────────────────────────────────────────
def test_payload_hash_is_stable_for_same_payload() -> None:
    assert compute_payload_hash(_spec()) == compute_payload_hash(_spec())


def test_payload_hash_changes_with_intent() -> None:
    assert compute_payload_hash(_spec()) != compute_payload_hash(_spec(intent="other"))


def test_quality_weak_when_no_falsifier() -> None:
    quality, warnings = assess_quality(_spec(falsifiers=[]))
    assert quality == "weak"
    assert "WEAK_FALSIFIER" in warnings


def test_quality_strong_with_falsifier_and_must_not_break() -> None:
    quality, _ = assess_quality(_spec(must_not_break=[list(_PASS)]))
    assert quality == "strong"


def test_file_under_scope() -> None:
    assert file_under_scope("packages/cart/checkout.py", "packages/cart")
    assert not file_under_scope("packages/payments/refund.py", "packages/cart")
    assert file_under_scope("anything", ".")


# ── lock ──────────────────────────────────────────────────────────────────
def test_lock_creates_sealed_claim(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    record = lock_claim(store, _spec(), root=repo)
    assert record["claim_id"].startswith("clm_")
    assert record["settlement"]["status"] == "LOCKED"
    assert record["seal"]["payload_hash"]
    assert record["seal"]["seal_version"] == 1
    assert record["schema_version"] == 1


def test_lock_records_git_head(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    record = lock_claim(store, _spec(), root=repo)
    assert record["pre_edit_state"]["git_head"]
    assert record["pre_edit_state"]["dirty_state"] == "clean"


def test_lock_records_dirty_state_warning(repo: Path) -> None:
    (repo / "packages" / "cart" / "checkout.py").write_text("x = 2\n")
    store = MemoryStore.from_paths(root=repo)
    record = lock_claim(store, _spec(), root=repo)
    assert record["pre_edit_state"]["dirty_state"] == "dirty"
    assert "DIRTY_PRE_EDIT_STATE" in record["quality"]["warnings"]


def test_lock_preserves_attribution_fields(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    record = lock_claim(store, _spec(), root=repo)
    attr = record["attribution"]
    for key in (
        "session_id",
        "terminal_id",
        "worktree_path",
        "branch",
        "agent_name",
        "model_name",
        "harness_id",
        "attribution_confidence",
    ):
        assert key in attr


def test_lock_unknown_attribution_allowed(repo: Path, monkeypatch) -> None:
    monkeypatch.delenv("AGENT_NAME", raising=False)
    monkeypatch.delenv("MODEL_NAME", raising=False)
    store = MemoryStore.from_paths(root=repo)
    record = lock_claim(store, _spec(), root=repo)
    assert record["attribution"]["agent_name"] is None
    assert record["attribution"]["attribution_confidence"] == "unknown"


def test_lock_includes_env_attribution_when_available(repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_NAME", "kiro")
    monkeypatch.setenv("MODEL_NAME", "claude-opus-4.8")
    store = MemoryStore.from_paths(root=repo)
    record = lock_claim(store, _spec(), root=repo)
    assert record["attribution"]["agent_name"] == "kiro"
    assert record["attribution"]["model_name"] == "claude-opus-4.8"
    assert record["attribution"]["attribution_confidence"] == "env"


def test_load_spec_from_toml(repo: Path) -> None:
    toml = repo / "claim.toml"
    toml.write_text(
        'intent = "fix x"\n'
        'scope_path = "packages/cart"\n'
        "[[falsifiers]]\n"
        'command = ["pytest", "tests/test_a.py"]\n'
    )
    spec = load_spec_from_toml(toml)
    assert spec.intent == "fix x"
    assert spec.scope_path == "packages/cart"
    assert spec.falsifiers == [["pytest", "tests/test_a.py"]]


def test_load_spec_from_toml_rejects_string_command(repo: Path) -> None:
    toml = repo / "claim.toml"
    toml.write_text(
        'intent = "fix x"\nscope_path = "packages/cart"\n'
        "[[falsifiers]]\ncommand = \"pytest tests/\"\n"
    )
    with pytest.raises(ClaimError):
        load_spec_from_toml(toml)


# ── settlement ────────────────────────────────────────────────────────────
def test_settle_passing_falsifier_validated(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    rec = lock_claim(store, _spec(falsifiers=[list(_PASS)]), root=repo)
    settled = settle_claim(store, rec["claim_id"], root=repo)
    assert settled["settlement"]["status"] == "VALIDATED"
    assert settled["settlement"]["settled_at"]


def test_settle_failing_falsifier_contradicted(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    rec = lock_claim(store, _spec(falsifiers=[list(_FAIL)]), root=repo)
    settled = settle_claim(store, rec["claim_id"], root=repo)
    assert settled["settlement"]["status"] == "CONTRADICTED"


def test_settle_must_not_break_failure_recorded(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    rec = lock_claim(
        store, _spec(falsifiers=[list(_PASS)], must_not_break=[list(_FAIL)]), root=repo
    )
    settled = settle_claim(store, rec["claim_id"], root=repo)
    assert settled["settlement"]["status"] == "CONTRADICTED"
    roles = {c["role"] for c in settled["settlement"]["commands"]}
    assert "must_not_break" in roles


def test_settle_unrunnable_command_unsettled(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    rec = lock_claim(
        store, _spec(falsifiers=[["definitely-not-a-real-binary-xyz"]]), root=repo
    )
    settled = settle_claim(store, rec["claim_id"], root=repo)
    assert settled["settlement"]["status"] == "UNSETTLED"
    cmd = settled["settlement"]["commands"][0]
    assert cmd["outcome"] == "UNRUNNABLE"
    assert "not found" in cmd["error"]


def test_settle_captures_changed_files(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    rec = lock_claim(store, _spec(falsifiers=[list(_PASS)]), root=repo)
    (repo / "packages" / "cart" / "checkout.py").write_text("x = 99\n")
    settled = settle_claim(store, rec["claim_id"], root=repo)
    assert "packages/cart/checkout.py" in settled["settlement"]["changed_files"]


def test_settle_detects_scope_drift(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    rec = lock_claim(store, _spec(falsifiers=[list(_PASS)]), root=repo)
    (repo / "packages" / "payments" / "refund.py").write_text("y = 99\n")
    settled = settle_claim(store, rec["claim_id"], root=repo)
    assert "packages/payments/refund.py" in settled["settlement"]["scope_drift_files"]
    assert settled["settlement"]["status"] == "SCOPE_DRIFT"


def test_settle_unknown_claim_raises(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    with pytest.raises(ClaimError):
        settle_claim(store, "clm_does_not_exist", root=repo)


def test_settle_cannot_replace_falsifier(repo: Path) -> None:
    # The sealed falsifier is the only check run. Mutating the lock file's
    # later record does not change which command settlement re-reads, because
    # settlement reads the latest record's sealed falsifiers, not an argument.
    store = MemoryStore.from_paths(root=repo)
    rec = lock_claim(store, _spec(falsifiers=[list(_FAIL)]), root=repo)
    settled = settle_claim(store, rec["claim_id"], root=repo)
    # settle takes no command argument at all — the sealed FAIL command runs.
    assert settled["settlement"]["status"] == "CONTRADICTED"
    assert settled["settlement"]["commands"][0]["command"] == list(_FAIL)


# ── CLI surface ───────────────────────────────────────────────────────────
def test_cli_claim_lock_list_show(repo: Path, capsys) -> None:
    toml = repo / "claim.toml"
    toml.write_text(
        'intent = "fix x"\nscope_path = "packages/cart"\n'
        f"[[falsifiers]]\ncommand = {json.dumps(_PASS)}\n"
    )
    assert main(["claim", "lock", "--from-file", str(toml)]) == 0
    out = capsys.readouterr().out
    assert "Locked claim clm_" in out

    assert main(["claim", "list"]) == 0
    listed = capsys.readouterr().out
    assert "LOCKED" in listed


def test_cli_claim_lock_rejects_string_in_toml(repo: Path) -> None:
    toml = repo / "claim.toml"
    toml.write_text(
        'intent = "x"\nscope_path = "packages/cart"\n'
        '[[falsifiers]]\ncommand = "pytest tests/"\n'
    )
    assert main(["claim", "lock", "--from-file", str(toml)]) == 2


def test_cli_claim_lock_flag_mode(repo: Path) -> None:
    rc = main(
        [
            "claim",
            "lock",
            "--intent",
            "fix x",
            "--scope-path",
            "packages/cart",
            "--falsifier",
            "python -c pass",
        ]
    )
    assert rc == 0


def test_cli_claim_settle_validated_exit_zero(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    rec = lock_claim(store, _spec(falsifiers=[list(_PASS)]), root=repo)
    assert main(["claim", "settle", rec["claim_id"]]) == 0


def test_cli_claim_settle_contradicted_exit_one(repo: Path) -> None:
    store = MemoryStore.from_paths(root=repo)
    rec = lock_claim(store, _spec(falsifiers=[list(_FAIL)]), root=repo)
    assert main(["claim", "settle", rec["claim_id"]]) == 1
