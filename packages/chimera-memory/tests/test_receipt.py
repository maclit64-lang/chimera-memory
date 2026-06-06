"""Slice 3: receipt builder + text/JSON formatters.

Format must include FILES/GIT/COMMIT lines (correction 2). Drift must be scoped
to the session's own store; if sparse/unavailable → INSUFFICIENT_DATA (correction 3).
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from chimera_memory.receipt import (
    build_receipt,
    format_receipt_json,
    format_receipt_text,
)
from chimera_memory.session import (
    AttributionConfidence,
    FinalStatus,
    IdentitySource,
    Session,
)
from chimera_memory.storage import MemoryStore


def _init_store(tmp_path: Path) -> MemoryStore:
    store = MemoryStore.from_paths(root=tmp_path)
    store.initialize()
    return store


def _closed_session(
    *,
    sid: str = "sess-20260603T200000Z-a1b2c3d4",
    task: str = "fix bug",
    files_changed_during: int = 3,
    end_dirty: bool = True,
    end_commit: str = "9e8a7b6c",
    start_commit: str = "b4fea595",
    final: FinalStatus = FinalStatus.PASSED,
    commands: list[str] | None = None,
    attribution: AttributionConfidence = AttributionConfidence.MEDIUM,
    identity_source: IdentitySource = IdentitySource.ENV_VAR,
) -> Session:
    return Session(
        session_id=sid,
        repo_path="/tmp/repo",
        branch="main",
        task_label=task,
        agent_app="ci-bot",
        model="claude-opus-4",
        attribution_confidence=attribution,
        identity_source=identity_source,
        started_at="2026-06-03T20:00:00+00:00",
        ended_at="2026-06-03T20:10:00+00:00",
        start_commit=start_commit,
        end_commit=end_commit,
        end_dirty_state=end_dirty,
        files_changed_during=files_changed_during,
        commands_observed=commands or [],
        final_status=final,
    )


# -----------------------------------------------------------------------------
# build_receipt — drift scoping
# -----------------------------------------------------------------------------


def test_build_receipt_returns_all_fields(tmp_path) -> None:
    s = _closed_session()
    r = build_receipt(s.to_dict(), root=tmp_path)
    for key in (
        "task_label", "session_id", "started_at", "ended_at",
        "agent", "git", "outcome", "drift", "commands_observed",
    ):
        assert key in r, f"missing key {key}"


def test_build_receipt_drift_insufficient_when_no_claims(tmp_path) -> None:
    _init_store(tmp_path)
    s = _closed_session()
    r = build_receipt(s.to_dict(), root=tmp_path)
    assert r["drift"] == "INSUFFICIENT_DATA"


def test_build_receipt_drift_insufficient_when_sparse(tmp_path) -> None:
    """< 30 settled claims in the store → INSUFFICIENT_DATA (matches drift's min_claims)."""
    from chimera_memory.ledger import record_claim

    def _ev():
        return {
            "ref_type": "external",
            "ref_id": "git:abc",
            "available_at": datetime(2026, 6, 3, tzinfo=UTC).isoformat(),
            "content_hash": "sha256:abc",
        }

    # Write 3 claims (well below min_claims=30) to the same tmp_path store
    for i in range(3):
        record_claim(
            title=f"c{i}", summary=f"s{i}", predicted=True,
            evidence=[_ev()], root=tmp_path, claim_time=datetime(2026, 6, 3, tzinfo=UTC),
            agent_id="a", model_version="m", task_type="t",
        )
    s = _closed_session()
    r = build_receipt(s.to_dict(), root=tmp_path)
    assert r["drift"] == "INSUFFICIENT_DATA"


def test_build_receipt_drift_ok_when_groups_ok(tmp_path) -> None:
    """When all drift groups return OK, the receipt shows OK."""
    s = _closed_session()
    fake_drift = {"groups": [{"status": "OK"}, {"status": "OK"}]}
    with patch("chimera_memory.receipt.detect_drift", return_value=fake_drift):
        r = build_receipt(s.to_dict(), root=tmp_path)
    assert r["drift"] == "OK"


def test_build_receipt_drift_advisory_when_any_group_advisory(tmp_path) -> None:
    """If any drift group is DRIFT_ADVISORY, the receipt shows DRIFT_ADVISORY."""
    s = _closed_session()
    fake_drift = {"groups": [{"status": "OK"}, {"status": "DRIFT_ADVISORY"}]}
    with patch("chimera_memory.receipt.detect_drift", return_value=fake_drift):
        r = build_receipt(s.to_dict(), root=tmp_path)
    assert r["drift"] == "DRIFT_ADVISORY"


def test_build_receipt_drift_scoped_to_session_repo_path(tmp_path) -> None:
    """Drift is computed against the session's repo_path, not cwd."""
    _init_store(tmp_path)
    s = _closed_session()
    captured = {}

    def fake_detect(*, root=None, memory_dir=None, store_path=None, **kwargs):
        captured["root"] = root
        captured["memory_dir"] = memory_dir
        captured["store_path"] = store_path
        return {"groups": []}

    with patch("chimera_memory.receipt.detect_drift", side_effect=fake_detect):
        build_receipt(s.to_dict(), root=tmp_path)  # explicit root wins
    # The explicit root argument is passed through to detect_drift
    assert captured["root"] == tmp_path


def test_build_receipt_drift_uses_session_repo_when_no_explicit_root(tmp_path) -> None:
    """If no explicit root, drift is computed against session.repo_path (correction 3)."""
    s = _closed_session()  # repo_path="/tmp/repo"
    captured = {}

    def fake_detect(*, root=None, memory_dir=None, store_path=None, **kwargs):
        captured["root"] = root
        return {"groups": []}

    with patch("chimera_memory.receipt.detect_drift", side_effect=fake_detect):
        build_receipt(s.to_dict())  # no explicit root
    # Should fall back to session.repo_path
    assert str(captured["root"]) == "/tmp/repo"


# -----------------------------------------------------------------------------
# format_receipt_text — FILES / GIT / COMMIT lines
# -----------------------------------------------------------------------------


def test_format_receipt_text_includes_files_git_commit_lines() -> None:
    """Correction 2: receipt must include FILES <N> changed, GIT clean|dirty, COMMIT <sha or unknown>."""
    s = _closed_session(files_changed_during=3, end_dirty=True, end_commit="9e8a7b6c")
    r = build_receipt(s.to_dict(), root="/tmp/fake")
    # Force INSUFFICIENT_DATA to avoid drift
    r["drift"] = "INSUFFICIENT_DATA"
    text = format_receipt_text(r)
    assert "FILES       3 changed" in text
    assert "GIT         dirty" in text
    assert "COMMIT      9e8a7b6c" in text


def test_format_receipt_text_includes_clean_git_line() -> None:
    s = _closed_session(end_dirty=False, end_commit="b4fea59", files_changed_during=0)
    r = build_receipt(s.to_dict(), root="/tmp/fake")
    r["drift"] = "INSUFFICIENT_DATA"
    text = format_receipt_text(r)
    assert "FILES       0 changed" in text
    assert "GIT         clean" in text
    assert "COMMIT      b4fea59" in text


def test_format_receipt_text_unknown_commit_when_not_set() -> None:
    s = _closed_session(end_commit="unknown", end_dirty=False, files_changed_during=0)
    r = build_receipt(s.to_dict(), root="/tmp/fake")
    r["drift"] = "INSUFFICIENT_DATA"
    text = format_receipt_text(r)
    assert "COMMIT      unknown" in text


def test_format_receipt_text_basic_fields() -> None:
    s = _closed_session(task="fix checkout", attribution=AttributionConfidence.MEDIUM)
    r = build_receipt(s.to_dict(), root="/tmp/fake")
    r["drift"] = "INSUFFICIENT_DATA"
    text = format_receipt_text(r)
    assert "Chimera Session Receipt" in text
    assert "Task: fix checkout" in text
    assert "Agent: ci-bot" in text
    assert "Model: claude-opus-4" in text
    assert "Attribution: medium" in text
    assert "Identity source: env_var" in text
    assert "Start commit: b4fea595" in text


def test_format_receipt_text_commands_observed_none() -> None:
    s = _closed_session(commands=[])
    r = build_receipt(s.to_dict(), root="/tmp/fake")
    r["drift"] = "INSUFFICIENT_DATA"
    text = format_receipt_text(r)
    assert "Commands observed: (none)" in text


def test_format_receipt_text_commands_observed_listed() -> None:
    s = _closed_session(commands=["pytest -q", "pytest tests/"])
    r = build_receipt(s.to_dict(), root="/tmp/fake")
    r["drift"] = "INSUFFICIENT_DATA"
    text = format_receipt_text(r)
    assert "Commands observed:" in text
    assert "- pytest -q" in text
    assert "- pytest tests/" in text


def test_format_receipt_text_outcome_passed() -> None:
    s = _closed_session(final=FinalStatus.PASSED)
    r = build_receipt(s.to_dict(), root="/tmp/fake")
    r["drift"] = "INSUFFICIENT_DATA"
    text = format_receipt_text(r)
    assert "Outcome:" in text
    assert "PASSED" in text


def test_format_receipt_text_drift_status() -> None:
    s = _closed_session()
    r = build_receipt(s.to_dict(), root="/tmp/fake")
    r["drift"] = "OK"
    text = format_receipt_text(r)
    assert "Drift: OK" in text


def test_format_receipt_text_ends_with_newline() -> None:
    s = _closed_session()
    r = build_receipt(s.to_dict(), root="/tmp/fake")
    r["drift"] = "INSUFFICIENT_DATA"
    text = format_receipt_text(r)
    assert text.endswith("\n")


# -----------------------------------------------------------------------------
# format_receipt_json
# -----------------------------------------------------------------------------


def test_format_receipt_json_is_valid_json() -> None:
    s = _closed_session()
    r = build_receipt(s.to_dict(), root="/tmp/fake")
    r["drift"] = "INSUFFICIENT_DATA"
    text = format_receipt_json(r)
    parsed = json.loads(text)
    assert parsed["task_label"] == s.task_label
    assert parsed["session_id"] == s.session_id
    assert parsed["git"]["files_changed_during"] == s.files_changed_during
    assert parsed["agent"]["attribution"] == "medium"


def test_format_receipt_json_ends_with_newline() -> None:
    s = _closed_session()
    r = build_receipt(s.to_dict(), root="/tmp/fake")
    r["drift"] = "INSUFFICIENT_DATA"
    text = format_receipt_json(r)
    assert text.endswith("\n")

# =============================================================================
# C3 tests — commands_observed derived from linked claims
# =============================================================================


def _seed_passing_test(tmp_path: Path) -> None:
    (tmp_path / "test_pass.py").write_text("def test_pass():\n    assert True\n")


def _run(argv: list[str], tmp_path: Path, monkeypatch) -> int:
    from chimera_memory.cli import main
    monkeypatch.chdir(tmp_path)
    return main(argv)


def test_receipt_includes_wrapped_commands_for_session_claims(
    tmp_path, monkeypatch
) -> None:
    """build_receipt populates commands_observed from claims linked to the session."""
    _init_store(tmp_path)
    _seed_passing_test(tmp_path)
    _run(
        ["session", "start", "--branch", "main", "--task-label", "t",
         "--agent", "kiro", "--model", "claude-sonnet-4.6"],
        tmp_path, monkeypatch,
    )
    _run(["wrap", "--task-type", "test", "pytest", "-q", "test_pass.py"], tmp_path, monkeypatch)
    _run(["session", "end", "--status", "PASSED"], tmp_path, monkeypatch)

    store = MemoryStore.from_paths(root=tmp_path)
    closed = store.list_sessions()
    receipt = build_receipt(closed[0], root=tmp_path)
    assert len(receipt["commands_observed"]) == 1
    cmd = receipt["commands_observed"][0]
    assert "pytest" in cmd["command"]
    assert cmd["task_type"] == "test"
    assert cmd["status"] in ("validated", "proposed", "contradicted")


def test_receipt_text_no_longer_says_none_when_session_has_wrapped_claims(
    tmp_path, monkeypatch
) -> None:
    """Text receipt does not show '(none)' when the session has linked wrap claims."""
    _init_store(tmp_path)
    _seed_passing_test(tmp_path)
    _run(
        ["session", "start", "--branch", "main", "--task-label", "t",
         "--agent", "kiro", "--model", "m"],
        tmp_path, monkeypatch,
    )
    _run(["wrap", "--task-type", "docs", "pytest", "-q", "test_pass.py"], tmp_path, monkeypatch)
    _run(["session", "end", "--status", "PASSED"], tmp_path, monkeypatch)

    store = MemoryStore.from_paths(root=tmp_path)
    closed = store.list_sessions()
    receipt = build_receipt(closed[0], root=tmp_path)
    text = format_receipt_text(receipt)
    assert "Commands observed:" in text
    assert "(none)" not in text.split("Commands observed:")[1].split("\n")[0]
    assert "docs" in text


def test_receipt_json_includes_commands_observed_for_wrapped_claims(
    tmp_path, monkeypatch
) -> None:
    """JSON receipt commands_observed is a list of dicts with command/task_type/status."""
    _init_store(tmp_path)
    _seed_passing_test(tmp_path)
    _run(
        ["session", "start", "--branch", "main", "--task-label", "t",
         "--agent", "a", "--model", "m"],
        tmp_path, monkeypatch,
    )
    _run(["wrap", "--task-type", "review", "pytest", "-q", "test_pass.py"], tmp_path, monkeypatch)
    _run(["session", "end", "--status", "PASSED"], tmp_path, monkeypatch)

    store = MemoryStore.from_paths(root=tmp_path)
    closed = store.list_sessions()
    receipt = build_receipt(closed[0], root=tmp_path)
    raw = format_receipt_json(receipt)
    parsed = json.loads(raw)
    cmds = parsed["commands_observed"]
    assert isinstance(cmds, list)
    assert len(cmds) == 1
    assert cmds[0]["task_type"] == "review"
    assert "command" in cmds[0]
    assert "status" in cmds[0]
    assert "claim_id" in cmds[0]


def test_receipt_still_says_none_when_session_has_no_claims(
    tmp_path, monkeypatch
) -> None:
    """Session with no wrapped commands still shows 'Commands observed: (none)'."""
    _init_store(tmp_path)
    _run(
        ["session", "start", "--branch", "main", "--task-label", "t",
         "--agent", "a", "--model", "m"],
        tmp_path, monkeypatch,
    )
    _run(["session", "end", "--status", "PASSED"], tmp_path, monkeypatch)

    store = MemoryStore.from_paths(root=tmp_path)
    closed = store.list_sessions()
    receipt = build_receipt(closed[0], root=tmp_path)
    text = format_receipt_text(receipt)
    assert "Commands observed: (none)" in text


# =============================================================================
# F6A tests — markdown receipt format
# =============================================================================


def test_format_receipt_markdown_includes_session_summary(tmp_path) -> None:
    """Markdown receipt includes session_id, task_label, agent, model, outcome."""
    from chimera_memory.receipt import format_receipt_markdown

    s = _closed_session(task="my-task", final=FinalStatus.PASSED)
    r = build_receipt(s.to_dict(), root="/tmp/fake")
    r["drift"] = "INSUFFICIENT_DATA"
    md = format_receipt_markdown(r)
    assert "# Chimera Memory Receipt" in md
    assert s.session_id in md
    assert "my-task" in md
    assert "ci-bot" in md
    assert "PASSED" in md


def test_format_receipt_markdown_includes_commands_observed(tmp_path, monkeypatch) -> None:
    """Markdown receipt shows wrapped commands with task_type and status."""
    from chimera_memory.cli import main
    from chimera_memory.receipt import format_receipt_markdown

    _init_store(tmp_path)
    _seed_passing_test(tmp_path)
    monkeypatch.chdir(tmp_path)
    main(["session", "start", "--branch", "main", "--task-label", "t",
          "--agent", "kiro", "--model", "m"])
    main(["wrap", "--task-type", "test", "pytest", "-q", "test_pass.py"])
    main(["session", "end", "--status", "PASSED"])

    store = MemoryStore.from_paths(root=tmp_path)
    closed = store.list_sessions()
    receipt = build_receipt(closed[0], root=tmp_path)
    md = format_receipt_markdown(receipt)
    assert "## Commands Observed" in md
    assert "pytest" in md
    assert "test" in md
    assert "VALIDATED" in md


def test_receipt_latest_markdown_cli_outputs_markdown(tmp_path, monkeypatch, capsys) -> None:
    """receipt latest --markdown outputs markdown starting with # Chimera Memory Receipt."""
    from chimera_memory.cli import main as _main

    _init_store(tmp_path)
    _seed_passing_test(tmp_path)
    monkeypatch.chdir(tmp_path)
    _main(["session", "start", "--branch", "main", "--task-label", "t",
           "--agent", "a", "--model", "m"])
    _main(["session", "end", "--status", "PASSED"])
    capsys.readouterr()
    code = _main(["receipt", "latest", "--markdown"])
    assert code == 0
    out = capsys.readouterr().out
    assert "# Chimera Memory Receipt" in out
    assert "## Session" in out


def test_receipt_show_markdown_cli_outputs_markdown(tmp_path, monkeypatch, capsys) -> None:
    """receipt show <id> --markdown outputs markdown."""
    import re

    from chimera_memory.cli import main as _main

    _init_store(tmp_path)
    _seed_passing_test(tmp_path)
    monkeypatch.chdir(tmp_path)
    _main(["session", "start", "--branch", "main", "--task-label", "t",
           "--agent", "a", "--model", "m"])
    _main(["session", "end", "--status", "PASSED"])
    _main(["session", "list"])
    list_out = capsys.readouterr().out
    m = re.search(r"sess-[\w-]+", list_out)
    assert m is not None
    sid = m.group(0)
    capsys.readouterr()
    code = _main(["receipt", "show", sid, "--markdown"])
    assert code == 0
    out = capsys.readouterr().out
    assert "# Chimera Memory Receipt" in out


# =============================================================================
# I2B tests — integrity in receipts
# =============================================================================


def _seed_passing_test(tmp_path: Path) -> None:
    (tmp_path / "test_pass.py").write_text("def test_pass():\n    assert True\n")


def test_receipt_text_includes_integrity_summary(tmp_path, monkeypatch) -> None:
    """Receipt text includes an Integrity: line."""
    from chimera_memory.cli import main

    _init_store(tmp_path)
    _seed_passing_test(tmp_path)
    monkeypatch.chdir(tmp_path)
    main(["session", "start", "--branch", "main", "--task-label", "t",
          "--agent", "a", "--model", "m"])
    main(["wrap", "--task-type", "test", "pytest", "-q", "test_pass.py"])
    main(["session", "end", "--status", "PASSED"])

    store = MemoryStore.from_paths(root=tmp_path)
    closed = store.list_sessions()
    receipt = build_receipt(closed[0], root=tmp_path)
    text = format_receipt_text(receipt)
    assert "Integrity:" in text


def test_receipt_json_includes_integrity_summary(tmp_path, monkeypatch) -> None:
    """Receipt JSON includes an 'integrity' object."""
    import json

    from chimera_memory.cli import main

    _init_store(tmp_path)
    _seed_passing_test(tmp_path)
    monkeypatch.chdir(tmp_path)
    main(["session", "start", "--branch", "main", "--task-label", "t",
          "--agent", "a", "--model", "m"])
    main(["wrap", "--task-type", "test", "pytest", "-q", "test_pass.py"])
    main(["session", "end", "--status", "PASSED"])

    store = MemoryStore.from_paths(root=tmp_path)
    closed = store.list_sessions()
    receipt = build_receipt(closed[0], root=tmp_path)
    parsed = json.loads(format_receipt_json(receipt))
    assert "integrity" in parsed
    assert parsed["integrity"]["status"] in ("OK", "LEGACY_UNSIGNED", "BROKEN")
    assert "broken_records" in parsed["integrity"]


def test_receipt_markdown_includes_integrity_section(tmp_path, monkeypatch) -> None:
    """Receipt markdown includes ## Integrity section."""
    from chimera_memory.cli import main
    from chimera_memory.receipt import format_receipt_markdown

    _init_store(tmp_path)
    _seed_passing_test(tmp_path)
    monkeypatch.chdir(tmp_path)
    main(["session", "start", "--branch", "main", "--task-label", "t",
          "--agent", "a", "--model", "m"])
    main(["session", "end", "--status", "PASSED"])

    store = MemoryStore.from_paths(root=tmp_path)
    closed = store.list_sessions()
    receipt = build_receipt(closed[0], root=tmp_path)
    md = format_receipt_markdown(receipt)
    assert "## Integrity" in md
    assert "Status" in md


def test_receipt_integrity_legacy_unsigned_is_not_failure(tmp_path, monkeypatch) -> None:
    """Receipt with no integrity.jsonl shows the status honestly (OK or LEGACY_UNSIGNED),
    and never shows BROKEN for a clean empty store."""
    from chimera_memory.cli import main

    _init_store(tmp_path)
    monkeypatch.chdir(tmp_path)
    main(["session", "start", "--branch", "main", "--task-label", "t",
          "--agent", "a", "--model", "m"])
    main(["session", "end", "--status", "PASSED"])

    store = MemoryStore.from_paths(root=tmp_path)
    closed = store.list_sessions()
    receipt = build_receipt(closed[0], root=tmp_path)
    text = format_receipt_text(receipt)
    assert "Integrity:" in text
    assert "BROKEN" not in text
