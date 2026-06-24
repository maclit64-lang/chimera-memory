"""Stage 2: ledger-derived handoff MVP tests.

Covers the handoff module (build/render) and the `handoff` CLI command. Seeds a
store with one fully-settled claim and one unsettled claim so the
open/unresolved and next-inspection-target paths are exercised. Structured
assertions only; no large markdown snapshots.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from chimera_memory.cli import main
from chimera_memory.handoff import ADVISORY, build_handoff, handoff_for_root, render_markdown
from chimera_memory.storage import MemoryStore
from chimera_memory.tool_notes import add_tool_note, build_tool_note

_FORBIDDEN = (
    "safe to merge",
    "production ready",
    "production-ready",
    "certified",
    "approved",
    "guaranteed",
    "proves correctness",
    "proves safety",
    "trusted",
    "proof-carrying",
    "proof",
)

# Stage 2B: `filters` is an additive 8th top-level key (was 7 in Stage 2).
# Stage 3: `tool_notes` is an additive 9th top-level key.
_TOP_KEYS = {
    "schema_version", "advisory", "filters", "event_count", "settled_claim_count",
    "claims", "open_or_unresolved", "next_inspection_targets", "tool_notes",
}


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")


def _seed(root: Path) -> Path:
    """Seed one settled claim (c1) and one unsettled claim (c2). Returns mem dir."""
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
    _write_jsonl(mem / "sessions.jsonl", [
        {"event": "start", "session": {"session_id": "s1", "started_at": "2026-01-01T00:00:00Z",
                                       "ended_at": None, "final_status": None}},
    ])
    return mem


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


# --- module-level -----------------------------------------------------------

def test_handoff_summary_counts_and_advisory(tmp_path: Path) -> None:
    _seed(tmp_path)
    summary = handoff_for_root(tmp_path)
    assert summary.schema_version == 1
    assert "not a correctness, safety, merge, approval, or production-readiness" in summary.advisory
    assert summary.settled_claim_count == 2  # c1 + c2
    assert len(summary.claims) == 2


def test_unsettled_claim_appears_in_open_or_unresolved(tmp_path: Path) -> None:
    _seed(tmp_path)
    summary = handoff_for_root(tmp_path)
    open_ids = {o.claim_id for o in summary.open_or_unresolved}
    assert open_ids == {"c2"}  # c1 is fully settled, c2 is not
    [c2] = [o for o in summary.open_or_unresolved if o.claim_id == "c2"]
    assert "no_settlement_record" in c2.reasons
    assert "no_score_record" in c2.reasons
    # next inspection targets are deterministic and point at c2 first
    assert summary.next_inspection_targets[0].claim_id == "c2"
    assert summary.next_inspection_targets[0].reason == "no_settlement_record"


def test_empty_store_zero_counts_no_crash(tmp_path: Path) -> None:
    summary = build_handoff(MemoryStore.from_paths(root=tmp_path))
    assert summary.event_count == 0
    assert summary.settled_claim_count == 0
    assert summary.claims == ()
    assert summary.open_or_unresolved == ()
    assert summary.next_inspection_targets == ()


def test_to_dict_is_exactly_the_contract(tmp_path: Path) -> None:
    _seed(tmp_path)
    d = handoff_for_root(tmp_path).to_dict()
    assert set(d) == _TOP_KEYS
    assert d["advisory"] == ADVISORY
    assert isinstance(d["claims"], list)
    assert set(d["claims"][0]) == {
        "claim_id", "latest_status", "event_count", "has_claim_record",
        "has_settlement_record", "has_score_record", "latest_exit_code",
    }


def test_markdown_has_advisory_and_sections(tmp_path: Path) -> None:
    _seed(tmp_path)
    md = render_markdown(
        handoff_for_root(tmp_path), store_label=".chimera-memory", generated_at="2026-01-01T00:00:00Z"
    )
    assert md.startswith("# Chimera Memory Handoff")
    assert "Advisory only." in md
    assert "## Claims" in md
    assert "## Open / unresolved evidence" in md
    assert "## Next inspection targets" in md
    assert "`c2`" in md  # the unresolved claim is listed


# --- CLI --------------------------------------------------------------------

def test_cli_handoff_json_contract(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = _seed(tmp_path)
    code, out = _run(capsys, "handoff", "--json", "--memory-dir", str(mem))
    assert code == 0
    data = json.loads(out)
    assert set(data) == _TOP_KEYS
    assert data["schema_version"] == 1
    assert data["settled_claim_count"] == 2
    assert len(data["claims"]) == 2
    assert len(data["open_or_unresolved"]) == 1


def test_cli_handoff_markdown_default(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = _seed(tmp_path)
    code, out = _run(capsys, "handoff", "--memory-dir", str(mem))
    assert code == 0
    assert out.startswith("# Chimera Memory Handoff")
    assert "Advisory only." in out


def test_cli_empty_store(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = tmp_path / ".chimera-memory"
    mem.mkdir()
    code, out = _run(capsys, "handoff", "--json", "--memory-dir", str(mem))
    assert code == 0
    data = json.loads(out)
    assert data["event_count"] == 0
    assert data["settled_claim_count"] == 0
    assert data["claims"] == []


def test_cli_handoff_is_read_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = _seed(tmp_path)
    before = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    _run(capsys, "handoff", "--json", "--memory-dir", str(mem))
    _run(capsys, "handoff", "--markdown", "--memory-dir", str(mem))
    _run(capsys, "handoff", "--memory-dir", str(mem))
    after = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    assert before == after


def test_no_forbidden_overclaim_phrases(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = _seed(tmp_path)
    blob = ""
    for argv in (("handoff", "--json"), ("handoff", "--markdown"), ("handoff", "--help")):
        _, out = _run(capsys, *argv, *(("--memory-dir", str(mem)) if argv[-1] != "--help" else ()))
        blob += out
    low = blob.lower()
    for phrase in _FORBIDDEN:
        assert phrase not in low, f"overclaim phrase leaked: {phrase!r}"


def test_existing_projection_commands_still_work(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = _seed(tmp_path)
    _, out_e = _run(capsys, "evidence-events", "--json", "--memory-dir", str(mem))
    assert json.loads(out_e)["schema_version"] == 1
    _, out_s = _run(capsys, "settled-claims", "--json", "--memory-dir", str(mem))
    assert json.loads(out_s)["schema_version"] == 1


# --- Stage 2B: filters ------------------------------------------------------

def test_filters_default_none_and_present_in_contract(tmp_path: Path) -> None:
    _seed(tmp_path)
    d = handoff_for_root(tmp_path).to_dict()
    # Stage 3B: filters extended with tool-note keys (all default None).
    assert d["filters"] == {
        "session_id": None, "claim_id": None, "status": None,
        "task_kind": None, "tool_name": None, "workflow_name": None, "tag": None,
    }


def test_filter_by_claim(tmp_path: Path) -> None:
    _seed(tmp_path)
    summary = handoff_for_root(tmp_path, claim_id="c1")
    assert [c.claim_id for c in summary.claims] == ["c1"]
    assert summary.settled_claim_count == 1
    assert summary.filters.claim_id == "c1"


def test_filter_by_claim_missing_returns_empty_with_advisory(tmp_path: Path) -> None:
    _seed(tmp_path)
    summary = handoff_for_root(tmp_path, claim_id="does-not-exist")
    assert summary.claims == ()
    assert summary.settled_claim_count == 0
    assert summary.open_or_unresolved == ()
    assert summary.advisory == ADVISORY  # advisory intact


def test_filter_by_status_exact(tmp_path: Path) -> None:
    _seed(tmp_path)
    assert [c.claim_id for c in handoff_for_root(tmp_path, status="validated").claims] == ["c1"]
    assert [c.claim_id for c in handoff_for_root(tmp_path, status="proposed").claims] == ["c2"]
    assert handoff_for_root(tmp_path, status="nope").claims == ()


def test_filter_by_session(tmp_path: Path) -> None:
    _seed(tmp_path)
    summary = handoff_for_root(tmp_path, session_id="s1")
    assert {c.claim_id for c in summary.claims} == {"c1", "c2"}  # both belong to s1
    # a session with no matching claim returns empty (no invented ownership)
    assert handoff_for_root(tmp_path, session_id="sX").claims == ()


def test_filters_combine_with_and(tmp_path: Path) -> None:
    _seed(tmp_path)
    summary = handoff_for_root(tmp_path, session_id="s1", status="validated")
    assert [c.claim_id for c in summary.claims] == ["c1"]


def test_event_count_stays_global_under_filter(tmp_path: Path) -> None:
    _seed(tmp_path)
    full = handoff_for_root(tmp_path)
    filtered = handoff_for_root(tmp_path, claim_id="c1")
    assert filtered.event_count == full.event_count  # store-global, not narrowed


def test_unfiltered_handoff_remains_compatible(tmp_path: Path) -> None:
    _seed(tmp_path)
    summary = handoff_for_root(tmp_path)
    assert summary.settled_claim_count == 2  # c1 + c2, unchanged from Stage 2 behavior
    assert summary.filters.session_id is None
    assert summary.filters.claim_id is None
    assert summary.filters.status is None


def test_cli_filter_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = _seed(tmp_path)
    code, out = _run(capsys, "handoff", "--json", "--claim", "c1", "--memory-dir", str(mem))
    assert code == 0
    data = json.loads(out)
    assert set(data) == _TOP_KEYS
    assert data["filters"]["claim_id"] == "c1"
    assert len(data["claims"]) == 1


def test_cli_filter_markdown(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = _seed(tmp_path)
    code, out = _run(capsys, "handoff", "--markdown", "--status", "proposed", "--memory-dir", str(mem))
    assert code == 0
    assert "filters:" in out
    assert "`c2`" in out      # the proposed claim is shown
    assert "`c1`" not in out  # the validated claim is filtered out


def test_cli_filtered_handoff_is_read_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = _seed(tmp_path)
    before = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    _run(capsys, "handoff", "--json", "--session", "s1", "--memory-dir", str(mem))
    _run(capsys, "handoff", "--markdown", "--claim", "c1", "--memory-dir", str(mem))
    _run(capsys, "handoff", "--json", "--status", "validated", "--memory-dir", str(mem))
    after = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    assert before == after


def test_no_forbidden_phrases_in_filtered_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = _seed(tmp_path)
    blob = ""
    _, out = _run(capsys, "handoff", "--json", "--claim", "c1", "--memory-dir", str(mem))
    blob += out
    _, out = _run(capsys, "handoff", "--markdown", "--session", "s1", "--memory-dir", str(mem))
    blob += out
    low = blob.lower()
    for phrase in _FORBIDDEN:
        assert phrase not in low, f"overclaim phrase leaked: {phrase!r}"


# --- Stage 3: tool-notes integration ----------------------------------------

def test_handoff_tool_notes_empty_by_default(tmp_path: Path) -> None:
    _seed(tmp_path)
    summary = handoff_for_root(tmp_path)
    assert summary.tool_notes == ()
    assert summary.to_dict()["tool_notes"] == []
    # markdown shows no Tool lessons section when there are no notes
    md = render_markdown(summary, store_label=".chimera-memory", generated_at="2026-01-01T00:00:00Z")
    assert "## Tool lessons" not in md


def test_handoff_includes_tool_lessons_when_notes_exist(tmp_path: Path) -> None:
    _seed(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    add_tool_note(store, build_tool_note(
        task_kind="large-repo-forensics", tool_name="parallel-agents",
        workflow_name="unit-card-specialist-fanout",
        lesson="Use coverage manifests before synthesis.",
        evidence="2189/2189 files read.", caveat="High cost/time.",
    ))
    summary = handoff_for_root(tmp_path)
    assert len(summary.tool_notes) == 1
    d = summary.to_dict()
    assert set(d) == _TOP_KEYS
    assert len(d["tool_notes"]) == 1
    assert d["tool_notes"][0]["task_kind"] == "large-repo-forensics"
    md = render_markdown(summary, store_label=".chimera-memory", generated_at="2026-01-01T00:00:00Z")
    assert "## Tool lessons" in md
    assert "parallel-agents / unit-card-specialist-fanout" in md
    assert "Use coverage manifests before synthesis." in md


def test_handoff_tool_notes_shown_regardless_of_claim_filter(tmp_path: Path) -> None:
    _seed(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    add_tool_note(store, build_tool_note(task_kind="k", tool_name="t", workflow_name="w"))
    # a claim filter narrows claims but tool notes remain (they are not claim-scoped)
    summary = handoff_for_root(tmp_path, claim_id="c1")
    assert [c.claim_id for c in summary.claims] == ["c1"]
    assert len(summary.tool_notes) == 1


def test_cli_handoff_json_includes_tool_notes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = _seed(tmp_path)
    _run(capsys, "tool-notes", "add", "--task-kind", "k", "--tool", "t",
         "--workflow", "w", "--lesson", "l", "--memory-dir", str(mem))
    code, out = _run(capsys, "handoff", "--json", "--memory-dir", str(mem))
    assert code == 0
    data = json.loads(out)
    assert set(data) == _TOP_KEYS
    assert len(data["tool_notes"]) == 1


# --- Stage 3B: handoff tool-note filters ------------------------------------

def _add_two_notes(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    add_tool_note(store, build_tool_note(
        task_kind="A", tool_name="ta", workflow_name="wa", tags=("x",)))
    add_tool_note(store, build_tool_note(
        task_kind="B", tool_name="tb", workflow_name="wb", tags=("y",)))


def test_handoff_task_kind_filters_tool_notes_only(tmp_path: Path) -> None:
    _seed(tmp_path)          # claims c1 (validated) + c2 (proposed)
    _add_two_notes(tmp_path)
    summary = handoff_for_root(tmp_path, task_kind="A")
    assert [n.task_kind for n in summary.tool_notes] == ["A"]
    assert summary.settled_claim_count == 2  # claims NOT affected by tool-note filter
    assert summary.filters.task_kind == "A"


def test_handoff_tag_filters_tool_notes_only(tmp_path: Path) -> None:
    _seed(tmp_path)
    _add_two_notes(tmp_path)
    summary = handoff_for_root(tmp_path, tag="y")
    assert [n.task_kind for n in summary.tool_notes] == ["B"]
    assert summary.settled_claim_count == 2


def test_handoff_claim_filter_still_works_with_tool_note_filter(tmp_path: Path) -> None:
    _seed(tmp_path)
    _add_two_notes(tmp_path)
    summary = handoff_for_root(tmp_path, claim_id="c1", task_kind="A")
    assert [c.claim_id for c in summary.claims] == ["c1"]      # claim filter applied
    assert [n.task_kind for n in summary.tool_notes] == ["A"]  # tool-note filter applied


def test_handoff_existing_claim_session_status_filters_unaffected(tmp_path: Path) -> None:
    _seed(tmp_path)
    _add_two_notes(tmp_path)
    assert [c.claim_id for c in handoff_for_root(tmp_path, status="validated").claims] == ["c1"]
    assert {c.claim_id for c in handoff_for_root(tmp_path, session_id="s1").claims} == {"c1", "c2"}
    assert [c.claim_id for c in handoff_for_root(tmp_path, claim_id="c2").claims] == ["c2"]


def test_cli_handoff_tool_note_filter_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed(tmp_path)
    _add_two_notes(tmp_path)
    mem = tmp_path / ".chimera-memory"
    code, out = _run(capsys, "handoff", "--json", "--task-kind", "A", "--memory-dir", str(mem))
    assert code == 0
    data = json.loads(out)
    assert set(data) == _TOP_KEYS
    assert set(data["filters"]) == {
        "session_id", "claim_id", "status", "task_kind", "tool_name", "workflow_name", "tag",
    }
    assert data["filters"]["task_kind"] == "A"
    assert len(data["tool_notes"]) == 1
