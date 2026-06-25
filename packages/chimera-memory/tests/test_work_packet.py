"""Tests for the Work Packet v0 artifact (read-only, local, advisory)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from chimera_memory.cli import main
from chimera_memory.storage import MemoryStore
from chimera_memory.tool_activity import add_tool_activity, build_tool_activity
from chimera_memory.tool_notes import add_tool_note, build_tool_note
from chimera_memory.work_packet import (
    BundleError,
    build_work_packet,
    diff_packets,
    inspect_bundle,
    load_packet_dict,
    render_diff_markdown,
    render_work_packet_markdown,
    write_work_packet_bundle,
)

_FORBIDDEN = (
    "safe to merge", "production ready", "production-ready", "certified",
    "approved", "guaranteed", "proves correctness", "proves safety",
    "trusted", "proof-carrying", "proof", "optimal", "guaranteed faster",
)

_TOP_KEYS = {
    "schema_version", "artifact", "advisory", "generated_at", "filters", "summary",
    "claims", "open_or_unresolved", "next_inspection_targets", "tool_notes",
    "candidate_tool_lessons",
}
_SUMMARY_KEYS = {
    "event_count", "settled_claim_count", "shown_claim_count", "open_or_unresolved_count",
    "next_inspection_target_count", "tool_note_count", "candidate_count",
}
_FILTER_KEYS = {
    "claim_id", "session_id", "status", "task_kind", "tag",
    "limit_tool_notes", "limit_candidates",
}


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")


def _seed_claims(root: Path) -> None:
    """Seed one validated claim (c1) and one unsettled claim (c2), session s1."""
    mem = root / ".chimera-memory"
    _write_jsonl(mem / "claims.jsonl", [
        {"claim_id": "c1", "claim_status": "proposed", "title": "c1",
         "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
         "metadata": {"session_id": "s1"}},
        {"claim_id": "c1", "claim_status": "validated", "title": "c1",
         "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:05Z",
         "metadata": {"session_id": "s1"}},
        {"claim_id": "c2", "claim_status": "proposed", "title": "c2",
         "created_at": "2026-01-01T00:00:01Z", "updated_at": "2026-01-01T00:00:01Z",
         "metadata": {"session_id": "s1"}},
    ])
    _write_jsonl(mem / "outcomes.jsonl", [
        {"claim_id": "c1", "event_key": "c1:k", "observed_at": "2026-01-01T00:00:05Z",
         "outcome": {"observed": True}, "metadata": {"exit_code": 0}},
    ])
    _write_jsonl(mem / "scores.jsonl", [
        {"record_id": "r1", "claim_id": "c1", "created_at": "2026-01-01T00:00:06Z",
         "settlement": {"status": "validated"}},
    ])


def _seed_notes_and_activity(root: Path) -> None:
    store = MemoryStore.from_paths(root=root)
    add_tool_note(store, build_tool_note(
        task_kind="large-repo-forensics", tool_name="parallel-agents",
        workflow_name="unit-card-specialist-fanout", lesson="Use coverage manifests first.",
        evidence="2189/2189 files.", caveat="High cost.", tags=("repo-forensics",)))
    add_tool_note(store, build_tool_note(
        task_kind="quick-fix", tool_name="single-agent", workflow_name="direct-edit",
        lesson="Small edits need no fanout.", tags=("small",)))
    add_tool_activity(store, build_tool_activity(
        task_kind="large-repo-forensics", tool_name="parallel-agents",
        workflow_name="unit-card-specialist-fanout",
        summary="7 agents synthesized 31 Unit Cards after 100% file coverage.",
        evidence="2189/2189 files.", caveat="High cost.", tags=("repo-forensics",)))
    add_tool_activity(store, build_tool_activity(
        task_kind="quick-fix", tool_name="single-agent", workflow_name="direct-edit",
        summary="One-line fix.", tags=("small",)))


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


# --- shape ------------------------------------------------------------------

def test_work_packet_json_schema(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_claims(tmp_path)
    _seed_notes_and_activity(tmp_path)
    mem = tmp_path / ".chimera-memory"
    code, out = _run(capsys, "work-packet", "--json", "--memory-dir", str(mem))
    assert code == 0
    d = json.loads(out)
    assert set(d) == _TOP_KEYS
    assert d["schema_version"] == 1
    assert d["artifact"] == "chimera_work_packet"
    assert "local evidence and operational memory summary only" in d["advisory"]
    assert set(d["summary"]) == _SUMMARY_KEYS
    assert set(d["filters"]) == _FILTER_KEYS
    assert isinstance(d["claims"], list)
    assert isinstance(d["candidate_tool_lessons"], list)


def test_work_packet_markdown_shape(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_claims(tmp_path)
    mem = tmp_path / ".chimera-memory"
    code, out = _run(capsys, "work-packet", "--memory-dir", str(mem))  # markdown default
    assert code == 0
    for header in ("# Chimera Work Packet", "## Store", "## Claims",
                   "## Open / unresolved evidence", "## Next inspection targets",
                   "## Tool lessons", "## Candidate tool lessons", "## Preflight advisory"):
        assert header in out, header
    assert "Advisory only." in out


def test_work_packet_empty_store_does_not_create(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"  # never created
    code, out = _run(capsys, "work-packet", "--json", "--memory-dir", str(mem))
    assert code == 0
    d = json.loads(out)
    assert d["summary"] == {k: 0 for k in _SUMMARY_KEYS}
    assert not mem.exists()


# --- filters ----------------------------------------------------------------

def test_work_packet_claim_session_status_filters_apply_to_claims(tmp_path: Path) -> None:
    _seed_claims(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)

    both = build_work_packet(store, generated_at="T", session_id="s1")
    assert {c.claim_id for c in both.claims} == {"c1", "c2"}

    validated = build_work_packet(store, generated_at="T", status="validated")
    assert {c.claim_id for c in validated.claims} == {"c1"}
    assert validated.summary.shown_claim_count == 1

    only_c2 = build_work_packet(store, generated_at="T", claim_id="c2")
    assert {c.claim_id for c in only_c2.claims} == {"c2"}


def test_work_packet_task_kind_tag_filters_tool_notes_and_candidates(tmp_path: Path) -> None:
    _seed_notes_and_activity(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)

    unfiltered = build_work_packet(store, generated_at="T")
    assert unfiltered.summary.tool_note_count == 2
    assert unfiltered.summary.candidate_count == 2

    by_task = build_work_packet(store, generated_at="T", task_kind="large-repo-forensics")
    assert by_task.summary.tool_note_count == 1
    assert by_task.summary.candidate_count == 1

    by_tag = build_work_packet(store, generated_at="T", tag="small")
    assert by_tag.summary.tool_note_count == 1
    assert by_tag.summary.candidate_count == 1

    # AND: task_kind from one note with tag from the other -> no match
    anded = build_work_packet(store, generated_at="T", task_kind="large-repo-forensics",
                              tag="small")
    assert anded.summary.tool_note_count == 0
    assert anded.summary.candidate_count == 0


def test_work_packet_limits_apply_after_filters(tmp_path: Path) -> None:
    _seed_notes_and_activity(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    p = build_work_packet(store, generated_at="T", limit_tool_notes=1, limit_candidates=1)
    assert p.summary.tool_note_count == 1
    assert p.summary.candidate_count == 1
    p0 = build_work_packet(store, generated_at="T", limit_tool_notes=0, limit_candidates=0)
    assert p0.summary.tool_note_count == 0
    assert p0.summary.candidate_count == 0


def test_work_packet_open_and_targets_carried_from_handoff(tmp_path: Path) -> None:
    _seed_claims(tmp_path)
    p = build_work_packet(MemoryStore.from_paths(root=tmp_path), generated_at="T")
    assert {o.claim_id for o in p.open_or_unresolved} == {"c2"}
    assert p.next_inspection_targets[0].claim_id == "c2"
    assert p.summary.open_or_unresolved_count == 1
    assert p.summary.next_inspection_target_count >= 1


def test_work_packet_tool_notes_and_candidates_included_when_matching(tmp_path: Path) -> None:
    _seed_notes_and_activity(tmp_path)
    p = build_work_packet(MemoryStore.from_paths(root=tmp_path), generated_at="T",
                          task_kind="large-repo-forensics")
    assert len(p.tool_notes) == 1
    assert len(p.candidate_tool_lessons) == 1
    assert p.candidate_tool_lessons[0].lesson == (
        "7 agents synthesized 31 Unit Cards after 100% file coverage.")
    md = render_work_packet_markdown(p, store_label="x")
    assert "Use coverage manifests first." in md
    assert "Candidate lesson: 7 agents synthesized 31 Unit Cards" in md


# --- read-only / output -----------------------------------------------------

def test_work_packet_is_read_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_claims(tmp_path)
    _seed_notes_and_activity(tmp_path)
    mem = tmp_path / ".chimera-memory"
    before = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    _run(capsys, "work-packet", "--memory-dir", str(mem))
    _run(capsys, "work-packet", "--json", "--task-kind", "large-repo-forensics",
         "--memory-dir", str(mem))
    after = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    assert before == after


def test_work_packet_output_writes_only_requested_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_notes_and_activity(tmp_path)
    mem = tmp_path / ".chimera-memory"
    out_file = tmp_path / "packet.md"
    before = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    code, out = _run(capsys, "work-packet", "--output", str(out_file), "--memory-dir", str(mem))
    assert code == 0
    assert out_file.exists()
    assert "# Chimera Work Packet" in out_file.read_text(encoding="utf-8")
    assert f"written to {out_file}" in out
    after = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    assert before == after  # memory store untouched by file output

    json_file = tmp_path / "packet.json"
    _run(capsys, "work-packet", "--json", "--output", str(json_file), "--memory-dir", str(mem))
    assert json.loads(json_file.read_text(encoding="utf-8"))["artifact"] == "chimera_work_packet"


def test_work_packet_output_missing_parent_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"
    mem.mkdir()
    code, _ = _run(capsys, "work-packet", "--output", str(tmp_path / "nope" / "p.md"),
                   "--memory-dir", str(mem))
    assert code == 2


def test_work_packet_no_forbidden_phrases(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_claims(tmp_path)
    _seed_notes_and_activity(tmp_path)
    mem = tmp_path / ".chimera-memory"
    blob = ""
    _, out = _run(capsys, "work-packet", "--memory-dir", str(mem))
    blob += out
    _, out = _run(capsys, "work-packet", "--json", "--memory-dir", str(mem))
    blob += out
    _, out = _run(capsys, "work-packet", "--help")
    blob += out
    blob += (Path(__file__).resolve().parents[3] / "docs" / "work-packet.md").read_text(
        encoding="utf-8")
    low = blob.lower()
    for phrase in _FORBIDDEN:
        assert phrase not in low, f"overclaim phrase leaked: {phrase!r}"


# ── v1: bundle / inspect / diff ──────────────────────────────────────────────

_MANIFEST_KEYS = {
    "schema_version", "artifact", "generated_at", "advisory", "filters",
    "packet_summary", "files",
}


def _packet(root: Path, *, generated_at: str = "T", **filters: Any) -> Any:
    return build_work_packet(MemoryStore.from_paths(root=root), generated_at=generated_at,
                             **filters)


def test_bundle_export_creates_four_files_and_manifest(tmp_path: Path) -> None:
    _seed_notes_and_activity(tmp_path)
    out = tmp_path / "packet-a"
    manifest = write_work_packet_bundle(_packet(tmp_path), output_dir=out, store_label="ws")
    assert sorted(p.name for p in out.iterdir()) == [
        "README.md", "WORK_PACKET.md", "manifest.json", "work-packet.json",
    ]
    assert set(manifest) == _MANIFEST_KEYS
    assert manifest["artifact"] == "chimera_work_packet_bundle"
    assert [f["path"] for f in manifest["files"]] == [
        "WORK_PACKET.md", "work-packet.json", "README.md",
    ]
    assert json.loads((out / "work-packet.json").read_text())["artifact"] == "chimera_work_packet"


def test_bundle_manifest_hashes_verify(tmp_path: Path) -> None:
    _seed_notes_and_activity(tmp_path)
    out = tmp_path / "packet-a"
    manifest = write_work_packet_bundle(_packet(tmp_path), output_dir=out, store_label="ws")
    import hashlib
    for entry in manifest["files"]:
        data = (out / entry["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        assert len(data) == entry["bytes"]


def test_bundle_does_not_mutate_store(tmp_path: Path) -> None:
    _seed_notes_and_activity(tmp_path)
    mem = tmp_path / ".chimera-memory"
    before = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    write_work_packet_bundle(_packet(tmp_path), output_dir=tmp_path / "b", store_label="ws")
    after = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    assert before == after


def test_bundle_missing_parent_fails_cleanly(tmp_path: Path) -> None:
    with pytest.raises(BundleError):
        write_work_packet_bundle(_packet(tmp_path), output_dir=tmp_path / "nope" / "b",
                                 store_label="ws")


def test_bundle_refuses_non_empty_without_force(tmp_path: Path) -> None:
    _seed_notes_and_activity(tmp_path)
    out = tmp_path / "packet-a"
    write_work_packet_bundle(_packet(tmp_path), output_dir=out, store_label="ws")
    with pytest.raises(BundleError):
        write_work_packet_bundle(_packet(tmp_path), output_dir=out, store_label="ws")
    empty = tmp_path / "empty"
    empty.mkdir()
    write_work_packet_bundle(_packet(tmp_path), output_dir=empty, store_label="ws")
    assert (empty / "manifest.json").exists()


def test_bundle_force_overwrites_bundle_files(tmp_path: Path) -> None:
    _seed_notes_and_activity(tmp_path)
    out = tmp_path / "packet-a"
    write_work_packet_bundle(_packet(tmp_path), output_dir=out, store_label="ws")
    sentinel = out / "unrelated.txt"
    sentinel.write_text("keep me", encoding="utf-8")
    write_work_packet_bundle(_packet(tmp_path), output_dir=out, store_label="ws", force=True)
    assert inspect_bundle(out)["valid"] is True
    assert sentinel.read_text(encoding="utf-8") == "keep me"


def test_bundle_cli_and_force(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_notes_and_activity(tmp_path)
    mem = tmp_path / ".chimera-memory"
    out = tmp_path / "packet-a"
    code, _ = _run(capsys, "work-packet", "bundle", "--output-dir", str(out),
                   "--memory-dir", str(mem))
    assert code == 0
    assert (out / "manifest.json").exists()
    code, _ = _run(capsys, "work-packet", "bundle", "--output-dir", str(out),
                   "--memory-dir", str(mem))
    assert code == 2
    code, _ = _run(capsys, "work-packet", "bundle", "--output-dir", str(out), "--force",
                   "--memory-dir", str(mem))
    assert code == 0


# --- inspect ----------------------------------------------------------------

def test_inspect_valid_bundle(tmp_path: Path) -> None:
    _seed_notes_and_activity(tmp_path)
    out = tmp_path / "packet-a"
    write_work_packet_bundle(_packet(tmp_path), output_dir=out, store_label="ws")
    result = inspect_bundle(out)
    assert result["artifact"] == "chimera_work_packet_bundle_inspection"
    assert result["valid"] is True
    assert result["errors"] == []
    assert all(f["exists"] and f["sha256_matches"] and f["bytes_matches"] for f in result["files"])


def test_inspect_missing_file_invalid(tmp_path: Path) -> None:
    _seed_notes_and_activity(tmp_path)
    out = tmp_path / "packet-a"
    write_work_packet_bundle(_packet(tmp_path), output_dir=out, store_label="ws")
    (out / "WORK_PACKET.md").unlink()
    result = inspect_bundle(out)
    assert result["valid"] is False
    assert any("missing file" in e for e in result["errors"])


def test_inspect_hash_mismatch_invalid(tmp_path: Path) -> None:
    _seed_notes_and_activity(tmp_path)
    out = tmp_path / "packet-a"
    write_work_packet_bundle(_packet(tmp_path), output_dir=out, store_label="ws")
    (out / "work-packet.json").write_text("tampered", encoding="utf-8")
    result = inspect_bundle(out)
    assert result["valid"] is False
    assert any("sha256 mismatch" in e or "bytes mismatch" in e for e in result["errors"])


def test_inspect_missing_manifest_invalid(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    result = inspect_bundle(empty)
    assert result["valid"] is False
    assert result["bundle"]["manifest"] is None


def test_inspect_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_notes_and_activity(tmp_path)
    out = tmp_path / "packet-a"
    write_work_packet_bundle(_packet(tmp_path), output_dir=out, store_label="ws")
    code, _ = _run(capsys, "work-packet", "inspect", str(out))
    assert code == 0
    (out / "README.md").unlink()
    code, jout = _run(capsys, "work-packet", "inspect", str(out), "--json")
    assert code == 1
    assert json.loads(jout)["valid"] is False


# --- diff -------------------------------------------------------------------

def test_diff_two_bundle_dirs_and_two_json_files(tmp_path: Path) -> None:
    _seed_notes_and_activity(tmp_path)
    a = tmp_path / "a"
    write_work_packet_bundle(_packet(tmp_path), output_dir=a, store_label="ws")
    store = MemoryStore.from_paths(root=tmp_path)
    add_tool_note(store, build_tool_note(task_kind="extra", tool_name="t", lesson="L3"))
    add_tool_activity(store, build_tool_activity(task_kind="extra", tool_name="t",
                                                 workflow_name="w", summary="S3"))
    b = tmp_path / "b"
    write_work_packet_bundle(_packet(tmp_path), output_dir=b, store_label="ws")

    by_dir = diff_packets(load_packet_dict(a), load_packet_dict(b),
                          old_path=str(a), new_path=str(b))
    by_file = diff_packets(load_packet_dict(a / "work-packet.json"),
                           load_packet_dict(b / "work-packet.json"),
                           old_path="a.json", new_path="b.json")
    assert by_dir["artifact"] == "chimera_work_packet_diff"
    assert by_dir["summary_delta"]["tool_note_count"] == 1
    assert by_dir["summary_delta"]["candidate_count"] == 1
    assert by_dir["claims"] == by_file["claims"]
    assert len(by_dir["tool_notes"]["added"]) == 1
    assert len(by_dir["candidate_tool_lessons"]["added"]) == 1


def test_diff_claims_added_removed_status_changed() -> None:
    old = {
        "artifact": "chimera_work_packet",
        "summary": {"shown_claim_count": 2}, "tool_notes": [], "candidate_tool_lessons": [],
        "claims": [
            {"claim_id": "c1", "latest_status": "validated"},
            {"claim_id": "c2", "latest_status": "proposed"},
        ],
    }
    new = {
        "artifact": "chimera_work_packet",
        "summary": {"shown_claim_count": 2}, "tool_notes": [], "candidate_tool_lessons": [],
        "claims": [
            {"claim_id": "c2", "latest_status": "validated"},
            {"claim_id": "c3", "latest_status": "proposed"},
        ],
    }
    d = diff_packets(old, new, old_path="o", new_path="n")
    assert d["claims"]["added"] == ["c3"]
    assert d["claims"]["removed"] == ["c1"]
    assert d["claims"]["status_changed"] == [
        {"claim_id": "c2", "old_status": "proposed", "new_status": "validated"},
    ]


def test_render_diff_markdown_formats_deltas() -> None:
    old = {
        "artifact": "chimera_work_packet",
        "summary": {"shown_claim_count": 1, "open_or_unresolved_count": 2, "tool_note_count": 0,
                    "candidate_count": 0, "settled_claim_count": 1,
                    "next_inspection_target_count": 2},
        "claims": [{"claim_id": "c1", "latest_status": "proposed"}],
        "tool_notes": [], "candidate_tool_lessons": [],
    }
    new = {
        "artifact": "chimera_work_packet",
        "summary": {"shown_claim_count": 2, "open_or_unresolved_count": 1, "tool_note_count": 1,
                    "candidate_count": 0, "settled_claim_count": 2,
                    "next_inspection_target_count": 1},
        "claims": [{"claim_id": "c1", "latest_status": "validated"},
                   {"claim_id": "c2", "latest_status": "proposed"}],
        "tool_notes": [{"note_id": "tn_a"}], "candidate_tool_lessons": [],
    }
    md = render_diff_markdown(diff_packets(old, new, old_path="o", new_path="n"))
    assert "# Chimera Work Packet Diff" in md
    assert "Local packet comparison" in md
    assert "claims shown: +1" in md
    assert "unresolved: -1" in md
    assert "tool lessons: +1" in md
    assert "candidate lessons: 0" in md
    assert "c1: proposed -> validated" in md


def test_diff_tool_notes_and_candidates_added_removed() -> None:
    old = {
        "summary": {}, "claims": [],
        "tool_notes": [{"note_id": "tn_a"}, {"note_id": "tn_b"}],
        "candidate_tool_lessons": [{"candidate_id": "cand_x"}],
    }
    new = {
        "summary": {}, "claims": [],
        "tool_notes": [{"note_id": "tn_b"}, {"note_id": "tn_c"}],
        "candidate_tool_lessons": [{"candidate_id": "cand_y"}],
    }
    d = diff_packets(old, new, old_path="o", new_path="n")
    assert d["tool_notes"]["added"] == ["tn_c"]
    assert d["tool_notes"]["removed"] == ["tn_a"]
    assert d["candidate_tool_lessons"]["added"] == ["cand_y"]
    assert d["candidate_tool_lessons"]["removed"] == ["cand_x"]


def test_diff_cli_text_and_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_notes_and_activity(tmp_path)
    mem = tmp_path / ".chimera-memory"
    a = tmp_path / "a"
    b = tmp_path / "b"
    _run(capsys, "work-packet", "bundle", "--output-dir", str(a), "--memory-dir", str(mem))
    _run(capsys, "work-packet", "bundle", "--output-dir", str(b), "--memory-dir", str(mem))
    code, text = _run(capsys, "work-packet", "diff", str(a), str(b))
    assert code == 0
    assert "# Chimera Work Packet Diff" in text
    code, jout = _run(capsys, "work-packet", "diff", str(a), str(b), "--json")
    assert code == 0
    assert json.loads(jout)["artifact"] == "chimera_work_packet_diff"


def test_diff_is_read_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_notes_and_activity(tmp_path)
    mem = tmp_path / ".chimera-memory"
    a = tmp_path / "a"
    b = tmp_path / "b"
    write_work_packet_bundle(_packet(tmp_path), output_dir=a, store_label="ws")
    write_work_packet_bundle(_packet(tmp_path), output_dir=b, store_label="ws")
    snap = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    a_snap = {p.name: p.read_bytes() for p in sorted(a.iterdir())}
    _run(capsys, "work-packet", "diff", str(a), str(b))
    _run(capsys, "work-packet", "diff", str(a), str(b), "--json")
    assert {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()} == snap
    assert {p.name: p.read_bytes() for p in sorted(a.iterdir())} == a_snap


def test_bundle_diff_no_forbidden_phrases(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_notes_and_activity(tmp_path)
    mem = tmp_path / ".chimera-memory"
    a = tmp_path / "a"
    b = tmp_path / "b"
    _run(capsys, "work-packet", "bundle", "--output-dir", str(a), "--memory-dir", str(mem))
    _run(capsys, "work-packet", "bundle", "--output-dir", str(b), "--memory-dir", str(mem))
    blob = ""
    blob += (a / "manifest.json").read_text(encoding="utf-8")
    blob += (a / "README.md").read_text(encoding="utf-8")
    _, out = _run(capsys, "work-packet", "inspect", str(a))
    blob += out
    _, out = _run(capsys, "work-packet", "diff", str(a), str(b))
    blob += out
    for argv in (("work-packet", "bundle", "--help"), ("work-packet", "inspect", "--help"),
                 ("work-packet", "diff", "--help")):
        _, out = _run(capsys, *argv)
        blob += out
    low = blob.lower()
    for phrase in _FORBIDDEN:
        assert phrase not in low, f"overclaim phrase leaked: {phrase!r}"
