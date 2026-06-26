"""Tests for the Session Review Rollup v0 (advisory multi-session review board)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from chimera_memory.cli import main
from chimera_memory.session_rollup import build_session_rollup, render_session_rollup_markdown
from chimera_memory.storage import MemoryStore
from chimera_memory.work_brief import add_work_brief, build_work_brief
from chimera_memory.work_session import (
    append_session_event,
    build_session_event,
    make_session_id,
)

_FORBIDDEN = (
    "safe to merge", "production ready", "production-ready", "certified",
    "approved", "guaranteed", "proves correctness", "proves safety",
    "trusted", "proof-carrying", "proof", "optimal", "guaranteed faster",
)
_TOP_KEYS = {
    "schema_version", "artifact", "advisory", "generated_at", "filters", "summary",
    "sessions", "open_sessions", "blocked_sessions", "recent_closeouts",
    "reported_checks", "done_observations", "carryover", "suggested_review_targets",
    "recent_harness_runs", "recent_consequence_observations",
}
_SUMMARY_KEYS = {
    "session_count", "open_count", "blocked_count", "closed_count", "reported_check_count",
    "done_observation_count", "carryover_count", "attached_snapshot_count",
    "attached_artifact_count", "harness_run_count", "executed_run_count", "recorded_run_count",
    "consequence_observation_count",
}
_FILTER_KEYS = {"status", "tag", "limit_sessions", "limit_carryover", "carryover_tag"}


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


def _seed(root: Path) -> None:
    """Open session (+check), blocked session (+carryover/done), closed session."""
    store = MemoryStore.from_paths(root=root)

    def mk(title: str, tag: str, seq: str, status: str, **kw: str) -> str:
        brief = build_work_brief(title=title, objective="O", task_kind="memory-feature",
                                 tags=(tag,))
        add_work_brief(store, brief)
        ts = f"2026-06-25T10:00:0{seq}+00:00"
        sid = make_session_id(created_at=ts, brief_id=brief.brief_id)
        append_session_event(store, build_session_event(
            session_id=sid, event_kind="started", brief_id=brief.brief_id, tags=(tag,),
            created_at=ts))
        if kw.get("check"):
            append_session_event(store, build_session_event(
                session_id=sid, event_kind="check_reported", check=kw["check"],
                created_at=f"2026-06-25T10:01:0{seq}+00:00"))
        if kw.get("done"):
            append_session_event(store, build_session_event(
                session_id=sid, event_kind="done_observed", done_criterion=kw["done"],
                status="reported", created_at=f"2026-06-25T10:02:0{seq}+00:00"))
        if kw.get("carry"):
            append_session_event(store, build_session_event(
                session_id=sid, event_kind="carryover_noted", carryover=kw["carry"],
                tags=("release-blocker",), created_at=f"2026-06-25T10:03:0{seq}+00:00"))
        if status != "open":
            append_session_event(store, build_session_event(
                session_id=sid, event_kind="closed", status=status,
                created_at=f"2026-06-25T10:04:0{seq}+00:00"))
        return sid

    mk("Open work", "v0.29", "1", "open", check="uv run pytest")
    mk("Blocked work", "v0.29", "2", "blocked", carry="PyPI token missing.", done="Suite green.")
    mk("Closed work", "other", "3", "closed")


# --- module ------------------------------------------------------------------

def test_rollup_schema(tmp_path: Path) -> None:
    _seed(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    r = build_session_rollup(store, generated_at="T")
    assert set(r) == _TOP_KEYS
    assert r["artifact"] == "chimera_work_session_rollup"
    assert set(r["summary"]) == _SUMMARY_KEYS
    assert set(r["filters"]) == _FILTER_KEYS


def test_rollup_counts(tmp_path: Path) -> None:
    _seed(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    s = build_session_rollup(store, generated_at="T")["summary"]
    assert s["session_count"] == 3
    assert s["open_count"] == 1
    assert s["blocked_count"] == 1
    assert s["closed_count"] == 1
    assert s["reported_check_count"] == 1
    assert s["done_observation_count"] == 1
    assert s["carryover_count"] == 1


def test_rollup_status_filter(tmp_path: Path) -> None:
    _seed(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    r = build_session_rollup(store, generated_at="T", status="blocked")
    assert r["summary"]["session_count"] == 1
    assert r["summary"]["blocked_count"] == 1
    assert r["summary"]["open_count"] == 0


def test_rollup_tag_filter(tmp_path: Path) -> None:
    _seed(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    r = build_session_rollup(store, generated_at="T", tag="v0.29")
    assert r["summary"]["session_count"] == 2


def test_rollup_limit_sessions_after_filter(tmp_path: Path) -> None:
    _seed(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    r = build_session_rollup(store, generated_at="T", tag="v0.29", limit_sessions=1)
    assert r["summary"]["session_count"] == 1


def test_rollup_limit_carryover_truncates_list_only(tmp_path: Path) -> None:
    _seed(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    r = build_session_rollup(store, generated_at="T", limit_carryover=0)
    assert len(r["carryover"]) == 0
    assert r["summary"]["carryover_count"] == 1  # count reflects total, not the truncated list


def test_rollup_carryover_verbatim_and_context(tmp_path: Path) -> None:
    _seed(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    r = build_session_rollup(store, generated_at="T", status="blocked")
    item = r["carryover"][0]
    assert item["carryover"] == "PyPI token missing."
    assert item["session_status"] == "blocked"
    assert item["tags"] == ["release-blocker"]
    assert item["source"] == "cli"
    assert item["brief_id"]


def test_rollup_carryover_tag_filter(tmp_path: Path) -> None:
    _seed(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    assert build_session_rollup(
        store, generated_at="T", carryover_tag="release-blocker"
    )["summary"]["carryover_count"] == 1
    assert build_session_rollup(
        store, generated_at="T", carryover_tag="nope"
    )["summary"]["carryover_count"] == 0


def test_rollup_review_targets_deterministic(tmp_path: Path) -> None:
    _seed(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    a = build_session_rollup(store, generated_at="T")["suggested_review_targets"]
    b = build_session_rollup(store, generated_at="T")["suggested_review_targets"]
    assert a == b
    assert any(t.startswith("Open session:") for t in a)
    assert any(t.startswith("Blocked session:") for t in a)
    assert len(a) == len(set(a))  # exact-deduplicated


def test_rollup_markdown_sections(tmp_path: Path) -> None:
    _seed(tmp_path)
    store = MemoryStore.from_paths(root=tmp_path)
    md = render_session_rollup_markdown(build_session_rollup(store, generated_at="T"))
    for h in ("# Chimera Work Session Rollup", "## Summary", "## Open sessions",
              "## Blocked sessions", "## Recent closeouts", "## Reported checks",
              "## Done observations", "## Carryover inbox", "## Suggested review targets"):
        assert h in md, h


def test_rollup_empty_missing_store_no_creation(tmp_path: Path) -> None:
    root = tmp_path / "ws"  # nothing created yet
    store = MemoryStore.from_paths(root=root)
    r = build_session_rollup(store, generated_at="T")
    assert r["summary"]["session_count"] == 0
    assert not (root / ".chimera-memory").exists()


# --- CLI ---------------------------------------------------------------------

def test_cli_rollup_json_and_markdown(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed(tmp_path)
    mem = tmp_path / ".chimera-memory"
    code, out = _run(capsys, "work-session", "rollup", "--json", "--memory-dir", str(mem))
    assert code == 0
    assert set(json.loads(out)) == _TOP_KEYS
    code, out = _run(capsys, "work-session", "rollup", "--memory-dir", str(mem))
    assert "# Chimera Work Session Rollup" in out and "## Carryover inbox" in out


def test_cli_rollup_read_only_store_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(tmp_path)
    mem = tmp_path / ".chimera-memory"
    before = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    _run(capsys, "work-session", "rollup", "--json", "--memory-dir", str(mem))
    _run(capsys, "work-session", "rollup", "--memory-dir", str(mem))
    after = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    assert before == after


def test_cli_rollup_missing_store_no_creation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"  # never created
    code, out = _run(capsys, "work-session", "rollup", "--json", "--memory-dir", str(mem))
    assert code == 0
    assert json.loads(out)["summary"]["session_count"] == 0
    assert not mem.exists()


def test_cli_rollup_output_writes_only_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(tmp_path)
    mem = tmp_path / ".chimera-memory"
    out_file = tmp_path / "SESSION_ROLLUP.md"
    before = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    code, _ = _run(capsys, "work-session", "rollup", "--output", str(out_file),
                   "--memory-dir", str(mem))
    assert code == 0 and out_file.exists()
    assert "# Chimera Work Session Rollup" in out_file.read_text(encoding="utf-8")
    after = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    assert before == after


def test_cli_rollup_bundle_files_and_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import hashlib
    _seed(tmp_path)
    mem = tmp_path / ".chimera-memory"
    out = tmp_path / "rollup-pack"
    code, _ = _run(capsys, "work-session", "rollup-bundle", "--output-dir", str(out),
                   "--memory-dir", str(mem))
    assert code == 0
    names = sorted(p.name for p in out.iterdir())
    assert names == ["README.md", "SESSION_ROLLUP.md", "manifest.json", "session-rollup.json"]
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifact"] == "chimera_work_session_rollup_bundle"
    for entry in manifest["files"]:
        data = (out / entry["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        assert len(data) == entry["bytes"]
        assert entry["path"] != "manifest.json"


def test_cli_rollup_bundle_refuses_non_empty_without_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(tmp_path)
    mem = tmp_path / ".chimera-memory"
    out = tmp_path / "pack"
    assert _run(capsys, "work-session", "rollup-bundle", "--output-dir", str(out),
                "--memory-dir", str(mem))[0] == 0
    assert _run(capsys, "work-session", "rollup-bundle", "--output-dir", str(out),
                "--memory-dir", str(mem))[0] == 2
    assert _run(capsys, "work-session", "rollup-bundle", "--output-dir", str(out), "--force",
                "--memory-dir", str(mem))[0] == 0


def test_no_forbidden_phrases(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed(tmp_path)
    mem = tmp_path / ".chimera-memory"
    blob = ""
    _, out = _run(capsys, "work-session", "rollup", "--memory-dir", str(mem))
    blob += out
    _, out = _run(capsys, "work-session", "rollup", "--json", "--memory-dir", str(mem))
    blob += out
    for argv in (("work-session", "rollup", "--help"),
                 ("work-session", "rollup-bundle", "--help")):
        _, out = _run(capsys, *argv)
        blob += out
    blob += (Path(__file__).resolve().parents[3] / "docs" / "work-session.md").read_text(
        encoding="utf-8")
    low = blob.lower()
    for phrase in _FORBIDDEN:
        assert phrase not in low, f"overclaim phrase leaked: {phrase!r}"
