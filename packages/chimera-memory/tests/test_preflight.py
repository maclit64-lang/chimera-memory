"""Tests for chimera-memory preflight command."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from chimera_memory_types.finding import EvidenceRef, EvidenceRefType

from chimera_memory.cli import main
from chimera_memory.errata import add_errata
from chimera_memory.ledger import record_claim, settle_claim
from chimera_memory.preflight import (
    build_preflight,
    format_preflight_text,
    infer_scopes_from_git,
    recommended_checks_for_scopes,
)
from chimera_memory.storage import MemoryStore

_T0 = datetime(2026, 1, 1, 12, tzinfo=UTC)
_T1 = datetime(2026, 1, 1, 13, tzinfo=UTC)
_CLEAN = {
    "harness_id": "h", "attribution_confidence": "high",
    "identity_source": "cli_flag", "session_id": "sess-001",
}


def _ev() -> EvidenceRef:
    return EvidenceRef(ref_type=EvidenceRefType.EXTERNAL, ref_id="r", available_at=_T0)


def _make(
    root: Path, *,
    origin: str = "organic_real",
    scope_paths: list[str] | None = None,
    task_type: str = "test",
    observed: bool = True,
    repair_loop_id: str | None = None,
    repair_phase: str | None = None,
) -> str:
    extra = {**_CLEAN, "failure_origin": origin, "verification_scope": "package",
              "scope_paths": scope_paths or []}
    if repair_loop_id:
        extra["repair_loop_id"] = repair_loop_id
    if repair_phase:
        extra["repair_phase"] = repair_phase
    cid = record_claim(
        title="t", summary="s", predicted=True, evidence=[_ev()],
        root=root, claim_time=_T0, agent_id="a", model_version="m",
        task_type=task_type, extra_metadata=extra,
    )
    settle_claim(cid, observed, _T1, root=root)
    return cid


# ---------------------------------------------------------------------------


def test_preflight_empty_ledger(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / ".chimera-memory")
    store.ensure()
    report = build_preflight(store)
    assert report.matching_claim_count == 0
    assert "No matching evidence" in " ".join(report.dq_caveats)
    assert report.recommended_checks  # generic checks still provided


def test_preflight_filters_by_scope_path(tmp_path: Path) -> None:
    _make(tmp_path, scope_paths=["packages/chimera-memory"])
    _make(tmp_path, scope_paths=["packages/other"])
    store = MemoryStore.from_paths(root=tmp_path)
    report = build_preflight(store, scope_paths=["packages/chimera-memory"])
    assert report.matching_claim_count == 1


def test_preflight_includes_recent_failures(tmp_path: Path) -> None:
    _make(tmp_path, scope_paths=["packages/chimera-memory"], observed=False)
    store = MemoryStore.from_paths(root=tmp_path)
    report = build_preflight(store, scope_paths=["packages/chimera-memory"])
    assert len(report.recent_failures) == 1


def test_preflight_uses_effective_failure_origin(tmp_path: Path) -> None:
    """Errata-corrected invocation_artifact shows correct effective origin."""
    cid = _make(tmp_path, scope_paths=["packages/chimera-memory"],
                origin="organic_real", observed=False)
    mem = tmp_path / ".chimera-memory"
    add_errata(mem, cid, "invocation_artifact", "shell quoting error")
    store = MemoryStore.from_paths(root=tmp_path)
    report = build_preflight(store, scope_paths=["packages/chimera-memory"])
    assert report.recent_failures[0]["effective_failure_origin"] == "invocation_artifact"
    assert report.recent_failures[0]["errata_applied"] is True


def test_preflight_excludes_invocation_artifact_with_organic_filter(tmp_path: Path) -> None:
    cid = _make(tmp_path, scope_paths=["packages/chimera-memory"],
                origin="organic_real", observed=False)
    mem = tmp_path / ".chimera-memory"
    add_errata(mem, cid, "invocation_artifact", "typo")
    store = MemoryStore.from_paths(root=tmp_path)
    report = build_preflight(store, scope_paths=["packages/chimera-memory"],
                              failure_origin="organic_real")
    # After errata correction, this claim should not match organic_real filter
    assert report.matching_claim_count == 0


def test_preflight_includes_repair_loops(tmp_path: Path) -> None:
    _make(tmp_path, scope_paths=["packages/chimera-memory"],
          repair_loop_id="loop-1", repair_phase="baseline", observed=False)
    _make(tmp_path, scope_paths=["packages/chimera-memory"],
          repair_loop_id="loop-1", repair_phase="same_scope_after_fix")
    store = MemoryStore.from_paths(root=tmp_path)
    report = build_preflight(store, scope_paths=["packages/chimera-memory"])
    loop = next((rl for rl in report.repair_loops if rl["repair_loop_id"] == "loop-1"), None)
    assert loop is not None
    assert loop["complete"] is True


def test_preflight_json_has_stable_keys(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / ".chimera-memory")
    store.ensure()
    d = build_preflight(store).to_dict()
    for key in ("schema_version", "filters", "matching_claim_count", "recent_failures",
                "repair_loops", "recommended_checks", "dq_caveats",
                "m2b_readiness_level", "notes"):
        assert key in d, f"missing key: {key}"


def test_preflight_text_includes_advisory_caveat(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / ".chimera-memory")
    store.ensure()
    text = format_preflight_text(build_preflight(store))
    assert "advisory" in text.lower() or "advisory" in text
    assert "routing" in text.lower()


def test_preflight_recommended_checks_chimera_memory_scope(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / ".chimera-memory")
    store.ensure()
    report = build_preflight(store, scope_paths=["packages/chimera-memory"])
    assert any("pytest" in c for c in report.recommended_checks)
    assert any("mypy" in c for c in report.recommended_checks)
    assert any("ruff" in c for c in report.recommended_checks)


def test_preflight_redaction_in_failure_command(tmp_path: Path, monkeypatch) -> None:
    """Fake secret in wrapped_args is redacted in preflight failure display."""
    monkeypatch.chdir(tmp_path)
    fake_secret = "ghp_FakePreflight1234567890ABCDEFG"
    main(["session", "start", "--branch", "b", "--task-label", "t",
          "--agent", "a", "--model", "m", "--harness-id", "h"])
    main(["wrap", "--failure-origin", "organic_real", "--verification-scope", "package",
          "--scope-path", "packages/chimera-memory",
          "--", "python", "-c",
          "import sys; sys.exit(1)"])
    main(["session", "end", "--status", "FAILED"])
    store = MemoryStore.from_paths(root=tmp_path)
    report = build_preflight(store, scope_paths=["packages/chimera-memory"])
    for f in report.recent_failures:
        assert fake_secret not in str(f.get("command", ""))
        assert fake_secret not in str(f.get("witness", ""))


def test_preflight_invalid_failure_origin_returns_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    ret = main(["preflight", "--scope-path", "packages/chimera-memory",
                "--failure-origin", "not_valid"])
    assert ret == 2


def test_preflight_cli_json(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".chimera-memory").mkdir()
    ret = main(["preflight", "--scope-path", "packages/chimera-memory", "--json"])
    assert ret == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert "matching_claim_count" in parsed


# ---------------------------------------------------------------------------
# Tests for --from-git / changed-scope detection
# ---------------------------------------------------------------------------


def test_infer_scopes_from_git_memory_package(tmp_path: Path) -> None:
    """Changed file under packages/chimera-memory infers that scope."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True, capture_output=True)
    # Stage a file in packages/chimera-memory/src/
    p = tmp_path / "packages/chimera-memory/src/foo.py"
    p.parent.mkdir(parents=True)
    p.write_text("# change\n")
    subprocess.run(["git", "add", "packages/chimera-memory/src/foo.py"], cwd=tmp_path, check=True, capture_output=True)
    changed, scopes = infer_scopes_from_git(tmp_path)
    assert "packages/chimera-memory/src/foo.py" in changed
    assert "packages/chimera-memory" in scopes


def test_infer_scopes_from_git_memory_types_package(tmp_path: Path) -> None:
    """Changed file under packages/chimera-memory-types infers that scope."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True, capture_output=True)
    p = tmp_path / "packages/chimera-memory-types/src/bar.py"
    p.parent.mkdir(parents=True)
    p.write_text("# types change\n")
    subprocess.run(["git", "add", "packages/chimera-memory-types/src/bar.py"], cwd=tmp_path, check=True, capture_output=True)
    changed, scopes = infer_scopes_from_git(tmp_path)
    assert "packages/chimera-memory-types/src/bar.py" in changed
    assert "packages/chimera-memory-types" in scopes


def test_infer_scopes_from_git_multiple_scopes(tmp_path: Path) -> None:
    """Changes in two packages produce both scope paths."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "packages/chimera-memory/src/x.py").parent.mkdir(parents=True)
    (tmp_path / "packages/chimera-memory/src/x.py").write_text("#\n")
    (tmp_path / "packages/chimera-memory-types/src/y.py").parent.mkdir(parents=True)
    (tmp_path / "packages/chimera-memory-types/src/y.py").write_text("#\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    _, scopes = infer_scopes_from_git(tmp_path)
    assert "packages/chimera-memory" in scopes
    assert "packages/chimera-memory-types" in scopes


def test_infer_scopes_from_git_docs_only(tmp_path: Path) -> None:
    """Changes in docs/ only infer docs scope."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True, capture_output=True)
    p = tmp_path / "docs/README.md"
    p.parent.mkdir(parents=True)
    p.write_text("# docs\n")
    subprocess.run(["git", "add", "docs/README.md"], cwd=tmp_path, check=True, capture_output=True)
    _, scopes = infer_scopes_from_git(tmp_path)
    assert "docs" in scopes


def test_infer_scopes_from_git_no_git_repo(tmp_path: Path) -> None:
    """No git available returns empty lists cleanly."""
    changed, scopes = infer_scopes_from_git(tmp_path)
    assert changed == []
    assert scopes == []


def test_infer_scopes_from_git_no_changes(tmp_path: Path) -> None:
    """Clean git tree returns empty scope inference."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True)
    changed, scopes = infer_scopes_from_git(tmp_path)
    assert changed == []
    assert scopes == []


def test_build_preflight_from_git_sets_source_git_changes(tmp_path: Path) -> None:
    """--from-git with changes sets source=git_changes."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True, capture_output=True)
    p = tmp_path / "packages/chimera-memory/src/foo.py"
    p.parent.mkdir(parents=True)
    p.write_text("#\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    store = MemoryStore(tmp_path / ".chimera-memory")
    store.ensure()
    report = build_preflight(store, from_git=True)
    assert report.source == "git_changes"
    assert report.inferred_scope_paths == ["packages/chimera-memory"]
    assert len(report.changed_files) >= 1


def test_build_preflight_from_git_no_changes_source_none(tmp_path: Path) -> None:
    """--from-git with no changes sets source=none and uses generic checks."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    store = MemoryStore(tmp_path / ".chimera-memory")
    store.ensure()
    report = build_preflight(store, from_git=True)
    assert report.source == "none"
    assert report.inferred_scope_paths == []
    assert report.recommended_checks  # generic checks returned


def test_build_preflight_from_git_json_contains_stable_keys(tmp_path: Path) -> None:
    """JSON from --from-git has all required v2 keys."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True, capture_output=True)
    store = MemoryStore(tmp_path / ".chimera-memory")
    store.ensure()
    d = build_preflight(store, from_git=True).to_dict()
    for key in ("schema_version", "source", "changed_files", "inferred_scope_paths",
                "filters", "matching_claim_count", "recent_failures",
                "repair_loops", "recommended_checks", "dq_caveats",
                "m2b_readiness_level", "notes"):
        assert key in d, f"missing key: {key}"


def test_recommended_checks_for_scopes_matches_inferred(tmp_path: Path) -> None:
    """recommended_checks_for_scopes returns correct checks per inferred scope."""
    checks = recommended_checks_for_scopes(["packages/chimera-memory"])
    assert any("pytest" in c and "chimera-memory" in c for c in checks)
    checks_types = recommended_checks_for_scopes(["packages/chimera-memory-types"])
    assert any("mypy" in c and "chimera-memory-types" in c for c in checks_types)
    checks_docs = recommended_checks_for_scopes(["docs"])
    assert any("ruff" in c for c in checks_docs)


def test_preflight_cli_from_git(tmp_path: Path, monkeypatch, capsys) -> None:
    """CLI --from-git flag produces JSON output."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True, capture_output=True)
    p = tmp_path / "packages/chimera-memory/src/foo.py"
    p.parent.mkdir(parents=True)
    p.write_text("#\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".chimera-memory").mkdir()
    ret = main(["preflight", "--from-git", "--json"])
    assert ret == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["source"] == "git_changes"
    assert "packages/chimera-memory" in parsed["inferred_scope_paths"]
    assert "recommended_checks" in parsed


def test_preflight_explicit_scope_still_works(tmp_path: Path, monkeypatch, capsys) -> None:
    """Explicit --scope-path without --from-git works as before."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".chimera-memory").mkdir()
    ret = main(["preflight", "--scope-path", "packages/chimera-memory"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "Source:" in out
    assert "Matching claims:" in out


def test_preflight_output_is_advisory_no_routing(tmp_path: Path, monkeypatch, capsys) -> None:
    """Text output contains routing/merge-gate disclaimer."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".chimera-memory").mkdir()
    ret = main(["preflight", "--from-git"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "no routing" in out.lower() or "advisory only" in out.lower()
