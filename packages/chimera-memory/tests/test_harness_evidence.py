"""Tests for the portable Harness Evidence Bundle (v0.31)."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

from chimera_memory.cli import main
from chimera_memory.harness_evidence import (
    SCHEMA_VERSION,
    build_harness_evidence_bundle,
    diff_bundle_dirs,
    evidence_reference,
    inspect_harness_evidence_bundle,
    inspect_is_clean,
    write_harness_evidence_bundle,
)
from chimera_memory.harness_run import append_harness_run, build_recorded_run, read_harness_runs
from chimera_memory.storage import MemoryStore
from chimera_memory.work_brief import add_work_brief, build_work_brief
from chimera_memory.work_session import append_session_event, build_session_event, make_session_id

_PY = sys.executable
_FORBIDDEN_SUB = (
    "safe to merge", "production ready", "production-ready", "certified", "approved",
    "guaranteed", "proves correctness", "proves safety", "trusted", "proof-carrying",
    "proof", "optimal", "guaranteed faster",
)
_FORBIDDEN_WORDS = ("healthy", "unhealthy", "pass", "fail", "ready", "not ready",
                    "success", "failure")

_BUNDLE_FILES = {
    "HARNESS_EVIDENCE.md", "harness-evidence.json", "harness-runs.json",
    "manifest.json", "README.md",
}


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


def _assert_no_forbidden(text: str) -> None:
    low = text.lower()
    for phrase in _FORBIDDEN_SUB:
        assert phrase not in low, f"overclaim phrase leaked: {phrase!r}"
    for word in _FORBIDDEN_WORDS:
        assert not re.search(r"\b" + re.escape(word) + r"\b", low), f"forbidden word: {word!r}"


def _store_fingerprint(root: Path) -> str:
    """Hash of every file under .chimera-memory (to detect store mutation)."""
    mem = root / ".chimera-memory"
    h = hashlib.sha256()
    for p in sorted(mem.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(mem).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def _seed(root: Path) -> tuple[str, str]:
    """Seed a brief + open session; return (session_id, brief_id)."""
    store = MemoryStore.from_paths(root=root)
    brief = build_work_brief(title="H", objective="O", task_kind="harness-lite", tags=("v0.31",))
    add_work_brief(store, brief)
    sid = make_session_id(created_at="2026-06-26T10:00:00+00:00", brief_id=brief.brief_id)
    append_session_event(store, build_session_event(
        session_id=sid, event_kind="started", brief_id=brief.brief_id, tags=("v0.31",),
        created_at="2026-06-26T10:00:00+00:00"))
    return sid, brief.brief_id


def _seed_runs(root: Path, sid: str, brief_id: str) -> MemoryStore:
    store = MemoryStore.from_paths(root=root)
    append_harness_run(store, build_recorded_run(
        command="python -c 'print(123)'", generated_at="2026-06-26T10:01:00+00:00",
        exit_code=0, work_session_id=sid, brief_id=brief_id, check_label="rec",
        note="recorded note", tags=("v0.31",)))
    append_harness_run(store, build_recorded_run(
        command="echo token=ABCDEF", generated_at="2026-06-26T10:02:00+00:00",
        exit_code=2, work_session_id=sid, brief_id=brief_id, check_label="run2",
        stdout_preview="token=SECRETVALUE truncate" + "x" * 100, tags=("v0.31",)))
    return store


# --- module: build + write ---------------------------------------------------

def test_bundle_creates_expected_files(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = _seed_runs(tmp_path, sid, bid)
    bundle = build_harness_evidence_bundle(store, created_at="T", work_session_id=sid)
    out = tmp_path / "bundle"
    manifest = write_harness_evidence_bundle(bundle, output_dir=out)
    assert {p.name for p in out.iterdir()} == _BUNDLE_FILES
    assert {e["path"] for e in manifest["files"]} == _BUNDLE_FILES - {"manifest.json"}
    assert bundle.summary["harness_run_count"] == 2


def test_bundle_filters_by_work_session(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = _seed_runs(tmp_path, sid, bid)
    append_harness_run(store, build_recorded_run(
        command="other", generated_at="T3", exit_code=0, work_session_id="sess_other"))
    bundle = build_harness_evidence_bundle(store, created_at="T", work_session_id=sid)
    assert bundle.summary["harness_run_count"] == 2
    assert all(r["work_session_id"] == sid for r in bundle.harness_runs)


def test_bundle_filters_by_brief(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = _seed_runs(tmp_path, sid, bid)
    bundle = build_harness_evidence_bundle(store, created_at="T", brief_id=bid)
    assert bundle.summary["harness_run_count"] == 2
    empty = build_harness_evidence_bundle(store, created_at="T", brief_id="brief_none")
    assert empty.summary["harness_run_count"] == 0


def test_bundle_filters_by_tag(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = _seed_runs(tmp_path, sid, bid)
    append_harness_run(store, build_recorded_run(
        command="untagged", generated_at="T9", exit_code=0, work_session_id=sid))
    bundle = build_harness_evidence_bundle(store, created_at="T", tag="v0.31")
    assert bundle.summary["harness_run_count"] == 2


def test_bundle_limit_is_deterministic_most_recent(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = _seed_runs(tmp_path, sid, bid)
    bundle = build_harness_evidence_bundle(store, created_at="T", work_session_id=sid, limit=1)
    assert bundle.summary["harness_run_count"] == 1
    # most-recent kept (the second seeded run)
    assert bundle.harness_runs[0]["check_label"] == "run2"
    again = build_harness_evidence_bundle(store, created_at="T", work_session_id=sid, limit=1)
    assert again.bundle_id == bundle.bundle_id  # deterministic


def test_bundle_omits_previews_by_default(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = _seed_runs(tmp_path, sid, bid)
    bundle = build_harness_evidence_bundle(store, created_at="T", work_session_id=sid)
    for r in bundle.harness_runs:
        assert "stdout_preview" not in r
        assert "stderr_preview" not in r
    assert bundle.redaction_summary.previews_included is False


def test_bundle_includes_previews_only_when_requested(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = _seed_runs(tmp_path, sid, bid)
    bundle = build_harness_evidence_bundle(
        store, created_at="T", work_session_id=sid, include_previews=True)
    assert all("stdout_preview" in r for r in bundle.harness_runs)
    assert bundle.redaction_summary.previews_included is True


def test_bundle_never_includes_full_output(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = _seed_runs(tmp_path, sid, bid)
    bundle = build_harness_evidence_bundle(
        store, created_at="T", work_session_id=sid, include_previews=True)
    out = tmp_path / "bundle"
    write_harness_evidence_bundle(bundle, output_dir=out)
    blob = (out / "harness-evidence.json").read_text()
    # the raw secret value is redacted out of any included preview
    assert "SECRETVALUE" not in blob
    # full output is referenced by hash; previews are bounded
    runs = json.loads((out / "harness-runs.json").read_text())["harness_runs"]
    for r in runs:
        assert "stdout_sha256" in r


def test_redaction_and_truncation_summary(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = _seed_runs(tmp_path, sid, bid)
    bundle = build_harness_evidence_bundle(store, created_at="T", work_session_id=sid)
    # the second seeded run has a secret-like preview -> redaction applied
    assert bundle.summary["redacted_preview_count"] >= 1
    assert bundle.summary["executed_run_count"] == 0
    assert bundle.summary["recorded_run_count"] == 2


def test_manifest_hashes_every_file(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = _seed_runs(tmp_path, sid, bid)
    bundle = build_harness_evidence_bundle(store, created_at="T", work_session_id=sid)
    out = tmp_path / "bundle"
    manifest = write_harness_evidence_bundle(bundle, output_dir=out)
    for entry in manifest["files"]:
        data = (out / entry["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        assert len(data) == entry["bytes"]


def test_bundle_has_no_store_files_inside(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = _seed_runs(tmp_path, sid, bid)
    bundle = build_harness_evidence_bundle(store, created_at="T", work_session_id=sid)
    out = tmp_path / "bundle"
    write_harness_evidence_bundle(bundle, output_dir=out)
    names = {p.name for p in out.rglob("*")}
    assert "harness_runs.jsonl" not in names
    assert not any(p.suffix == ".jsonl" for p in out.rglob("*"))
    assert not (out / ".chimera-memory").exists()


def test_bundle_does_not_mutate_store(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = _seed_runs(tmp_path, sid, bid)
    before = _store_fingerprint(tmp_path)
    bundle = build_harness_evidence_bundle(store, created_at="T", work_session_id=sid)
    write_harness_evidence_bundle(bundle, output_dir=tmp_path / "bundle")
    assert _store_fingerprint(tmp_path) == before
    assert len(read_harness_runs(store)) == 2


def test_bundle_does_not_execute_command(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    sentinel = tmp_path / "SHOULD_NOT_EXIST"
    append_harness_run(store, build_recorded_run(
        command=f"touch {sentinel}", generated_at="T", exit_code=0, work_session_id=sid))
    bundle = build_harness_evidence_bundle(store, created_at="T", work_session_id=sid)
    write_harness_evidence_bundle(bundle, output_dir=tmp_path / "bundle")
    assert not sentinel.exists()  # the command string is data, never executed


def test_write_refuses_nonempty_without_force(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = _seed_runs(tmp_path, sid, bid)
    bundle = build_harness_evidence_bundle(store, created_at="T", work_session_id=sid)
    out = tmp_path / "bundle"
    write_harness_evidence_bundle(bundle, output_dir=out)
    from chimera_memory.harness_evidence import HarnessEvidenceError
    with pytest.raises(HarnessEvidenceError):
        write_harness_evidence_bundle(bundle, output_dir=out)
    write_harness_evidence_bundle(bundle, output_dir=out, force=True)  # ok with force


# --- inspect ------------------------------------------------------------------

def test_inspect_clean_bundle(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = _seed_runs(tmp_path, sid, bid)
    bundle = build_harness_evidence_bundle(store, created_at="T", work_session_id=sid)
    out = tmp_path / "bundle"
    write_harness_evidence_bundle(bundle, output_dir=out)
    result = inspect_harness_evidence_bundle(out)
    assert result["hash_mismatch_count"] == 0
    assert result["missing_file_count"] == 0
    assert result["unexpected_store_file_count"] == 0
    assert result["harness_run_count"] == 2
    assert result["file_count"] == 5
    assert result["schema_version_recognized"] is True
    assert inspect_is_clean(result) is True


def test_inspect_detects_missing_file(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = _seed_runs(tmp_path, sid, bid)
    bundle = build_harness_evidence_bundle(store, created_at="T", work_session_id=sid)
    out = tmp_path / "bundle"
    write_harness_evidence_bundle(bundle, output_dir=out)
    (out / "harness-runs.json").unlink()
    result = inspect_harness_evidence_bundle(out)
    assert result["missing_file_count"] == 1
    assert inspect_is_clean(result) is False


def test_inspect_detects_hash_mismatch(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = _seed_runs(tmp_path, sid, bid)
    bundle = build_harness_evidence_bundle(store, created_at="T", work_session_id=sid)
    out = tmp_path / "bundle"
    write_harness_evidence_bundle(bundle, output_dir=out)
    (out / "HARNESS_EVIDENCE.md").write_text("tampered", encoding="utf-8")
    result = inspect_harness_evidence_bundle(out)
    assert result["hash_mismatch_count"] == 1
    assert inspect_is_clean(result) is False


def test_inspect_detects_unexpected_store_file(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = _seed_runs(tmp_path, sid, bid)
    bundle = build_harness_evidence_bundle(store, created_at="T", work_session_id=sid)
    out = tmp_path / "bundle"
    write_harness_evidence_bundle(bundle, output_dir=out)
    (out / "harness_runs.jsonl").write_text("{}\n", encoding="utf-8")
    result = inspect_harness_evidence_bundle(out)
    assert result["unexpected_store_file_count"] == 1
    assert inspect_is_clean(result) is False


def test_inspect_missing_manifest(tmp_path: Path) -> None:
    out = tmp_path / "empty"
    out.mkdir()
    result = inspect_harness_evidence_bundle(out)
    assert result["manifest_present"] is False
    assert result["missing_file_count"] == 1
    assert inspect_is_clean(result) is False


# --- diff ---------------------------------------------------------------------

def test_diff_detects_added_and_removed(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = _seed_runs(tmp_path, sid, bid)
    a = build_harness_evidence_bundle(store, created_at="T", work_session_id=sid)
    write_harness_evidence_bundle(a, output_dir=tmp_path / "a")
    append_harness_run(store, build_recorded_run(
        command="later", generated_at="T5", exit_code=0, work_session_id=sid, tags=("v0.31",)))
    b = build_harness_evidence_bundle(store, created_at="T", work_session_id=sid)
    write_harness_evidence_bundle(b, output_dir=tmp_path / "b")
    diff = diff_bundle_dirs(tmp_path / "a", tmp_path / "b")
    assert len(diff["harness_runs"]["added"]) == 1
    assert diff["harness_runs"]["removed"] == []
    assert diff["harness_runs"]["content_changed"] == []
    assert diff["summary_delta"]["harness_run_count"] == 1


def test_diff_detects_content_changed(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = _seed_runs(tmp_path, sid, bid)
    a = build_harness_evidence_bundle(store, created_at="T", work_session_id=sid)
    write_harness_evidence_bundle(a, output_dir=tmp_path / "a")
    # Build b from a, then tamper one run's content (same run_id, different content).
    b = build_harness_evidence_bundle(store, created_at="T", work_session_id=sid)
    write_harness_evidence_bundle(b, output_dir=tmp_path / "b")
    ev = json.loads((tmp_path / "b" / "harness-evidence.json").read_text())
    ev["harness_runs"][0]["note"] = "mutated content"
    (tmp_path / "b" / "harness-evidence.json").write_text(json.dumps(ev), encoding="utf-8")
    diff = diff_bundle_dirs(tmp_path / "a", tmp_path / "b")
    assert len(diff["harness_runs"]["content_changed"]) == 1
    assert diff["harness_runs"]["added"] == []


# --- CLI surfaces -------------------------------------------------------------

def test_cli_bundle_inspect_diff(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sid, bid = _seed(tmp_path)
    _seed_runs(tmp_path, sid, bid)
    mem = str(tmp_path / ".chimera-memory")
    a = tmp_path / "a"
    b = tmp_path / "b"
    code, out = _run(capsys, "harness", "bundle", "--work-session", sid,
                     "--output-dir", str(a), "--memory-dir", mem)
    assert code == 0
    code, out = _run(capsys, "harness", "bundle-inspect", str(a), "--json")
    assert code == 0
    result = json.loads(out)
    assert result["hash_mismatch_count"] == 0 and result["harness_run_count"] == 2
    # text view
    code, txt = _run(capsys, "harness", "bundle-inspect", str(a))
    assert code == 0 and "hash_mismatch_count" in txt
    # add a run, second bundle, diff
    store = MemoryStore.from_paths(root=tmp_path)
    append_harness_run(store, build_recorded_run(
        command="later", generated_at="T5", exit_code=0, work_session_id=sid, tags=("v0.31",)))
    _run(capsys, "harness", "bundle", "--work-session", sid, "--output-dir", str(b),
         "--memory-dir", mem)
    code, out = _run(capsys, "harness", "bundle-diff", str(a), str(b), "--json")
    assert code == 0
    assert len(json.loads(out)["harness_runs"]["added"]) == 1


def test_cli_work_session_harness_bundle_no_mutation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sid, bid = _seed(tmp_path)
    _seed_runs(tmp_path, sid, bid)
    mem = str(tmp_path / ".chimera-memory")
    before = _store_fingerprint(tmp_path)
    code, out = _run(capsys, "work-session", "harness-bundle", sid,
                     "--output-dir", str(tmp_path / "wsb"), "--memory-dir", mem)
    assert code == 0
    assert (tmp_path / "wsb" / "manifest.json").exists()
    assert _store_fingerprint(tmp_path) == before  # session not closed, no events written


def test_cli_work_packet_references_evidence_bundle(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sid, bid = _seed(tmp_path)
    _seed_runs(tmp_path, sid, bid)
    mem = str(tmp_path / ".chimera-memory")
    ev = tmp_path / "ev"
    _run(capsys, "harness", "bundle", "--work-session", sid, "--output-dir", str(ev),
         "--memory-dir", mem)
    pkt = tmp_path / "pkt"
    code, out = _run(capsys, "work-packet", "bundle", "--session", sid,
                     "--output-dir", str(pkt), "--harness-evidence-dir", str(ev),
                     "--memory-dir", mem)
    assert code == 0
    packet = json.loads((pkt / "work-packet.json").read_text())
    ref = packet["harness_evidence_bundle"]
    assert ref["schema_version"] == SCHEMA_VERSION
    assert ref["harness_run_count"] == 2
    assert len(ref["manifest_sha256"]) == 64
    # the reference matches what evidence_reference computes
    assert ref["manifest_sha256"] == evidence_reference(ev)["manifest_sha256"]


def test_cli_work_packet_bundle_without_evidence_has_no_ref(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sid, bid = _seed(tmp_path)
    _seed_runs(tmp_path, sid, bid)
    mem = str(tmp_path / ".chimera-memory")
    pkt = tmp_path / "pkt"
    _run(capsys, "work-packet", "bundle", "--session", sid, "--output-dir", str(pkt),
         "--memory-dir", mem)
    packet = json.loads((pkt / "work-packet.json").read_text())
    assert "harness_evidence_bundle" not in packet


# --- MCP read-only ------------------------------------------------------------

def test_mcp_bundle_tools_read_only_and_present() -> None:
    from chimera_memory.mcp_server import ToolPermissions, list_tools
    ro = {t["name"] for t in list_tools(ToolPermissions(allow_write=False, allow_execute=False))}
    assert "chimera_harness_bundle_inspect" in ro
    assert "chimera_harness_bundle_diff" in ro
    # bundle creation is never exposed as an MCP tool
    assert "chimera_harness_bundle" not in ro
    rw = {t["name"] for t in list_tools(ToolPermissions(allow_write=True, allow_execute=True))}
    assert "chimera_harness_bundle" not in rw


def test_mcp_bundle_inspect_diff_results(tmp_path: Path) -> None:
    from chimera_memory.mcp_server import ToolPermissions, call_tool
    sid, bid = _seed(tmp_path)
    store = _seed_runs(tmp_path, sid, bid)
    a = build_harness_evidence_bundle(store, created_at="T", work_session_id=sid)
    write_harness_evidence_bundle(a, output_dir=tmp_path / "a")
    append_harness_run(store, build_recorded_run(
        command="later", generated_at="T5", exit_code=0, work_session_id=sid, tags=("v0.31",)))
    b = build_harness_evidence_bundle(store, created_at="T", work_session_id=sid)
    write_harness_evidence_bundle(b, output_dir=tmp_path / "b")

    perms = ToolPermissions(allow_write=False, allow_execute=False)
    insp = call_tool("chimera_harness_bundle_inspect", {"bundle_dir": str(tmp_path / "a")},
                     perms=perms, root=tmp_path)
    assert insp["hash_mismatch_count"] == 0 and insp["harness_run_count"] == 2
    diff = call_tool(
        "chimera_harness_bundle_diff",
        {"left_bundle_dir": str(tmp_path / "a"), "right_bundle_dir": str(tmp_path / "b")},
        perms=perms, root=tmp_path)
    assert len(diff["harness_runs"]["added"]) == 1


def test_mcp_bundle_tools_create_no_store(tmp_path: Path) -> None:
    """Inspecting/diffing bundles in a dir with no store must not create .chimera-memory."""
    from chimera_memory.mcp_server import ToolPermissions, call_tool
    # build bundles under a separate root, then inspect from a clean cwd root
    src = tmp_path / "src"
    src.mkdir()
    sid, bid = _seed(src)
    store = _seed_runs(src, sid, bid)
    a = build_harness_evidence_bundle(store, created_at="T", work_session_id=sid)
    write_harness_evidence_bundle(a, output_dir=tmp_path / "a")
    clean_root = tmp_path / "clean"
    clean_root.mkdir()
    perms = ToolPermissions(allow_write=False, allow_execute=False)
    call_tool("chimera_harness_bundle_inspect", {"bundle_dir": str(tmp_path / "a")},
              perms=perms, root=clean_root)
    assert not (clean_root / ".chimera-memory").exists()


# --- anti-overclaim -----------------------------------------------------------

def test_no_forbidden_wording_in_generated_bundle(tmp_path: Path) -> None:
    sid, bid = _seed(tmp_path)
    store = _seed_runs(tmp_path, sid, bid)
    bundle = build_harness_evidence_bundle(
        store, created_at="T", work_session_id=sid, include_previews=True)
    out = tmp_path / "bundle"
    write_harness_evidence_bundle(bundle, output_dir=out)
    for p in out.iterdir():
        _assert_no_forbidden(p.read_text(encoding="utf-8"))


def test_no_forbidden_wording_in_inspect_and_diff_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sid, bid = _seed(tmp_path)
    _seed_runs(tmp_path, sid, bid)
    mem = str(tmp_path / ".chimera-memory")
    a = tmp_path / "a"
    b = tmp_path / "b"
    _run(capsys, "harness", "bundle", "--work-session", sid, "--output-dir", str(a),
         "--memory-dir", mem)
    store = MemoryStore.from_paths(root=tmp_path)
    append_harness_run(store, build_recorded_run(
        command="later", generated_at="T5", exit_code=0, work_session_id=sid, tags=("v0.31",)))
    _run(capsys, "harness", "bundle", "--work-session", sid, "--output-dir", str(b),
         "--memory-dir", mem)
    _, insp = _run(capsys, "harness", "bundle-inspect", str(a))
    _assert_no_forbidden(insp)
    _, dtxt = _run(capsys, "harness", "bundle-diff", str(a), str(b))
    _assert_no_forbidden(dtxt)


def test_doc_has_no_forbidden_wording() -> None:
    doc = Path(__file__).resolve().parents[3] / "docs" / "harness-evidence-bundle.md"
    if doc.exists():
        _assert_no_forbidden(doc.read_text(encoding="utf-8"))
