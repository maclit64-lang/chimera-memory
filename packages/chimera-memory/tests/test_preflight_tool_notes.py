"""Stage 4: preflight tool-note advisory tests.

The advisory is quiet by default and surfaced only on an exact-match filter.
`preflight` reads the store from the current working directory, so these tests
chdir into a seeded tmp workspace. The forbidden-phrase check is scoped to OUR
advisory (the rest of preflight legitimately disclaims "statistical proof").
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from chimera_memory.cli import main
from chimera_memory.storage import MemoryStore
from chimera_memory.tool_notes import add_tool_note, build_tool_note

_FORBIDDEN = (
    "safe to merge", "production ready", "production-ready", "certified",
    "approved", "guaranteed", "proves correctness", "proves safety",
    "trusted", "proof-carrying", "proof", "optimal", "guaranteed faster",
)


def _seed(root: Path) -> None:
    store = MemoryStore.from_paths(root=root)
    add_tool_note(store, build_tool_note(
        task_kind="large-repo-forensics", tool_name="parallel-agents",
        workflow_name="unit-card-specialist-fanout",
        lesson="Use coverage manifests and Unit Cards before cross-cutting synthesis.",
        evidence="2189/2189 files read; 31 Unit Cards; 31 manifests; 7 agents.",
        caveat="High cost/time; monitor MCP failures.",
        tags=("repo-forensics", "orchestration"),
    ))


def _run(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
         root: Path, *argv: str) -> tuple[int, str]:
    monkeypatch.chdir(root)
    code = main(list(argv))
    return code, capsys.readouterr().out


def test_preflight_task_kind_includes_tool_lesson(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path)
    code, out = _run(capsys, monkeypatch, tmp_path, "preflight", "--task-kind",
                     "large-repo-forensics")
    assert code == 0
    assert "## Tool lessons" in out
    assert "parallel-agents / unit-card-specialist-fanout" in out
    assert "Lesson:" in out
    assert "Caveat:" in out


def test_preflight_tag_includes_tool_lesson(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path)
    _, out = _run(capsys, monkeypatch, tmp_path, "preflight", "--tag", "repo-forensics")
    assert "## Tool lessons" in out


def test_preflight_no_matching_note_is_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path)
    _, out = _run(capsys, monkeypatch, tmp_path, "preflight", "--task-kind", "nope")
    assert "## Tool lessons" not in out


def test_preflight_without_filters_is_quiet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path)
    _, out = _run(capsys, monkeypatch, tmp_path, "preflight")
    assert "## Tool lessons" not in out


def test_preflight_json_has_additive_tool_note_advisory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path)
    _, out = _run(capsys, monkeypatch, tmp_path, "preflight", "--json", "--task-kind",
                  "large-repo-forensics")
    d = json.loads(out)
    assert "tool_note_advisory" in d
    adv = d["tool_note_advisory"]
    assert adv["schema_version"] == 1
    assert set(adv["filters"]) == {"task_kind", "tag", "tool_name", "workflow_name"}
    assert adv["filters"]["task_kind"] == "large-repo-forensics"
    assert len(adv["tool_notes"]) == 1
    # existing preflight keys remain (additive change only)
    assert "schema_version" in d
    assert "recommended_checks" in d
    assert "preflight_intelligence_note" in d


def test_preflight_json_quiet_when_no_filter(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path)
    _, out = _run(capsys, monkeypatch, tmp_path, "preflight", "--json")
    adv = json.loads(out)["tool_note_advisory"]
    assert adv["tool_notes"] == []
    assert adv["filters"] == {
        "task_kind": None, "tag": None, "tool_name": None, "workflow_name": None,
    }


def test_preflight_advisory_is_read_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path)
    mem = tmp_path / ".chimera-memory"
    before = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    _run(capsys, monkeypatch, tmp_path, "preflight", "--task-kind", "large-repo-forensics")
    _run(capsys, monkeypatch, tmp_path, "preflight", "--json", "--tag", "repo-forensics")
    after = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    assert before == after


def test_preflight_advisory_no_forbidden_phrases(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path)
    _, text = _run(capsys, monkeypatch, tmp_path, "preflight", "--task-kind",
                   "large-repo-forensics")
    # Scope to OUR advisory section; the rest of preflight legitimately negates "proof".
    section = text.split("## Tool lessons", 1)[1]
    _, jtext = _run(capsys, monkeypatch, tmp_path, "preflight", "--json", "--task-kind",
                    "large-repo-forensics")
    advisory_json = json.dumps(json.loads(jtext)["tool_note_advisory"])
    _, help_text = _run(capsys, monkeypatch, tmp_path, "preflight", "--help")
    blob = (section + advisory_json + help_text).lower()
    for phrase in _FORBIDDEN:
        assert phrase not in blob, f"overclaim phrase leaked: {phrase!r}"


# --- candidate advisory (quiet by default) ----------------------------------

def _seed_activity(root: Path) -> None:
    from chimera_memory.tool_activity import add_tool_activity, build_tool_activity
    store = MemoryStore.from_paths(root=root)
    add_tool_activity(store, build_tool_activity(
        task_kind="large-repo-forensics", tool_name="parallel-agents",
        workflow_name="unit-card-specialist-fanout",
        summary="did big synthesis", evidence="2189 files", caveat="costly",
        tags=("repo-forensics",)))


def test_preflight_candidate_present_with_filter(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_activity(tmp_path)
    _, out = _run(capsys, monkeypatch, tmp_path, "preflight", "--json",
                  "--candidate-task-kind", "large-repo-forensics")
    adv = json.loads(out)["candidate_tool_lesson_advisory"]
    assert adv["schema_version"] == 1
    assert set(adv["filters"]) == {"task_kind", "tag"}
    assert len(adv["candidates"]) == 1
    assert adv["candidates"][0]["lesson"] == "did big synthesis"


def test_preflight_candidate_quiet_without_filter(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_activity(tmp_path)
    _, out = _run(capsys, monkeypatch, tmp_path, "preflight", "--json")
    adv = json.loads(out)["candidate_tool_lesson_advisory"]
    assert adv["candidates"] == []
    assert adv["filters"] == {"task_kind": None, "tag": None}


def test_preflight_candidate_non_matching_filter_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_activity(tmp_path)
    _, out = _run(capsys, monkeypatch, tmp_path, "preflight", "--json",
                  "--candidate-tag", "nope")
    assert json.loads(out)["candidate_tool_lesson_advisory"]["candidates"] == []


def test_preflight_candidate_text_section_only_with_filter(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_activity(tmp_path)
    _, quiet = _run(capsys, monkeypatch, tmp_path, "preflight")
    assert "Candidate tool lessons" not in quiet
    _, shown = _run(capsys, monkeypatch, tmp_path, "preflight",
                    "--candidate-task-kind", "large-repo-forensics")
    assert "Candidate tool lessons" in shown
    assert "did big synthesis" in shown


def test_preflight_candidate_bundle_keys_untouched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_activity(tmp_path)
    _, out = _run(capsys, monkeypatch, tmp_path, "preflight", "--json",
                  "--candidate-task-kind", "large-repo-forensics")
    d = json.loads(out)
    # candidate advisory is additive; tool_note_advisory and core keys remain
    assert "candidate_tool_lesson_advisory" in d
    assert "tool_note_advisory" in d
    assert "recommended_checks" in d


def test_preflight_candidate_read_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_activity(tmp_path)
    mem = tmp_path / ".chimera-memory"
    before = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    _run(capsys, monkeypatch, tmp_path, "preflight", "--candidate-task-kind",
         "large-repo-forensics")
    _run(capsys, monkeypatch, tmp_path, "preflight", "--json", "--candidate-tag",
         "repo-forensics")
    after = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    assert before == after
    assert not (mem / "tool_notes.jsonl").exists()
