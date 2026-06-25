"""Tests for the Agent Work Brief v0 (local task brief / kickoff contract)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from chimera_memory.cli import main
from chimera_memory.storage import MemoryStore
from chimera_memory.work_brief import (
    add_work_brief,
    build_work_brief,
    find_work_brief,
    read_work_briefs,
)

_FORBIDDEN = (
    "safe to merge", "production ready", "production-ready", "certified",
    "approved", "guaranteed", "proves correctness", "proves safety",
    "trusted", "proof-carrying", "proof", "optimal", "guaranteed faster",
)
_BRIEF_KEYS = {
    "schema_version", "brief_id", "created_at", "title", "objective", "task_kind",
    "scope_paths", "out_of_scope_paths", "constraints", "checks", "done_criteria",
    "context_refs", "tags", "source",
}


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


def _add(capsys: pytest.CaptureFixture[str], mem: Path, *extra: str) -> str:
    code, out = _run(capsys, "work-brief", "add", "--title", "Implement X",
                     "--objective", "Do the thing.", "--memory-dir", str(mem), *extra)
    assert code == 0
    return out.strip()


# --- module -----------------------------------------------------------------

def test_add_writes_only_work_briefs_file(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    add_work_brief(store, build_work_brief(title="T", objective="O"))
    files = sorted(p.name for p in (tmp_path / ".chimera-memory").iterdir() if p.is_file())
    assert files == ["work_briefs.jsonl"]
    briefs = read_work_briefs(store)
    assert len(briefs) == 1 and briefs[0].title == "T"
    assert briefs[0].brief_id.startswith("brief_")


def test_required_title_objective(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        build_work_brief(title="", objective="O")
    with pytest.raises(ValueError):
        build_work_brief(title="T", objective="")


def test_read_round_trips_list_fields(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    add_work_brief(store, build_work_brief(
        title="T", objective="O", scope_paths=("a", "b"), constraints=("c1",),
        checks=("pytest",), done_criteria=("green",), tags=("v0.29",)))
    b = read_work_briefs(store)[0]
    assert b.scope_paths == ("a", "b")
    assert b.checks == ("pytest",)
    assert set(b.to_dict()) == _BRIEF_KEYS


# --- CLI --------------------------------------------------------------------

def test_cli_add_requires_title_and_objective(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"
    code, _ = _run(capsys, "work-brief", "add", "--title", "only title",
                   "--memory-dir", str(mem))
    assert code == 2
    assert not mem.exists()  # invalid input writes nothing


def test_cli_list_text_and_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = tmp_path / ".chimera-memory"
    bid = _add(capsys, mem, "--task-kind", "memory-feature", "--tag", "v0.29")
    code, out = _run(capsys, "work-brief", "list", "--memory-dir", str(mem))
    assert code == 0
    assert bid in out
    code, out = _run(capsys, "work-brief", "list", "--json", "--memory-dir", str(mem))
    d = json.loads(out)
    assert d["schema_version"] == 1
    assert len(d["work_briefs"]) == 1
    assert set(d["work_briefs"][0]) == _BRIEF_KEYS


def test_cli_list_filters_and_limit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = tmp_path / ".chimera-memory"
    _add(capsys, mem, "--task-kind", "memory-feature", "--tag", "v0.29")
    _run(capsys, "work-brief", "add", "--title", "Other", "--objective", "y",
         "--task-kind", "quick-fix", "--tag", "small", "--memory-dir", str(mem))

    def count(*args: str) -> int:
        _, out = _run(capsys, "work-brief", "list", "--json", *args, "--memory-dir", str(mem))
        return len(json.loads(out)["work_briefs"])

    assert count() == 2
    assert count("--task-kind", "memory-feature") == 1
    assert count("--tag", "small") == 1
    assert count("--task-kind", "memory-feature", "--tag", "small") == 0  # AND
    assert count("--limit", "1") == 1
    assert count("--limit", "0") == 0


def test_cli_show_found_missing_json_markdown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"
    bid = _add(capsys, mem, "--scope-path", "src", "--check", "pytest", "--done", "green")
    code, out = _run(capsys, "work-brief", "show", bid, "--json", "--memory-dir", str(mem))
    assert code == 0
    d = json.loads(out)
    assert d["found"] is True and d["work_brief"]["brief_id"] == bid
    code, out = _run(capsys, "work-brief", "show", "brief_nope", "--json", "--memory-dir", str(mem))
    assert json.loads(out) == {"schema_version": 1, "work_brief": None, "found": False}
    code, out = _run(capsys, "work-brief", "show", bid, "--markdown", "--memory-dir", str(mem))
    assert code == 0
    for header in ("# Chimera Agent Work Brief", "## Objective", "## Scope",
                   "## Checks to report", "## Done criteria"):
        assert header in out, header


def test_cli_list_show_read_only_no_store_creation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"  # never created
    code, out = _run(capsys, "work-brief", "list", "--json", "--memory-dir", str(mem))
    assert code == 0 and json.loads(out)["work_briefs"] == []
    code, out = _run(capsys, "work-brief", "show", "brief_x", "--json", "--memory-dir", str(mem))
    assert code == 0 and json.loads(out)["found"] is False
    assert not mem.exists()


def test_cli_add_then_list_show_is_read_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"
    _add(capsys, mem, "--tag", "v0.29")
    before = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    _run(capsys, "work-brief", "list", "--json", "--memory-dir", str(mem))
    _run(capsys, "work-brief", "list", "--memory-dir", str(mem))
    after = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    assert before == after


def test_no_forbidden_phrases(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = tmp_path / ".chimera-memory"
    bid = _add(capsys, mem, "--task-kind", "memory-feature", "--tag", "v0.29")
    blob = ""
    for argv in (("work-brief", "list"), ("work-brief", "list", "--json"),
                 ("work-brief", "show", bid), ("work-brief", "show", bid, "--json")):
        _, out = _run(capsys, *argv, "--memory-dir", str(mem))
        blob += out
    for argv in (("work-brief", "--help"), ("work-brief", "add", "--help"),
                 ("work-brief", "show", "--help")):
        _, out = _run(capsys, *argv)
        blob += out
    blob += (Path(__file__).resolve().parents[3] / "docs" / "work-brief.md").read_text(
        encoding="utf-8")
    low = blob.lower()
    for phrase in _FORBIDDEN:
        assert phrase not in low, f"overclaim phrase leaked: {phrase!r}"


def test_find_work_brief_module(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    b = build_work_brief(title="T", objective="O")
    add_work_brief(store, b)
    assert find_work_brief(store, b.brief_id).brief_id == b.brief_id  # type: ignore[union-attr]
    assert find_work_brief(store, "brief_missing") is None
