"""Tool Activity + Candidate Lesson tests (model, CLI, manual-save loop)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from chimera_memory.cli import main
from chimera_memory.storage import MemoryStore
from chimera_memory.tool_activity import (
    add_tool_activity,
    build_tool_activity,
    project_candidates,
    read_tool_activities,
)

_FORBIDDEN = (
    "safe to merge", "production ready", "production-ready", "certified",
    "approved", "guaranteed", "proves correctness", "proves safety",
    "trusted", "proof-carrying", "proof", "optimal", "guaranteed faster",
)

_ACTIVITY_KEYS = {
    "schema_version", "activity_id", "created_at", "task_kind", "tool_name",
    "workflow_name", "phase", "summary", "evidence", "caveat", "status",
    "duration_seconds", "cost_units", "artifact_refs", "tags", "source",
}
_CANDIDATE_KEYS = {
    "schema_version", "candidate_id", "task_kind", "tool_name", "workflow_name",
    "lesson", "evidence", "caveat", "source_activity_ids",
}


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


# --- module -----------------------------------------------------------------

def test_activity_add_writes_only_tool_activity_file(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    add_tool_activity(store, build_tool_activity(task_kind="k", tool_name="t", summary="s"))
    acts = read_tool_activities(store)
    assert len(acts) == 1 and acts[0].task_kind == "k"
    files = sorted(p.name for p in (tmp_path / ".chimera-memory").iterdir() if p.is_file())
    assert files == ["tool_activity.jsonl"]


def test_candidate_projection_verbatim_and_deterministic(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    add_tool_activity(store, build_tool_activity(
        task_kind="k", tool_name="t", workflow_name="w", summary="did X", evidence="e", caveat="c"))
    acts = read_tool_activities(store)
    cands = project_candidates(acts)
    assert len(cands) == 1
    assert cands[0].lesson == "did X"  # verbatim from summary
    assert cands[0].source_activity_ids == (acts[0].activity_id,)
    assert [c.to_dict() for c in project_candidates(acts)] == [c.to_dict() for c in cands]


def test_candidate_skips_activity_missing_required(tmp_path: Path) -> None:
    mem = tmp_path / ".chimera-memory"
    mem.mkdir()
    (mem / "tool_activity.jsonl").write_text(
        json.dumps({"activity_id": "act_x", "task_kind": "k", "tool_name": "t"}) + "\n",
        encoding="utf-8",
    )
    store = MemoryStore.from_paths(root=tmp_path)
    assert project_candidates(read_tool_activities(store)) == []  # no summary -> skipped


# --- CLI --------------------------------------------------------------------

def test_cli_activity_add_list_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = tmp_path / ".chimera-memory"
    code, out = _run(
        capsys, "tool-activity", "add", "--task-kind", "large-repo-forensics",
        "--tool", "parallel-agents", "--workflow", "unit-card-specialist-fanout",
        "--summary", "7 agents.", "--duration-seconds", "12094", "--cost-units", "55.51",
        "--artifact-ref", "Unit Cards", "--tag", "repo-forensics", "--memory-dir", str(mem),
    )
    assert code == 0
    assert out.strip().startswith("act_")
    code, out = _run(capsys, "tool-activity", "list", "--json", "--memory-dir", str(mem))
    d = json.loads(out)
    assert d["schema_version"] == 1
    assert len(d["tool_activities"]) == 1
    a = d["tool_activities"][0]
    assert set(a) == _ACTIVITY_KEYS
    assert a["duration_seconds"] == 12094.0
    assert a["cost_units"] == 55.51
    assert a["artifact_refs"] == ["Unit Cards"]
    assert a["tags"] == ["repo-forensics"]


def test_cli_activity_add_requires_fields(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = tmp_path / ".chimera-memory"
    code, _ = _run(capsys, "tool-activity", "add", "--task-kind", "k", "--tool", "t",
                   "--memory-dir", str(mem))  # no --summary
    assert code == 2
    assert not mem.exists()  # invalid input writes nothing


def test_cli_activity_list_filters(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = tmp_path / ".chimera-memory"
    _run(capsys, "tool-activity", "add", "--task-kind", "A", "--tool", "ta",
         "--summary", "s1", "--tag", "x", "--memory-dir", str(mem))
    _run(capsys, "tool-activity", "add", "--task-kind", "B", "--tool", "tb",
         "--summary", "s2", "--tag", "y", "--memory-dir", str(mem))

    def count(*args: str) -> int:
        _, out = _run(capsys, "tool-activity", "list", "--json", *args, "--memory-dir", str(mem))
        return len(json.loads(out)["tool_activities"])

    assert count() == 2
    assert count("--task-kind", "A") == 1
    assert count("--tool", "tb") == 1
    assert count("--tag", "x") == 1
    assert count("--limit", "1") == 1
    assert count("--limit", "0") == 0


def test_cli_candidates_json_readonly_no_tool_notes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"
    _run(capsys, "tool-activity", "add", "--task-kind", "large-repo-forensics",
         "--tool", "parallel-agents", "--workflow", "unit-card-specialist-fanout",
         "--summary", "did X.", "--memory-dir", str(mem))
    before = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    code, out = _run(capsys, "tool-notes", "candidates", "--json",
                     "--task-kind", "large-repo-forensics", "--memory-dir", str(mem))
    assert code == 0
    d = json.loads(out)
    assert set(d) == {"schema_version", "advisory", "candidates"}
    assert len(d["candidates"]) == 1
    assert set(d["candidates"][0]) == _CANDIDATE_KEYS
    assert d["candidates"][0]["lesson"] == "did X."
    after = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    assert before == after  # read-only
    assert not (mem / "tool_notes.jsonl").exists()  # candidates never creates Tool Notes


def test_candidate_manual_save_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # record activity -> read candidate -> MANUALLY save as tool note -> suggest finds it
    mem = tmp_path / ".chimera-memory"
    _run(capsys, "tool-activity", "add", "--task-kind", "large-repo-forensics",
         "--tool", "parallel-agents", "--workflow", "unit-card-specialist-fanout",
         "--summary", "Use coverage manifests first.", "--memory-dir", str(mem))
    _, out = _run(capsys, "tool-notes", "candidates", "--json",
                  "--task-kind", "large-repo-forensics", "--memory-dir", str(mem))
    cand = json.loads(out)["candidates"][0]
    code, _ = _run(capsys, "tool-notes", "add", "--task-kind", cand["task_kind"],
                   "--tool", cand["tool_name"], "--workflow", cand["workflow_name"],
                   "--lesson", cand["lesson"], "--memory-dir", str(mem))
    assert code == 0
    _, out = _run(capsys, "tool-notes", "suggest", "--json",
                  "--task-kind", "large-repo-forensics", "--memory-dir", str(mem))
    suggestions = json.loads(out)["suggestions"]
    assert any(s["lesson"] == "Use coverage manifests first." for s in suggestions)


def test_no_forbidden_phrases_activity_candidates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"
    _run(capsys, "tool-activity", "add", "--task-kind", "k", "--tool", "t",
         "--summary", "did a thing", "--memory-dir", str(mem))
    blob = ""
    for argv in (("tool-activity", "list", "--json"), ("tool-notes", "candidates", "--json")):
        _, out = _run(capsys, *argv, "--memory-dir", str(mem))
        blob += out
    for argv in (("tool-activity", "--help"), ("tool-activity", "add", "--help"),
                 ("tool-notes", "candidates", "--help")):
        _, out = _run(capsys, *argv)
        blob += out
    low = blob.lower()
    for phrase in _FORBIDDEN:
        assert phrase not in low, f"overclaim phrase leaked: {phrase!r}"
