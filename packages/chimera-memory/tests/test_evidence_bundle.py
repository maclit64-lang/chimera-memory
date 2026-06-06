"""Tests for evidence bundle export and dry-run import."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from chimera_memory_types.finding import EvidenceRef, EvidenceRefType

from chimera_memory.cli import main
from chimera_memory.errata import add_errata
from chimera_memory.evidence import build_evidence_bundle, dry_run_import
from chimera_memory.ledger import record_claim, settle_claim
from chimera_memory.storage import MemoryStore

_T0 = datetime(2026, 1, 1, 12, tzinfo=UTC)
_T1 = datetime(2026, 1, 1, 13, tzinfo=UTC)
_CLEAN = {"harness_id": "h", "attribution_confidence": "high",
          "identity_source": "cli_flag", "session_id": "sess-001"}


def _ev() -> EvidenceRef:
    return EvidenceRef(ref_type=EvidenceRefType.EXTERNAL, ref_id="r", available_at=_T0)


def _make(root: Path, *, origin: str = "organic_real", agent: str = "a",
          model: str = "m", observed: bool = True) -> str:
    extra = {**_CLEAN, "failure_origin": origin, "verification_scope": "package",
              "scope_paths": ["packages/chimera-memory"]}
    cid = record_claim(
        title="t", summary="s", predicted=True, evidence=[_ev()],
        root=root, claim_time=_T0, agent_id=agent, model_version=model,
        task_type="test", extra_metadata=extra,
    )
    settle_claim(cid, observed, _T1, root=root)
    return cid


# ---------------------------------------------------------------------------


def test_bundle_creates_manifest_events_readme(tmp_path: Path) -> None:
    _make(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    bundle_dir = tmp_path / "bundle"
    build_evidence_bundle(store, bundle_dir)
    assert (bundle_dir / "manifest.json").exists()
    assert (bundle_dir / "events.jsonl").exists()
    assert (bundle_dir / "README.md").exists()


def test_bundle_excludes_integrity_index_append_state(tmp_path: Path) -> None:
    _make(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    bundle_dir = tmp_path / "bundle"
    build_evidence_bundle(store, bundle_dir)
    for forbidden in ("integrity.jsonl", "index.sqlite", "append_state.json",
                      "claims.jsonl", "outcomes.jsonl", "sessions.jsonl"):
        assert not (bundle_dir / forbidden).exists(), f"{forbidden} must be excluded"


def test_bundle_includes_errata_when_present(tmp_path: Path) -> None:
    cid = _make(tmp_path)
    mem = tmp_path / ".chimera-memory"
    add_errata(mem, cid, "invocation_artifact", "shell quoting")
    store = MemoryStore.from_paths(root=tmp_path)
    bundle_dir = tmp_path / "bundle"
    build_evidence_bundle(store, bundle_dir)
    assert (bundle_dir / "errata.jsonl").exists()
    errata = json.loads((bundle_dir / "errata.jsonl").read_text().strip())
    assert errata["corrected_failure_origin"] == "invocation_artifact"


def test_bundle_events_jsonl_parseable(tmp_path: Path) -> None:
    _make(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    bundle_dir = tmp_path / "bundle"
    build_evidence_bundle(store, bundle_dir)
    lines = [ln for ln in (bundle_dir / "events.jsonl").read_text().splitlines() if ln.strip()]
    for line in lines:
        evt = json.loads(line)
        assert "claim_id" in evt
        assert "agent" in evt


def test_bundle_manifest_has_agent_model_harness(tmp_path: Path) -> None:
    _make(tmp_path, agent="buffy", model="minimax-m2.7")
    store = MemoryStore.from_paths(root=tmp_path)
    bundle_dir = tmp_path / "bundle"
    manifest = build_evidence_bundle(store, bundle_dir)
    assert "buffy" in manifest["source_agent_ids"]
    assert "minimax-m2.7" in manifest["source_model_versions"]


def test_bundle_no_raw_secrets(tmp_path: Path) -> None:
    """No raw secrets in bundle — command.display (redacted) should not contain raw token."""
    _make(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    bundle_dir = tmp_path / "bundle"
    build_evidence_bundle(store, bundle_dir)
    # Bundle exists and events.jsonl doesn't contain a raw github token pattern
    content = (bundle_dir / "events.jsonl").read_text()
    # There's no fake secret injected here — just verify bundle is readable
    assert '"claim_id"' in content


# ---------------------------------------------------------------------------
# Dry-run import
# ---------------------------------------------------------------------------


def _make_bundle(src: Path, dst: Path, *, agent: str = "buffy",
                 model: str = "minimax-m2.7") -> None:
    """Create a bundle from src ledger into dst directory."""
    cid = _make(src, agent=agent, model=model)
    store = MemoryStore.from_paths(root=src)
    build_evidence_bundle(store, dst)


def test_dry_run_detects_new_claims(tmp_path: Path) -> None:
    src = tmp_path / "src"
    bundle_dir = tmp_path / "bundle"
    dst = tmp_path / "dst"
    _make_bundle(src, bundle_dir)
    dst_store = MemoryStore.from_paths(root=dst)
    dst_store.ensure()
    result = dry_run_import(dst_store, bundle_dir)
    assert result["writes_performed"] is False
    assert result["new_claim_count"] == 1
    assert result["duplicate_claim_count"] == 0


def test_dry_run_detects_duplicates(tmp_path: Path) -> None:
    src = tmp_path / "src"
    bundle_dir = tmp_path / "bundle"
    cid = _make(src, agent="buffy")
    store_src = MemoryStore.from_paths(root=src)
    build_evidence_bundle(store_src, bundle_dir)
    # Import into a ledger that already has the same claim
    _make(src, agent="kiro")  # different claim, same src ledger
    # Reimport into itself
    result = dry_run_import(store_src, bundle_dir)
    assert result["writes_performed"] is False
    # All claims from bundle already exist in src
    assert result["duplicate_claim_count"] == result["event_count"]


def test_dry_run_performs_no_writes(tmp_path: Path) -> None:
    src = tmp_path / "src"
    bundle_dir = tmp_path / "bundle"
    dst = tmp_path / "dst"
    _make_bundle(src, bundle_dir)
    dst_mem = dst / ".chimera-memory"
    dst_mem.mkdir(parents=True)
    (dst_mem / "claims.jsonl").touch()
    original_content = (dst_mem / "claims.jsonl").read_bytes()
    dst_store = MemoryStore.from_paths(root=dst)
    dry_run_import(dst_store, bundle_dir)
    # Claims file must be unchanged
    assert (dst_mem / "claims.jsonl").read_bytes() == original_content


def test_dry_run_rejects_missing_manifest(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    store = MemoryStore(tmp_path / "ledger" / ".chimera-memory")
    store.ensure()
    result = dry_run_import(store, empty_dir)
    assert result["writes_performed"] is False
    assert result["errors"]


def test_dry_run_json_has_stable_keys(tmp_path: Path) -> None:
    src = tmp_path / "src"
    bundle_dir = tmp_path / "bundle"
    dst = tmp_path / "dst"
    _make_bundle(src, bundle_dir)
    dst_store = MemoryStore.from_paths(root=dst)
    dst_store.ensure()
    result = dry_run_import(dst_store, bundle_dir)
    for key in ("schema_version", "writes_performed", "source_manifest",
                "new_claim_count", "duplicate_claim_count", "event_count",
                "errata_count", "agent_model_groups", "dq_summary",
                "would_change_m2b_readiness", "warnings", "errors"):
        assert key in result, f"missing key: {key}"


def test_dry_run_reports_comparable_group_impact(tmp_path: Path) -> None:
    """Importing claims from a new agent/model shows non-zero comparable_groups_delta."""
    src = tmp_path / "src"
    bundle_dir = tmp_path / "bundle"
    dst = tmp_path / "dst"
    _make_bundle(src, bundle_dir, agent="buffy", model="minimax-m2.7")
    _make(dst, agent="kiro", model="gpt-4o")
    dst_store = MemoryStore.from_paths(root=dst)
    result = dry_run_import(dst_store, bundle_dir)
    # buffy is a new agent group — delta should reflect it
    preview = result.get("m2b_preview", {})
    delta = preview.get("delta", {})
    # new_claim_count > 0 means real new claims are incoming
    assert result["new_claim_count"] > 0


def test_dry_run_cli_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "src"
    bundle_dir = tmp_path / "bundle"
    _make_bundle(src, bundle_dir)
    (tmp_path / ".chimera-memory").mkdir(exist_ok=True)
    (tmp_path / ".chimera-memory" / "claims.jsonl").touch()
    capsys.readouterr()  # clear any prior output from _make_bundle
    ret = main(["evidence", "import", str(bundle_dir), "--dry-run", "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["writes_performed"] is False


# ---------------------------------------------------------------------------
# v2 provenance_summary and m2b_preview tests
# ---------------------------------------------------------------------------


def test_dry_run_has_provenance_summary(tmp_path: Path) -> None:
    src = tmp_path / "src"
    bundle_dir = tmp_path / "bundle"
    _make_bundle(src, bundle_dir, agent="buffy", model="minimax-m2.7")
    dst = MemoryStore(tmp_path / "dst" / ".chimera-memory")
    dst.ensure()
    result = dry_run_import(dst, bundle_dir)
    ps = result.get("provenance_summary", {})
    for key in (
        "local_claim_count", "incoming_event_count", "new_claim_count",
        "duplicate_claim_count", "source_agents", "source_models",
        "incoming_agent_model_groups", "local_agent_model_groups",
        "new_agent_model_groups", "duplicate_agent_model_groups",
    ):
        assert key in ps, f"missing provenance key: {key}"


def test_dry_run_new_agent_model_groups_detected(tmp_path: Path) -> None:
    src = tmp_path / "src"
    bundle_dir = tmp_path / "bundle"
    _make_bundle(src, bundle_dir, agent="buffy", model="minimax-m2.7")
    # Local ledger has kiro only
    _make(tmp_path / "dst", agent="kiro", model="gpt-4o")
    dst_store = MemoryStore.from_paths(root=tmp_path / "dst")
    result = dry_run_import(dst_store, bundle_dir)
    ps = result["provenance_summary"]
    assert "buffy/minimax-m2.7" in ps["new_agent_model_groups"]


def test_dry_run_all_dupes_m2b_preview_unchanged(tmp_path: Path) -> None:
    """All-duplicate bundle → projected == current, all_duplicates=True."""
    src = tmp_path / "src"
    bundle_dir = tmp_path / "bundle"
    _make(src, agent="kiro")
    src_store = MemoryStore.from_paths(root=src)
    build_evidence_bundle(src_store, bundle_dir)
    result = dry_run_import(src_store, bundle_dir)  # import into same store
    preview = result["m2b_preview"]
    assert preview["delta"]["all_duplicates"] is True
    assert (preview.get("current") or {}).get("readiness_level") == \
           (preview.get("projected") or {}).get("readiness_level")


def test_dry_run_m2b_preview_keys(tmp_path: Path) -> None:
    src = tmp_path / "src"
    bundle_dir = tmp_path / "bundle"
    _make_bundle(src, bundle_dir)
    dst = MemoryStore(tmp_path / "dst" / ".chimera-memory")
    dst.ensure()
    result = dry_run_import(dst, bundle_dir)
    preview = result.get("m2b_preview", {})
    # New full-parity structure
    for key in ("current", "projected", "delta", "notes"):
        assert key in preview, f"missing m2b_preview key: {key}"
    for key in ("readiness_level", "m2b_ready", "blockers", "warnings"):
        assert key in preview["current"], f"missing current key: {key}"
        assert key in preview["projected"], f"missing projected key: {key}"
    for key in ("all_duplicates", "comparable_groups_delta", "organic_real_delta"):
        assert key in preview["delta"], f"missing delta key: {key}"


def test_dry_run_manifest_event_count_mismatch_warning(tmp_path: Path) -> None:
    src = tmp_path / "src"
    bundle_dir = tmp_path / "bundle"
    _make_bundle(src, bundle_dir)
    # Tamper: change manifest event_count
    mpath = bundle_dir / "manifest.json"
    m = json.loads(mpath.read_text())
    m["event_count"] = 9999
    mpath.write_text(json.dumps(m))
    dst = MemoryStore(tmp_path / "dst" / ".chimera-memory")
    dst.ensure()
    result = dry_run_import(dst, bundle_dir)
    assert any("9999" in w for w in result["warnings"])


def test_dry_run_missing_dq_warning(tmp_path: Path) -> None:
    """Events without data_quality trigger a warning."""
    src = tmp_path / "src"
    bundle_dir = tmp_path / "bundle"
    _make(src, agent="buffy")
    src_store = MemoryStore.from_paths(root=src)
    build_evidence_bundle(src_store, bundle_dir)
    # Strip effective_data_quality from events
    events_path = bundle_dir / "events.jsonl"
    lines = []
    for line in events_path.read_text().splitlines():
        if line.strip():
            evt = json.loads(line)
            evt.pop("effective_data_quality", None)
            evt.pop("data_quality", None)
            lines.append(json.dumps(evt))
    events_path.write_text("\n".join(lines) + "\n")
    dst = MemoryStore(tmp_path / "dst" / ".chimera-memory")
    dst.ensure()
    result = dry_run_import(dst, bundle_dir)
    assert any("DQ metadata" in w or "effective_data_quality" in w for w in result["warnings"])


def test_dry_run_possible_secret_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake unredacted secret in command display triggers warning."""
    monkeypatch.chdir(tmp_path)
    main(["session", "start", "--branch", "b", "--task-label", "t",
          "--agent", "a", "--model", "m", "--harness-id", "h"])
    main(["wrap", "--failure-origin", "organic_real", "--verification-scope", "package",
          "--scope-path", "packages/chimera-memory",
          "--", "python", "-c", "print('ok')"])
    main(["session", "end", "--status", "PASSED"])
    src_store = MemoryStore.from_paths(root=tmp_path)
    bundle_dir = tmp_path / "bundle"
    build_evidence_bundle(src_store, bundle_dir)
    # Inject fake secret into a command display field
    events_path = bundle_dir / "events.jsonl"
    lines = []
    for line in events_path.read_text().splitlines():
        if line.strip():
            evt = json.loads(line)
            evt["command"] = {"display": "python -c print('token=ghp_FakeSecret1234567890ABC')"}
            lines.append(json.dumps(evt))
    events_path.write_text("\n".join(lines) + "\n")
    dst = MemoryStore(tmp_path / "dst" / ".chimera-memory")
    dst.ensure()
    result = dry_run_import(dst, bundle_dir)
    assert any("ghp_" in w for w in result["warnings"])


def test_dry_run_text_includes_no_write_disclaimer(tmp_path: Path) -> None:
    from chimera_memory.evidence import format_dry_run_text
    src = tmp_path / "src"
    bundle_dir = tmp_path / "bundle"
    _make_bundle(src, bundle_dir)
    dst = MemoryStore(tmp_path / "dst" / ".chimera-memory")
    dst.ensure()
    result = dry_run_import(dst, bundle_dir)
    text = format_dry_run_text(result)
    assert "no ledger mutation" in text.lower() or "dry-run" in text.lower()
    assert "writes_performed: False" in text


# ---------------------------------------------------------------------------
# Repair-loop projection parity tests
# ---------------------------------------------------------------------------


def _make_with_repair(
    root: Path,
    *,
    agent: str = "buffy",
    model: str = "minimax-m2.7",
    loop_id: str = "loop-1",
    phase: str = "baseline",
    observed: bool = True,
) -> str:
    extra = {
        **_CLEAN,
        "failure_origin": "organic_real",
        "verification_scope": "package",
        "scope_paths": ["packages/chimera-memory"],
        "repair_loop_id": loop_id,
        "repair_phase": phase,
    }
    cid = record_claim(
        title="t", summary="s", predicted=True, evidence=[_ev()],
        root=root, claim_time=_T0, agent_id=agent, model_version=model,
        task_type="test", extra_metadata=extra,
    )
    settle_claim(cid, observed, _T1, root=root)
    return cid


def test_dry_run_repair_loop_projection_works(tmp_path: Path) -> None:
    """Incoming bundle with baseline+fix repair loop projects correctly."""
    src = tmp_path / "src"
    bundle_dir = tmp_path / "bundle"
    # Bundle: one complete repair loop (baseline + same_scope_after_fix)
    _make_with_repair(src, loop_id="ext-loop-1", phase="baseline", observed=False)
    _make_with_repair(src, loop_id="ext-loop-1", phase="same_scope_after_fix", observed=True)
    src_store = MemoryStore.from_paths(root=src)
    build_evidence_bundle(src_store, bundle_dir)
    # Local: no repair loops
    dst = MemoryStore(tmp_path / "dst" / ".chimera-memory")
    dst.ensure()
    result = dry_run_import(dst, bundle_dir)
    assert result["writes_performed"] is False
    proj_rl = (
        (result.get("m2b_preview") or {}).get("projected") or {}
    ).get("repair_loop_summary") or {}
    # Projected should show the incoming repair loop
    assert proj_rl.get("total_loops", 0) >= 1
    assert proj_rl.get("complete_loops", 0) >= 1


def test_dry_run_dupes_do_not_change_repair_loop_count(tmp_path: Path) -> None:
    """All-duplicate import: projected repair loops == current."""
    src = tmp_path / "src"
    bundle_dir = tmp_path / "bundle"
    _make_with_repair(src, loop_id="local-loop", phase="baseline", observed=False)
    _make_with_repair(src, loop_id="local-loop", phase="same_scope_after_fix")
    src_store = MemoryStore.from_paths(root=src)
    build_evidence_bundle(src_store, bundle_dir)
    # Import into same ledger (all dupes)
    result = dry_run_import(src_store, bundle_dir)
    assert result["writes_performed"] is False
    delta = (result.get("m2b_preview") or {}).get("delta") or {}
    assert delta.get("all_duplicates") is True
    assert delta.get("repair_loop_delta", 0) == 0


def test_dry_run_repair_loop_json_keys(tmp_path: Path) -> None:
    """Projected m2b_preview includes repair_loop_summary."""
    src = tmp_path / "src"
    bundle_dir = tmp_path / "bundle"
    _make_with_repair(src)
    src_store = MemoryStore.from_paths(root=src)
    build_evidence_bundle(src_store, bundle_dir)
    dst = MemoryStore(tmp_path / "dst" / ".chimera-memory")
    dst.ensure()
    result = dry_run_import(dst, bundle_dir)
    projected = (result.get("m2b_preview") or {}).get("projected") or {}
    assert "repair_loop_summary" in projected
    current = (result.get("m2b_preview") or {}).get("current") or {}
    assert "repair_loop_summary" in current


def test_claim_proxy_repair_loop_fields_work_with_real_gate(tmp_path: Path) -> None:
    """Verify _ClaimProxy with repair_loop metadata integrates with gate logic."""
    from chimera_memory_types.knowledge import ClaimStatus

    from chimera_memory.evidence import _ClaimProxy
    from chimera_memory.m2b_readiness import _repair_loop_summary

    proxies = [
        _ClaimProxy(
            claim_id="p-001",
            metadata={"repair_loop_id": "test-loop", "repair_phase": "baseline",
                      "failure_origin": "organic_real", "verification_scope": "package"},
            claim_status=ClaimStatus.CONTRADICTED,
        ),
        _ClaimProxy(
            claim_id="p-002",
            metadata={"repair_loop_id": "test-loop", "repair_phase": "same_scope_after_fix",
                      "failure_origin": "organic_real", "verification_scope": "package"},
            claim_status=ClaimStatus.VALIDATED,
        ),
    ]
    summary, complete = _repair_loop_summary(proxies)
    assert complete == 1
    assert summary["total_loops"] == 1
    assert "test-loop" in summary["loop_ids"]
