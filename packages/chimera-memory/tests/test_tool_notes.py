"""Stage 3: manual Tool Notes tests (model, storage, CLI).

Structured assertions only. Verify add/list, stable schema, deterministic
note_id, missing-field tolerance, tag preservation, that tool notes never alter
the evidence/settled-claim projection, and that no overclaim phrases leak.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from chimera_memory.cli import main
from chimera_memory.evidence_events import project_evidence_events
from chimera_memory.settled_claims import project_settled_claims
from chimera_memory.storage import MemoryStore
from chimera_memory.tool_notes import (
    add_tool_note,
    build_tool_note,
    make_note_id,
    read_tool_notes,
)

_FORBIDDEN = (
    "safe to merge", "production ready", "production-ready", "certified",
    "approved", "guaranteed", "proves correctness", "proves safety",
    "trusted", "proof-carrying", "proof", "optimal", "guaranteed faster",
)

_NOTE_KEYS = {
    "schema_version", "note_id", "created_at", "task_kind", "tool_name",
    "workflow_name", "lesson", "evidence", "caveat", "source", "tags",
}


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


def test_add_writes_one_note_only_to_tool_notes_file(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    add_tool_note(store, build_tool_note(task_kind="k", tool_name="t", workflow_name="w", lesson="l"))
    notes = read_tool_notes(store)
    assert len(notes) == 1
    assert notes[0].task_kind == "k"
    files = sorted(p.name for p in (tmp_path / ".chimera-memory").iterdir() if p.is_file())
    assert files == ["tool_notes.jsonl"]  # no other ledger file created


def test_note_id_is_deterministic_and_content_addressed() -> None:
    kw = dict(created_at="2026-01-01T00:00:00Z", task_kind="k", tool_name="t",
              workflow_name="w", lesson="l")
    assert make_note_id(**kw) == make_note_id(**kw)
    assert make_note_id(**kw).startswith("tn_")
    changed = {**kw, "task_kind": "k2"}
    assert make_note_id(**changed) != make_note_id(**kw)


def test_missing_optional_fields_do_not_crash(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    add_tool_note(store, build_tool_note(task_kind="k"))
    [n] = read_tool_notes(store)
    assert n.tool_name is None
    assert n.lesson is None
    assert n.evidence is None
    assert n.tags == ()


def test_multiple_tags_preserved_round_trip(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    add_tool_note(store, build_tool_note(task_kind="k", tags=("a", "b", "c")))
    [n] = read_tool_notes(store)
    assert n.tags == ("a", "b", "c")


def test_cli_add_then_list_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = tmp_path / ".chimera-memory"
    code, out = _run(
        capsys, "tool-notes", "add", "--task-kind", "k", "--tool", "t",
        "--workflow", "w", "--lesson", "l", "--tag", "x", "--tag", "y",
        "--memory-dir", str(mem),
    )
    assert code == 0
    assert out.strip().startswith("tn_")
    code, out = _run(capsys, "tool-notes", "list", "--json", "--memory-dir", str(mem))
    data = json.loads(out)
    assert data["schema_version"] == 1
    assert len(data["tool_notes"]) == 1
    assert set(data["tool_notes"][0]) == _NOTE_KEYS
    assert data["tool_notes"][0]["tags"] == ["x", "y"]


def test_cli_list_empty_store(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = tmp_path / ".chimera-memory"
    mem.mkdir()
    code, out = _run(capsys, "tool-notes", "list", "--json", "--memory-dir", str(mem))
    assert code == 0
    assert json.loads(out) == {"schema_version": 1, "tool_notes": []}


def test_tool_notes_do_not_alter_projection(tmp_path: Path) -> None:
    mem = tmp_path / ".chimera-memory"
    mem.mkdir()
    (mem / "claims.jsonl").write_text(
        json.dumps({"claim_id": "c1", "claim_status": "validated", "title": "t",
                    "metadata": {}}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    store = MemoryStore.from_paths(root=tmp_path)
    before_events = len(project_evidence_events(store))
    before_claims = len(project_settled_claims(store))
    add_tool_note(store, build_tool_note(task_kind="k", tool_name="t"))
    assert len(project_evidence_events(store)) == before_events  # projection ignores tool notes
    assert len(project_settled_claims(store)) == before_claims


def test_no_forbidden_overclaim_phrases(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = tmp_path / ".chimera-memory"
    _run(
        capsys, "tool-notes", "add", "--task-kind", "k", "--tool", "t",
        "--workflow", "w", "--lesson", "Use coverage manifests before synthesis.",
        "--memory-dir", str(mem),
    )
    blob = ""
    _, out = _run(capsys, "tool-notes", "list", "--memory-dir", str(mem))
    blob += out
    _, out = _run(capsys, "tool-notes", "list", "--json", "--memory-dir", str(mem))
    blob += out
    for argv in (("tool-notes", "--help"), ("tool-notes", "add", "--help"),
                 ("tool-notes", "list", "--help")):
        _, out = _run(capsys, *argv)
        blob += out
    low = blob.lower()
    for phrase in _FORBIDDEN:
        assert phrase not in low, f"overclaim phrase leaked: {phrase!r}"
