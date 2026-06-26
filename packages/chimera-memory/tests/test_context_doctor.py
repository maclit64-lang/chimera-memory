"""Tests for the Agent Context Doctor v0 (advisory local context-hygiene report)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from chimera_memory.cli import main
from chimera_memory.context_doctor import (
    FINDING_KINDS,
    build_context_doctor,
    render_context_doctor_markdown,
)
from chimera_memory.storage import MemoryStore
from chimera_memory.work_brief import add_work_brief, build_work_brief
from chimera_memory.work_session import (
    append_session_event,
    build_session_event,
    make_session_id,
)

_FORBIDDEN_SUB = (
    "safe to merge", "production ready", "production-ready", "certified", "approved",
    "guaranteed", "proves correctness", "proves safety", "trusted", "proof-carrying",
    "proof", "optimal", "guaranteed faster",
)
_FORBIDDEN_WORDS = ("healthy", "unhealthy", "pass", "fail", "ready", "not ready")
_TOP_KEYS = {
    "schema_version", "artifact", "advisory", "generated_at", "filters", "summary",
    "findings", "suggested_review_targets",
}
_SUMMARY_KEYS = {
    "session_count", "brief_count", "finding_count", "open_session_count",
    "blocked_session_count", "carryover_count",
}
_FILTER_KEYS = {"status", "tag", "limit_findings"}


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


def _assert_no_forbidden(text: str) -> None:
    low = text.lower()
    for phrase in _FORBIDDEN_SUB:
        assert phrase not in low, f"overclaim phrase leaked: {phrase!r}"
    for word in _FORBIDDEN_WORDS:
        assert not re.search(r"\b" + re.escape(word) + r"\b", low), f"forbidden word: {word!r}"


def _mk_session(
    store: MemoryStore, seq: int, *, status: str = "open", thread_dir: str | None = None,
    kickoff_dir: str | None = None, snapshot: bool = False, check: bool = False,
    done: bool = False, carry: bool = False, tag: str = "v0.29", with_brief: bool = True,
) -> str:
    brief_id: str | None = None
    if with_brief:
        b = build_work_brief(title=f"S{seq}", objective="O", task_kind="memory-feature",
                             tags=(tag,))
        add_work_brief(store, b)
        brief_id = b.brief_id
    base = f"2026-06-25T10:0{seq}"
    sid = make_session_id(created_at=base + ":00+00:00", brief_id=brief_id or "")

    def ap(**kw: object) -> None:
        append_session_event(store, build_session_event(session_id=sid, **kw))  # type: ignore[arg-type]

    ap(event_kind="started", brief_id=brief_id, thread_dir=thread_dir, kickoff_pack_dir=kickoff_dir,
       tags=(tag,), created_at=base + ":00+00:00")
    if snapshot:
        ap(event_kind="snapshot_attached", thread_dir=thread_dir, snapshot_id=f"snap_{seq}",
           created_at=base + ":01+00:00")
    if check:
        ap(event_kind="check_reported", check="uv run pytest", created_at=base + ":02+00:00")
    if done:
        ap(event_kind="done_observed", done_criterion="green", status="reported",
           created_at=base + ":03+00:00")
    if carry:
        ap(event_kind="carryover_noted", carryover="note", tags=(tag,),
           created_at=base + ":04+00:00")
    if status != "open":
        ap(event_kind="closed", status=status, created_at=base + ":05+00:00")
    return sid


def _kinds(doctor: dict[str, object]) -> set[str]:
    return {f["kind"] for f in doctor["findings"]}  # type: ignore[index,union-attr]


# --- schema / rendering ------------------------------------------------------

def test_doctor_schema(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    _mk_session(store, 1)
    d = build_context_doctor(store, generated_at="T")
    assert set(d) == _TOP_KEYS
    assert d["artifact"] == "chimera_context_doctor"
    assert set(d["summary"]) == _SUMMARY_KEYS  # type: ignore[arg-type]
    assert set(d["filters"]) == _FILTER_KEYS  # type: ignore[arg-type]
    assert all(f["kind"] in FINDING_KINDS for f in d["findings"])  # type: ignore[index,union-attr]


def test_doctor_markdown_sections(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    _mk_session(store, 1)
    md = render_context_doctor_markdown(build_context_doctor(store, generated_at="T"))
    for h in ("# Chimera Context Doctor", "## Summary", "## Findings",
              "## Suggested review targets"):
        assert h in md, h


# --- each finding kind -------------------------------------------------------

def test_open_session_without_closeout(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    _mk_session(store, 1, status="open", snapshot=True, check=False)
    assert "open_session_without_closeout" in _kinds(build_context_doctor(store, generated_at="T"))


def test_blocked_session_with_carryover(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    _mk_session(store, 1, status="blocked", carry=True)
    assert "blocked_session_with_carryover" in _kinds(build_context_doctor(store, generated_at="T"))


def test_session_without_snapshots(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    _mk_session(store, 1, snapshot=False)
    assert "session_without_snapshots" in _kinds(build_context_doctor(store, generated_at="T"))


def test_session_without_reported_checks(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    _mk_session(store, 1, check=False)
    assert "session_without_reported_checks" in _kinds(build_context_doctor(store, generated_at="T"))


def test_brief_without_session(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    b = build_work_brief(title="Orphan", objective="O", task_kind="memory-feature", tags=("v0.29",))
    add_work_brief(store, b)
    d = build_context_doctor(store, generated_at="T")
    orphan = [f for f in d["findings"] if f["kind"] == "brief_without_session"]  # type: ignore[index,union-attr]
    assert orphan and orphan[0]["brief_id"] == b.brief_id


def test_missing_thread_dir(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    _mk_session(store, 1, thread_dir=str(tmp_path / "nope-thread"))
    assert "missing_thread_dir" in _kinds(build_context_doctor(store, generated_at="T"))


def test_missing_kickoff_pack_dir(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    _mk_session(store, 1, kickoff_dir=str(tmp_path / "nope-kickoff"))
    assert "missing_kickoff_pack_dir" in _kinds(build_context_doctor(store, generated_at="T"))


def test_existing_thread_dir_no_finding(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    real = tmp_path / "real-thread"
    real.mkdir()
    _mk_session(store, 1, thread_dir=str(real), snapshot=True, check=True)
    assert "missing_thread_dir" not in _kinds(build_context_doctor(store, generated_at="T"))


def test_closeout_without_carryover_review(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    _mk_session(store, 1, status="closed", done=True, carry=False)
    assert "closeout_without_carryover_review" in _kinds(
        build_context_doctor(store, generated_at="T"))


# --- filters / limits / determinism ------------------------------------------

def test_status_filter_suppresses_brief_findings(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    _mk_session(store, 1, status="open")
    b = build_work_brief(title="Orphan", objective="O", task_kind="memory-feature", tags=("v0.29",))
    add_work_brief(store, b)
    d = build_context_doctor(store, generated_at="T", status="open")
    assert d["summary"]["session_count"] == 1  # type: ignore[index]
    assert "brief_without_session" not in _kinds(d)


def test_tag_filter(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    _mk_session(store, 1, tag="v0.29")
    _mk_session(store, 2, tag="other")
    d = build_context_doctor(store, generated_at="T", tag="v0.29")
    assert d["summary"]["session_count"] == 1  # type: ignore[index]


def test_limit_findings_after_full_count(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    _mk_session(store, 1)  # one open session yields multiple findings
    full = build_context_doctor(store, generated_at="T")
    total = full["summary"]["finding_count"]  # type: ignore[index]
    assert total >= 2
    limited = build_context_doctor(store, generated_at="T", limit_findings=1)
    assert len(limited["findings"]) == 1  # type: ignore[arg-type]
    assert limited["summary"]["finding_count"] == total  # type: ignore[index]


def test_suggested_review_targets_deterministic(tmp_path: Path) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    _mk_session(store, 1, status="open", thread_dir=str(tmp_path / "nope"))
    a = build_context_doctor(store, generated_at="T")["suggested_review_targets"]
    b = build_context_doctor(store, generated_at="T")["suggested_review_targets"]
    assert a == b
    assert len(a) == len(set(a))  # type: ignore[arg-type]


def test_empty_missing_store_no_creation(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    store = MemoryStore.from_paths(root=root)
    d = build_context_doctor(store, generated_at="T")
    assert d["summary"]["finding_count"] == 0  # type: ignore[index]
    assert not (root / ".chimera-memory").exists()


# --- CLI ---------------------------------------------------------------------

def test_cli_doctor_json_and_markdown(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    _mk_session(store, 1)
    mem = tmp_path / ".chimera-memory"
    code, out = _run(capsys, "context-doctor", "--json", "--memory-dir", str(mem))
    assert code == 0 and set(json.loads(out)) == _TOP_KEYS
    code, out = _run(capsys, "context-doctor", "--memory-dir", str(mem))
    assert "# Chimera Context Doctor" in out and "## Findings" in out


def test_cli_doctor_read_only_store_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    _mk_session(store, 1)
    mem = tmp_path / ".chimera-memory"
    before = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    _run(capsys, "context-doctor", "--json", "--memory-dir", str(mem))
    _run(capsys, "context-doctor", "--memory-dir", str(mem))
    after = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    assert before == after


def test_cli_doctor_missing_store_no_creation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mem = tmp_path / ".chimera-memory"
    code, out = _run(capsys, "context-doctor", "--json", "--memory-dir", str(mem))
    assert code == 0 and json.loads(out)["summary"]["finding_count"] == 0
    assert not mem.exists()


def test_cli_doctor_output_writes_only_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    _mk_session(store, 1)
    mem = tmp_path / ".chimera-memory"
    out_file = tmp_path / "CONTEXT_DOCTOR.md"
    before = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    code, _ = _run(capsys, "context-doctor", "--output", str(out_file), "--memory-dir", str(mem))
    assert code == 0 and out_file.exists()
    assert "# Chimera Context Doctor" in out_file.read_text(encoding="utf-8")
    after = {p.name: p.read_bytes() for p in sorted(mem.iterdir()) if p.is_file()}
    assert before == after


def test_cli_doctor_bundle_files_and_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import hashlib
    store = MemoryStore.from_paths(root=tmp_path)
    _mk_session(store, 1)
    mem = tmp_path / ".chimera-memory"
    out = tmp_path / "doctor-pack"
    code, _ = _run(capsys, "context-doctor", "bundle", "--output-dir", str(out),
                   "--memory-dir", str(mem))
    assert code == 0
    names = sorted(p.name for p in out.iterdir())
    assert names == ["CONTEXT_DOCTOR.md", "README.md", "context-doctor.json", "manifest.json"]
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifact"] == "chimera_context_doctor_bundle"
    for entry in manifest["files"]:
        data = (out / entry["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        assert len(data) == entry["bytes"]
        assert entry["path"] != "manifest.json"


def test_cli_doctor_bundle_refuses_non_empty_without_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    _mk_session(store, 1)
    mem = tmp_path / ".chimera-memory"
    out = tmp_path / "pack"
    assert _run(capsys, "context-doctor", "bundle", "--output-dir", str(out),
                "--memory-dir", str(mem))[0] == 0
    assert _run(capsys, "context-doctor", "bundle", "--output-dir", str(out),
                "--memory-dir", str(mem))[0] == 2
    assert _run(capsys, "context-doctor", "bundle", "--output-dir", str(out), "--force",
                "--memory-dir", str(mem))[0] == 0


def test_no_forbidden_phrases(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = MemoryStore.from_paths(root=tmp_path)
    _mk_session(store, 1, status="blocked", thread_dir=str(tmp_path / "nope"), carry=True)
    mem = tmp_path / ".chimera-memory"
    blob = ""
    _, out = _run(capsys, "context-doctor", "--memory-dir", str(mem))
    blob += out
    _, out = _run(capsys, "context-doctor", "--json", "--memory-dir", str(mem))
    blob += out
    for argv in (("context-doctor", "--help"), ("context-doctor", "bundle", "--help")):
        _, out = _run(capsys, *argv)
        blob += out
    blob += (Path(__file__).resolve().parents[3] / "docs" / "context-doctor.md").read_text(
        encoding="utf-8")
    _assert_no_forbidden(blob)
