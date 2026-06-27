"""Tests for the read-only Memory Evidence Bridge (bridge scaffolding v0)."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from chimera_memory.bridge import (
    SCHEMA_VERSION,
    SOURCE_HARNESS_EVIDENCE,
    SOURCE_WORK_PACKET,
    BridgeError,
    detect_source_kind,
    normalize_bundle,
)
from chimera_memory.cli import main

_PY = sys.executable
_FORBIDDEN_SUB = (
    "safe to merge", "production ready", "production-ready", "certified", "approved",
    "guaranteed", "proves correctness", "proves safety", "proof-carrying", "proof",
    "optimal", "guaranteed faster",
)
_FORBIDDEN_WORDS = (
    "healthy", "unhealthy", "pass", "fail", "ready", "not ready", "success", "failure",
    "risk", "severity", "priority", "score", "unsafe", "blocked",
    "valid", "invalid", "trusted", "untrusted", "rejected",
)
_T = "2026-06-27T10:00:00+00:00"


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


def _assert_no_forbidden(text: str) -> None:
    low = text.lower()
    for phrase in _FORBIDDEN_SUB:
        assert phrase not in low, f"overclaim phrase leaked: {phrase!r}"
    for word in _FORBIDDEN_WORDS:
        assert not re.search(r"\b" + re.escape(word) + r"\b", low), f"forbidden word: {word!r}"


def _dir_fingerprint(d: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(d.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(d).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def _write_manifest(bundle_dir: Path, content_files: dict[str, str]) -> str:
    entries = []
    for name, text in content_files.items():
        data = text.encode("utf-8")
        (bundle_dir / name).write_bytes(data)
        entries.append({
            "path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
        })
    manifest = {"schema_version": "harness_evidence_bundle.v1", "files": entries}
    mbytes = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")
    (bundle_dir / "manifest.json").write_bytes(mbytes)
    return hashlib.sha256(mbytes).hexdigest()


def _run_dict(
    run_id: str, *, exit_code: int | None = 0, truncated: bool = False,
    redacted: bool = False, check_label: str | None = None, command: str = "pytest -q",
    extra: bool = False,
) -> dict[str, Any]:
    d: dict[str, Any] = {
        "run_id": run_id, "created_at": _T, "mode": "recorded", "command": command,
        "cwd": ".", "exit_code": exit_code, "status": "completed",
        "check_label": check_label, "note": "n", "tags": ["bridge"],
        "work_session_id": "sess_x", "brief_id": "brief_x",
        "redaction_applied": redacted, "output_truncated": truncated,
        "stdout_sha256": "abc123", "stderr_sha256": None, "artifact_refs": ["a.txt"],
        "source": "cli",
    }
    if extra:
        d["unknown_future_field"] = "ignore me"
    return d


def _heb(bundle_dir: Path, *, runs: list[dict[str, Any]]) -> str:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    evidence = {
        "schema_version": "harness_evidence_bundle.v1", "bundle_id": "heb_test",
        "filters": {"work_session_id": "sess_x", "brief_id": "brief_x", "limit": None},
        "source": {"package": "chimera-memory", "version": "0.32.0"},
        "harness_runs": runs,
    }
    files = {
        "HARNESS_EVIDENCE.md": "# Chimera Harness Evidence Bundle\n",
        "harness-evidence.json": json.dumps(evidence, sort_keys=True, indent=2) + "\n",
        "harness-runs.json": json.dumps({"harness_runs": runs}, sort_keys=True, indent=2) + "\n",
        "README.md": "# readme\n",
    }
    return _write_manifest(bundle_dir, files)


def _wp(
    bundle_dir: Path, *, runs: list[dict[str, Any]], observations: list[dict[str, Any]],
    heb_ref: dict[str, Any] | None,
) -> str:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    wp: dict[str, Any] = {
        "schema_version": 1, "artifact": "chimera_work_packet",
        "filters": {"session_id": "sess_x"},
        "harness_runs": runs, "consequence_observations": observations,
    }
    if heb_ref is not None:
        wp["harness_evidence_bundle"] = heb_ref
    files = {
        "WORK_PACKET.md": "# Chimera Work Packet\n",
        "work-packet.json": json.dumps(wp, sort_keys=True, indent=2) + "\n",
        "README.md": "# readme\n",
    }
    return _write_manifest(bundle_dir, files)


def _obs(observation_id: str = "co_1") -> dict[str, Any]:
    return {
        "observation_id": observation_id,
        "observation_kind": "harness_run_nonzero_exit_code_observed",
        "subject": {"type": "harness_run", "id": "run_1"},
        "suggested_checks": ["pytest -q"], "note": "n",
        "work_session_id": "sess_x", "brief_id": "brief_x",
    }


# --- source detection + happy path -------------------------------------------

def test_detect_source_kind(tmp_path: Path) -> None:
    heb = tmp_path / "ev"
    _heb(heb, runs=[_run_dict("run_1")])
    wp = tmp_path / "pk"
    _wp(wp, runs=[], observations=[], heb_ref=None)
    assert detect_source_kind(heb) == SOURCE_HARNESS_EVIDENCE
    assert detect_source_kind(wp) == SOURCE_WORK_PACKET
    assert detect_source_kind(tmp_path / "nope") == "unknown"


def test_reads_valid_harness_evidence_bundle(tmp_path: Path) -> None:
    heb = tmp_path / "ev"
    sha = _heb(heb, runs=[_run_dict("run_1"), _run_dict("run_2", exit_code=7)])
    ev = normalize_bundle(heb, created_at=_T)
    assert ev.source_kind == SOURCE_HARNESS_EVIDENCE
    assert ev.schema_version == SCHEMA_VERSION
    assert ev.source_manifest_sha256 == sha
    assert len(ev.harness_runs) == 2
    assert ev.manifest.file_count == 5  # 4 content files + manifest.json
    assert ev.manifest.hash_mismatch_count == 0
    assert ev.manifest.missing_file_count == 0
    assert ev.manifest.unexpected_store_file_count == 0
    assert ev.manifest.recognized_record_count == 2
    assert ev.work_session_id == "sess_x"
    assert ev.memory_version == "0.32.0"


def test_detects_missing_required_file_count(tmp_path: Path) -> None:
    heb = tmp_path / "ev"
    _heb(heb, runs=[_run_dict("run_1")])
    (heb / "README.md").unlink()  # listed in manifest, now missing
    ev = normalize_bundle(heb, created_at=_T)
    assert ev.manifest.missing_file_count >= 1


def test_detects_manifest_hash_mismatch_count(tmp_path: Path) -> None:
    heb = tmp_path / "ev"
    _heb(heb, runs=[_run_dict("run_1")])
    (heb / "HARNESS_EVIDENCE.md").write_text("tampered", encoding="utf-8")
    ev = normalize_bundle(heb, created_at=_T)
    assert ev.manifest.hash_mismatch_count >= 1


def test_detects_unexpected_store_file(tmp_path: Path) -> None:
    heb = tmp_path / "ev"
    _heb(heb, runs=[_run_dict("run_1")])
    (heb / "harness_runs.jsonl").write_text("{}\n", encoding="utf-8")
    ev = normalize_bundle(heb, created_at=_T)
    assert ev.manifest.unexpected_store_file_count >= 1


# --- normalization fields -----------------------------------------------------

def test_normalizes_exit_code_as_observed_data(tmp_path: Path) -> None:
    heb = tmp_path / "ev"
    _heb(heb, runs=[_run_dict("run_1", exit_code=7)])
    ev = normalize_bundle(heb, created_at=_T)
    run = ev.harness_runs[0]
    assert run["exit_code"] == 7  # observed integer, not a verdict
    # no verdict fields leaked into the normalized record
    for forbidden in ("passed", "failed", "score", "verdict", "approval", "decision"):
        assert forbidden not in run


def test_normalizes_redaction_and_truncation_fields(tmp_path: Path) -> None:
    heb = tmp_path / "ev"
    _heb(heb, runs=[_run_dict("run_1", truncated=True, redacted=True)])
    ev = normalize_bundle(heb, created_at=_T)
    run = ev.harness_runs[0]
    assert run["redaction_applied"] is True
    assert run["output_truncated"] is True


def test_unknown_run_fields_ignored_deterministically(tmp_path: Path) -> None:
    heb = tmp_path / "ev"
    _heb(heb, runs=[_run_dict("run_1", extra=True)])
    ev = normalize_bundle(heb, created_at=_T)
    run = ev.harness_runs[0]
    assert "unknown_future_field" not in run  # ignored deterministically
    assert ev.manifest.hash_mismatch_count == 0  # manifest still consistent


def test_no_recognized_artifact_raises(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(BridgeError):
        normalize_bundle(empty, created_at=_T)


# --- work packet reference ----------------------------------------------------

def test_work_packet_with_consequence_and_reference(tmp_path: Path) -> None:
    heb = tmp_path / "ev"
    heb_sha = _heb(heb, runs=[_run_dict("run_1"), _run_dict("run_2")])
    ref = {
        "path": "ev", "schema_version": "harness_evidence_bundle.v1",
        "manifest_sha256": heb_sha, "harness_run_count": 2,
    }
    wp = tmp_path / "pk"
    _wp(wp, runs=[_run_dict("run_1", exit_code=7)], observations=[_obs()], heb_ref=ref)
    ev = normalize_bundle(wp, created_at=_T)
    assert ev.source_kind == SOURCE_WORK_PACKET
    assert len(ev.consequence_observations) == 1
    assert ev.suggested_checks == ("pytest -q",)
    assert ev.work_packet_reference is not None
    assert ev.work_packet_reference.resolved is True
    assert ev.work_packet_reference.manifest_sha256 == heb_sha
    assert ev.work_packet_reference.harness_run_count == 2
    assert ev.manifest.hash_mismatch_count == 0


def test_work_packet_missing_reference_is_noted_not_raised(tmp_path: Path) -> None:
    ref = {"path": "does-not-exist", "manifest_sha256": "x", "harness_run_count": 1}
    wp = tmp_path / "pk"
    _wp(wp, runs=[], observations=[], heb_ref=ref)
    ev = normalize_bundle(wp, created_at=_T)  # must not raise
    assert ev.work_packet_reference is not None
    assert ev.work_packet_reference.resolved is False
    assert ev.manifest.missing_file_count >= 1
    assert any("referenced harness evidence bundle manifest not found" in n for n in ev.notes)


# --- read-only / no-execution -------------------------------------------------

def test_inspect_does_not_mutate_source_or_create_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    heb = tmp_path / "ev"
    _heb(heb, runs=[_run_dict("run_1")])
    before = _dir_fingerprint(heb)
    code, _ = _run(capsys, "bridge", "inspect", "--bundle-dir", str(heb), "--json")
    assert code == 0
    assert _dir_fingerprint(heb) == before
    assert not (heb / ".chimera-memory").exists()
    assert not (tmp_path / ".chimera-memory").exists()


def test_normalize_writes_only_explicit_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    heb = tmp_path / "ev"
    _heb(heb, runs=[_run_dict("run_1")])
    before = _dir_fingerprint(heb)
    out = tmp_path / "normalized.json"
    code, _ = _run(capsys, "bridge", "normalize", "--bundle-dir", str(heb),
                   "--output-json", str(out))
    assert code == 0
    assert out.exists()
    assert _dir_fingerprint(heb) == before  # source unchanged
    data = json.loads(out.read_text())
    assert data["schema_version"] == "memory_bridge_evidence.v1"
    assert len(data["harness_runs"]) == 1


def test_bridge_does_not_execute_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sentinel = tmp_path / "SENTINEL"
    heb = tmp_path / "ev"
    _heb(heb, runs=[_run_dict("run_1", command=f"touch {sentinel}")])
    out = tmp_path / "n.json"
    _run(capsys, "bridge", "inspect", "--bundle-dir", str(heb), "--json")
    _run(capsys, "bridge", "normalize", "--bundle-dir", str(heb), "--output-json", str(out))
    assert not sentinel.exists()  # the command string is data, never executed


# --- CLI text/json ------------------------------------------------------------

def test_cli_inspect_json_and_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    heb = tmp_path / "ev"
    _heb(heb, runs=[_run_dict("run_1"), _run_dict("run_2")])
    code, jout = _run(capsys, "bridge", "inspect", "--bundle-dir", str(heb), "--json")
    assert code == 0
    d = json.loads(jout)
    assert d["harness_run_count"] == 2 and d["manifest"]["hash_mismatch_count"] == 0
    code, tout = _run(capsys, "bridge", "inspect", "--bundle-dir", str(heb))
    assert code == 0 and "manifest check" in tout.lower() and "harness_run_count" in tout


def test_cli_normalize_emits_expected_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    heb = tmp_path / "ev"
    heb_sha = _heb(heb, runs=[_run_dict("run_1")])
    ref = {"path": "ev", "schema_version": "harness_evidence_bundle.v1",
           "manifest_sha256": heb_sha, "harness_run_count": 1}
    wp = tmp_path / "pk"
    _wp(wp, runs=[_run_dict("run_1")], observations=[_obs()], heb_ref=ref)
    out = tmp_path / "np.json"
    code, _ = _run(capsys, "bridge", "normalize", "--bundle-dir", str(wp),
                   "--output-json", str(out))
    assert code == 0
    d = json.loads(out.read_text())
    assert d["source_kind"] == "work_packet_bundle"
    assert len(d["consequence_observations"]) == 1
    assert d["work_packet_reference"]["resolved"] is True


# --- MCP read-only ------------------------------------------------------------

def test_mcp_bridge_tools_read_only_and_no_writer() -> None:
    from chimera_memory.mcp_server import ToolPermissions, list_tools
    ro = {t["name"] for t in list_tools(ToolPermissions(allow_write=False, allow_execute=False))}
    assert "chimera_memory_bridge_inspect" in ro
    assert "chimera_memory_bridge_normalize_preview" in ro
    rwx = {t["name"] for t in list_tools(ToolPermissions(allow_write=True, allow_execute=True))}
    # the normalize writer is never exposed (only the read-only preview is)
    assert not any("bridge_normalize" in n and "preview" not in n for n in rwx)


def test_mcp_bridge_inspect_and_preview_results(tmp_path: Path) -> None:
    from chimera_memory.mcp_server import ToolPermissions, call_tool
    heb = tmp_path / "ev"
    _heb(heb, runs=[_run_dict("run_1"), _run_dict("run_2")])
    perms = ToolPermissions(allow_write=False, allow_execute=False)
    insp = call_tool("chimera_memory_bridge_inspect", {"bundle_dir": str(heb)},
                     perms=perms, root=tmp_path)
    assert insp["harness_run_count"] == 2 and insp["manifest"]["hash_mismatch_count"] == 0
    prev = call_tool("chimera_memory_bridge_normalize_preview", {"bundle_dir": str(heb)},
                     perms=perms, root=tmp_path)
    assert prev["schema_version"] == "memory_bridge_evidence.v1"
    assert len(prev["harness_runs"]) == 2
    # preview must not have written any file into the source
    assert {p.name for p in heb.iterdir()} == {
        "HARNESS_EVIDENCE.md", "harness-evidence.json", "harness-runs.json",
        "manifest.json", "README.md",
    }


def test_mcp_bridge_tools_create_no_store(tmp_path: Path) -> None:
    from chimera_memory.mcp_server import ToolPermissions, call_tool
    heb = tmp_path / "ev"
    _heb(heb, runs=[_run_dict("run_1")])
    clean = tmp_path / "clean"
    clean.mkdir()
    perms = ToolPermissions(allow_write=False, allow_execute=False)
    call_tool("chimera_memory_bridge_inspect", {"bundle_dir": str(heb)},
              perms=perms, root=clean)
    assert not (clean / ".chimera-memory").exists()


# --- anti-overclaim -----------------------------------------------------------

def test_no_forbidden_wording_in_generated_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    heb = tmp_path / "ev"
    _heb(heb, runs=[_run_dict("run_1", exit_code=7, truncated=True, redacted=True)])
    out = tmp_path / "n.json"
    _, jout = _run(capsys, "bridge", "inspect", "--bundle-dir", str(heb), "--json")
    _assert_no_forbidden(jout)
    _, tout = _run(capsys, "bridge", "inspect", "--bundle-dir", str(heb))
    _assert_no_forbidden(tout)
    _run(capsys, "bridge", "normalize", "--bundle-dir", str(heb), "--output-json", str(out))
    _assert_no_forbidden(out.read_text())


def test_doc_has_no_forbidden_wording() -> None:
    doc = Path(__file__).resolve().parents[3] / "docs" / "memory-bridge.md"
    if doc.exists():
        _assert_no_forbidden(doc.read_text(encoding="utf-8"))
