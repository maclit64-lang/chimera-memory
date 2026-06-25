"""Tests for the Agent / Branch Primer v0 artifact (read-only, local, advisory)."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from chimera_memory.branch_primer import (
    PackError,
    build_branch_primer,
    render_branch_primer_markdown,
    render_prompt_header,
    write_kickoff_pack,
)
from chimera_memory.cli import main
from chimera_memory.storage import MemoryStore
from chimera_memory.tool_activity import add_tool_activity, build_tool_activity
from chimera_memory.tool_notes import add_tool_note, build_tool_note
from chimera_memory.work_packet import (
    ThreadError,
    add_thread_snapshot,
    build_work_packet,
    inspect_bundle,
    read_thread_index,
)

_FORBIDDEN = (
    "safe to merge", "production ready", "production-ready", "certified",
    "approved", "guaranteed", "proves correctness", "proves safety",
    "trusted", "proof-carrying", "proof", "optimal", "guaranteed faster",
)
_TOP_KEYS = {
    "schema_version", "artifact", "advisory", "generated_at", "filters", "summary",
    "work_packet", "thread_delta", "next_inspection_targets", "tool_notes",
    "candidate_tool_lessons", "suggested_first_read",
}
_SUMMARY_KEYS = {
    "shown_claim_count", "open_or_unresolved_count", "next_inspection_target_count",
    "tool_note_count", "candidate_count", "thread_snapshot_count",
}
_FILTER_KEYS = {
    "claim_id", "session_id", "status", "task_kind", "tag", "thread_dir", "since",
    "limit_tool_notes", "limit_candidates",
}
_T0 = datetime(2026, 6, 25, 10, 0, 0, tzinfo=UTC)


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")


def _seed_claims(root: Path) -> None:
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
        tags=("repo-forensics",)))
    add_tool_note(store, build_tool_note(
        task_kind="quick-fix", tool_name="single-agent", workflow_name="direct-edit",
        lesson="Small edits need no fanout.", tags=("small",)))
    add_tool_activity(store, build_tool_activity(
        task_kind="large-repo-forensics", tool_name="parallel-agents",
        workflow_name="unit-card-specialist-fanout", summary="big synthesis",
        tags=("repo-forensics",)))
    add_tool_activity(store, build_tool_activity(
        task_kind="quick-fix", tool_name="single-agent", workflow_name="direct-edit",
        summary="one-line fix", tags=("small",)))


def _seed_thread(root: Path, *, two: bool) -> Path:
    store = MemoryStore.from_paths(root=root)
    add_tool_note(store, build_tool_note(task_kind="large-repo-forensics", tool_name="pa",
                                         workflow_name="wf", lesson="L", tags=("repo-forensics",)))
    td = root / "review-thread"
    add_thread_snapshot(build_work_packet(store, generated_at=_T0.isoformat()),
                        thread_dir=td, store_label="ws", now=_T0, label="first")
    if two:
        add_tool_note(store, build_tool_note(task_kind="quick-fix", tool_name="single",
                                             lesson="L2", tags=("small",)))
        t1 = _T0 + timedelta(seconds=5)
        add_thread_snapshot(build_work_packet(store, generated_at=t1.isoformat()),
                            thread_dir=td, store_label="ws", now=t1, label="second")
    return td


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


def _primer(root: Path, **kwargs: Any) -> Any:
    return build_branch_primer(
        MemoryStore.from_paths(root=root), generated_at="T", store_label="ws", **kwargs)


# --- shape ------------------------------------------------------------------

def test_branch_primer_json_schema(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_claims(tmp_path)
    _seed_notes_and_activity(tmp_path)
    mem = tmp_path / ".chimera-memory"
    code, out = _run(capsys, "branch-primer", "--json", "--memory-dir", str(mem))
    assert code == 0
    d = json.loads(out)
    assert set(d) == _TOP_KEYS
    assert d["artifact"] == "chimera_branch_primer"
    assert "local work context and operational memory only" in d["advisory"]
    assert set(d["summary"]) == _SUMMARY_KEYS
    assert set(d["filters"]) == _FILTER_KEYS
    assert set(d["work_packet"]) == {"artifact", "advisory", "generated_at", "filters", "summary"}
    assert isinstance(d["suggested_first_read"], list)
    assert d["thread_delta"] is None


def test_branch_primer_markdown_shape(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_claims(tmp_path)
    mem = tmp_path / ".chimera-memory"
    code, out = _run(capsys, "branch-primer", "--memory-dir", str(mem))
    assert code == 0
    for header in ("# Chimera Branch Primer", "## Start here", "## Current work state",
                   "## Next inspection targets", "## Relevant tool lessons",
                   "## Candidate lessons to review", "## Suggested first read"):
        assert header in out, header
    assert "## Latest thread delta" not in out  # no thread provided


def test_branch_primer_empty_store_does_not_create(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"
    code, out = _run(capsys, "branch-primer", "--json", "--memory-dir", str(mem))
    assert code == 0
    d = json.loads(out)
    assert d["summary"] == {k: 0 for k in _SUMMARY_KEYS}
    assert not mem.exists()


# --- filters ----------------------------------------------------------------

def test_branch_primer_claim_session_status_filters(tmp_path: Path) -> None:
    _seed_claims(tmp_path)
    both = _primer(tmp_path, session_id="s1")
    assert {t.claim_id for t in both.next_inspection_targets} == {"c2"}  # c2 unresolved
    validated = _primer(tmp_path, status="validated")
    assert validated.summary.shown_claim_count == 1
    only_c2 = _primer(tmp_path, claim_id="c2")
    assert only_c2.summary.shown_claim_count == 1


def test_branch_primer_task_kind_tag_filters(tmp_path: Path) -> None:
    _seed_notes_and_activity(tmp_path)
    by_task = _primer(tmp_path, task_kind="large-repo-forensics")
    assert by_task.summary.tool_note_count == 1
    assert by_task.summary.candidate_count == 1
    by_tag = _primer(tmp_path, tag="small")
    assert by_tag.summary.tool_note_count == 1
    anded = _primer(tmp_path, task_kind="large-repo-forensics", tag="small")
    assert anded.summary.tool_note_count == 0
    assert anded.summary.candidate_count == 0


def test_branch_primer_limits_after_filters(tmp_path: Path) -> None:
    _seed_notes_and_activity(tmp_path)
    p = _primer(tmp_path, limit_tool_notes=1, limit_candidates=1)
    assert p.summary.tool_note_count == 1
    assert p.summary.candidate_count == 1
    p0 = _primer(tmp_path, limit_tool_notes=0, limit_candidates=0)
    assert p0.summary.tool_note_count == 0
    assert p0.summary.candidate_count == 0


# --- thread integration -----------------------------------------------------

def test_branch_primer_thread_one_snapshot_no_delta(tmp_path: Path) -> None:
    td = _seed_thread(tmp_path, two=False)
    p = _primer(tmp_path, thread_dir=td)
    assert p.summary.thread_snapshot_count == 1
    assert p.thread_delta is None
    # suggested_first_read points at the thread index + latest packet
    joined = "\n".join(p.suggested_first_read)
    assert "INDEX.md" in joined and "WORK_PACKET.md" in joined


def test_branch_primer_thread_two_snapshots_delta(tmp_path: Path) -> None:
    td = _seed_thread(tmp_path, two=True)
    p = _primer(tmp_path, thread_dir=td)
    assert p.summary.thread_snapshot_count == 2
    assert p.thread_delta is not None
    assert p.thread_delta["mode"] == "latest-two"
    assert p.thread_delta["diff"]["artifact"] == "chimera_work_packet_diff"
    md = render_branch_primer_markdown(p, store_label="ws")
    assert "## Latest thread delta" in md


def test_branch_primer_invalid_thread_raises(tmp_path: Path) -> None:
    with pytest.raises(ThreadError):
        _primer(tmp_path, thread_dir=tmp_path / "no-such-thread")


def test_branch_primer_cli_invalid_thread_exit2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"
    mem.mkdir()
    code, _ = _run(capsys, "branch-primer", "--thread-dir", str(tmp_path / "nope"),
                   "--memory-dir", str(mem))
    assert code == 2


def test_branch_primer_cli_thread_delta(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    td = _seed_thread(tmp_path, two=True)
    mem = tmp_path / ".chimera-memory"
    code, out = _run(capsys, "branch-primer", "--json", "--thread-dir", str(td),
                     "--memory-dir", str(mem))
    assert code == 0
    d = json.loads(out)
    assert d["summary"]["thread_snapshot_count"] == 2
    assert d["thread_delta"]["mode"] == "latest-two"
    assert d["thread_delta"]["diff"]["artifact"] == "chimera_work_packet_diff"


# --- read-only / output -----------------------------------------------------

def test_branch_primer_is_read_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    td = _seed_thread(tmp_path, two=True)
    mem = tmp_path / ".chimera-memory"
    store_snap = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    thread_snap = sorted((str(p.relative_to(td)), p.stat().st_size)
                         for p in td.rglob("*") if p.is_file())
    _run(capsys, "branch-primer", "--thread-dir", str(td), "--memory-dir", str(mem))
    _run(capsys, "branch-primer", "--json", "--thread-dir", str(td), "--memory-dir", str(mem))
    assert {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()} == store_snap
    assert sorted((str(p.relative_to(td)), p.stat().st_size)
                  for p in td.rglob("*") if p.is_file()) == thread_snap


def test_branch_primer_output_writes_only_requested_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_notes_and_activity(tmp_path)
    mem = tmp_path / ".chimera-memory"
    out_file = tmp_path / "BRANCH_PRIMER.md"
    before = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    code, out = _run(capsys, "branch-primer", "--output", str(out_file), "--memory-dir", str(mem))
    assert code == 0
    assert out_file.exists()
    assert "# Chimera Branch Primer" in out_file.read_text(encoding="utf-8")
    assert f"written to {out_file}" in out
    after = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    assert before == after


def test_branch_primer_no_forbidden_phrases(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_claims(tmp_path)
    _seed_notes_and_activity(tmp_path)
    td = _seed_thread(tmp_path, two=True)
    mem = tmp_path / ".chimera-memory"
    blob = ""
    _, out = _run(capsys, "branch-primer", "--thread-dir", str(td), "--memory-dir", str(mem))
    blob += out
    _, out = _run(capsys, "branch-primer", "--json", "--memory-dir", str(mem))
    blob += out
    _, out = _run(capsys, "branch-primer", "--help")
    blob += out
    blob += (Path(__file__).resolve().parents[3] / "docs" / "branch-primer.md").read_text(
        encoding="utf-8")
    low = blob.lower()
    for phrase in _FORBIDDEN:
        assert phrase not in low, f"overclaim phrase leaked: {phrase!r}"


# ── v0.29: --since / prompt-header / kickoff pack ────────────────────────────

_PACK_MANIFEST_KEYS = {
    "schema_version", "artifact", "generated_at", "advisory", "filters",
    "primer_summary", "files",
}


def _first_snapshot_id(td: Path) -> str:
    index = read_thread_index(td)
    assert index is not None
    return index["snapshots"][0]["snapshot_id"]  # type: ignore[no-any-return]


def test_since_requires_thread_dir(tmp_path: Path) -> None:
    _seed_notes_and_activity(tmp_path)
    with pytest.raises(ThreadError):
        _primer(tmp_path, since="wp_anything")


def test_since_exact_snapshot(tmp_path: Path) -> None:
    td = _seed_thread(tmp_path, two=True)
    first = _first_snapshot_id(td)
    p = _primer(tmp_path, thread_dir=td, since=first)
    assert p.thread_delta is not None
    assert p.thread_delta["mode"] == "since"
    assert p.thread_delta["old_snapshot_id"] == first
    assert p.thread_delta["diff"]["artifact"] == "chimera_work_packet_diff"
    assert p.filters.since == first


def test_since_missing_id_fails_cleanly(tmp_path: Path) -> None:
    td = _seed_thread(tmp_path, two=True)
    with pytest.raises(ThreadError):
        _primer(tmp_path, thread_dir=td, since="wp_does_not_exist")


def test_default_latest_two_delta_still_works(tmp_path: Path) -> None:
    td = _seed_thread(tmp_path, two=True)
    p = _primer(tmp_path, thread_dir=td)
    assert p.thread_delta is not None
    assert p.thread_delta["mode"] == "latest-two"


def test_since_cli_requires_thread_and_validates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    td = _seed_thread(tmp_path, two=True)
    mem = tmp_path / ".chimera-memory"
    first = _first_snapshot_id(td)
    code, _ = _run(capsys, "branch-primer", "--since", first, "--memory-dir", str(mem))
    assert code == 2  # since without thread-dir
    code, out = _run(capsys, "branch-primer", "--json", "--thread-dir", str(td),
                     "--since", first, "--memory-dir", str(mem))
    assert code == 0
    assert json.loads(out)["thread_delta"]["mode"] == "since"
    code, _ = _run(capsys, "branch-primer", "--thread-dir", str(td), "--since", "wp_nope",
                   "--memory-dir", str(mem))
    assert code == 2


# --- prompt header ----------------------------------------------------------

def test_prompt_header_shape(tmp_path: Path) -> None:
    td = _seed_thread(tmp_path, two=True)
    p = _primer(tmp_path, thread_dir=td, since=_first_snapshot_id(td))
    header = render_prompt_header(p)
    for section in ("# Chimera Agent Kickoff Header", "Read this before starting work.",
                    "Current work state:", "Thread context:", "First inspection targets:",
                    "Relevant tool lessons:", "Candidate lessons to review:"):
        assert section in header, section
    assert "delta source: since" in header


def test_prompt_header_cli_and_no_forbidden(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_notes_and_activity(tmp_path)
    mem = tmp_path / ".chimera-memory"
    code, out = _run(capsys, "branch-primer", "--prompt-header", "--memory-dir", str(mem))
    assert code == 0
    assert "# Chimera Agent Kickoff Header" in out
    low = out.lower()
    for phrase in _FORBIDDEN:
        assert phrase not in low, f"overclaim phrase leaked: {phrase!r}"


# --- kickoff pack bundle ----------------------------------------------------

def _pack(tmp_path: Path, out: Path, **kwargs: Any) -> dict[str, Any]:
    p = _primer(tmp_path, **kwargs)
    return write_kickoff_pack(p, output_dir=out, store_label="ws")


def test_bundle_creates_five_files_and_manifest(tmp_path: Path) -> None:
    _seed_notes_and_activity(tmp_path)
    out = tmp_path / "pack"
    manifest = _pack(tmp_path, out)
    assert sorted(p.name for p in out.iterdir()) == [
        "AGENT_PROMPT_HEADER.md", "BRANCH_PRIMER.md", "README.md",
        "branch-primer.json", "manifest.json",
    ]
    assert set(manifest) == _PACK_MANIFEST_KEYS
    assert manifest["artifact"] == "chimera_agent_kickoff_pack"
    assert [f["path"] for f in manifest["files"]] == [
        "BRANCH_PRIMER.md", "branch-primer.json", "AGENT_PROMPT_HEADER.md", "README.md",
    ]


def test_bundle_manifest_hashes_verify(tmp_path: Path) -> None:
    _seed_notes_and_activity(tmp_path)
    out = tmp_path / "pack"
    manifest = _pack(tmp_path, out)
    import hashlib
    for entry in manifest["files"]:
        data = (out / entry["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        assert len(data) == entry["bytes"]
    assert inspect_bundle(out)["valid"] is True


def test_bundle_does_not_mutate_store_or_thread(tmp_path: Path) -> None:
    td = _seed_thread(tmp_path, two=True)
    mem = tmp_path / ".chimera-memory"
    store_snap = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    thread_snap = sorted((str(p.relative_to(td)), p.stat().st_size)
                         for p in td.rglob("*") if p.is_file())
    _pack(tmp_path, tmp_path / "pack", thread_dir=td)
    assert {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()} == store_snap
    assert sorted((str(p.relative_to(td)), p.stat().st_size)
                  for p in td.rglob("*") if p.is_file()) == thread_snap


def test_bundle_missing_parent_fails_cleanly(tmp_path: Path) -> None:
    _seed_notes_and_activity(tmp_path)
    with pytest.raises(PackError):
        _pack(tmp_path, tmp_path / "nope" / "pack")


def test_bundle_refuses_non_empty_without_force(tmp_path: Path) -> None:
    _seed_notes_and_activity(tmp_path)
    out = tmp_path / "pack"
    _pack(tmp_path, out)
    with pytest.raises(PackError):
        _pack(tmp_path, out)


def test_bundle_force_overwrites_only_known_files(tmp_path: Path) -> None:
    _seed_notes_and_activity(tmp_path)
    out = tmp_path / "pack"
    _pack(tmp_path, out)
    sentinel = out / "unrelated.txt"
    sentinel.write_text("keep", encoding="utf-8")
    p = _primer(tmp_path)
    write_kickoff_pack(p, output_dir=out, store_label="ws", force=True)
    assert inspect_bundle(out)["valid"] is True
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_bundle_cli_and_inspect(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    td = _seed_thread(tmp_path, two=True)
    mem = tmp_path / ".chimera-memory"
    out = tmp_path / "pack"
    code, _ = _run(capsys, "branch-primer", "bundle", "--output-dir", str(out),
                   "--thread-dir", str(td), "--since", _first_snapshot_id(td),
                   "--memory-dir", str(mem))
    assert code == 0
    assert (out / "manifest.json").exists()
    code, jout = _run(capsys, "branch-primer", "inspect", str(out), "--json")
    assert code == 0
    assert json.loads(jout)["valid"] is True
    # refuse non-empty without --force
    code, _ = _run(capsys, "branch-primer", "bundle", "--output-dir", str(out),
                   "--memory-dir", str(mem))
    assert code == 2
    # tamper -> inspect invalid (exit 1)
    (out / "AGENT_PROMPT_HEADER.md").write_text("tampered", encoding="utf-8")
    code, _ = _run(capsys, "branch-primer", "inspect", str(out))
    assert code == 1
