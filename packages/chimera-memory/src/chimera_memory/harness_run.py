"""Harness Lite v0 — a local run-observation ledger.

A Harness Run is an *observation* of a command / check / tool invocation: what was
run (or reported as run), where, when, the exit code if known, bounded and redacted
stdout/stderr previews, and how it attaches to a Work Session. Two modes:

- ``recorded``: the user/agent records a command that ran elsewhere (no execution).
- ``executed``: Chimera explicitly ran the command locally because ``harness run``
  was invoked — never automatic, never background.

Everything is a local observation. An exit code is recorded, never interpreted as a
verdict; statuses are neutral (``completed`` / ``interrupted`` / ``unknown``).
Reading the ledger writes nothing; only ``harness record`` / ``harness run`` append
to ``harness_runs.jsonl``.
"""
from __future__ import annotations

import hashlib
import shlex
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from chimera_memory.redaction import redact
from chimera_memory.storage import MemoryStore

SCHEMA_VERSION = 1
STORE_FILE = "harness_runs.jsonl"
MODES = frozenset({"recorded", "executed"})
STATUSES = frozenset({"completed", "interrupted", "unknown"})
DEFAULT_MAX_OUTPUT_BYTES = 4096


class HarnessError(Exception):
    """Raised for harness precondition failures (clean CLI errors)."""


def _strs(value: Any) -> tuple[str, ...]:
    return tuple(str(v) for v in value if isinstance(v, str)) if isinstance(value, list) else ()


def _opt(value: Any) -> str | None:
    return str(value) if isinstance(value, str) else None


def _opt_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


@dataclass(frozen=True)
class HarnessRun:
    schema_version: int
    run_id: str
    created_at: str
    started_at: str | None
    ended_at: str | None
    duration_ms: int | None
    mode: str
    command: str
    cwd: str | None
    exit_code: int | None
    status: str
    stdout_preview: str
    stderr_preview: str
    stdout_sha256: str | None
    stderr_sha256: str | None
    redaction_applied: bool
    output_truncated: bool
    artifact_refs: tuple[str, ...]
    work_session_id: str | None
    brief_id: str | None
    check_label: str | None
    note: str | None
    tags: tuple[str, ...]
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "mode": self.mode,
            "command": self.command,
            "cwd": self.cwd,
            "exit_code": self.exit_code,
            "status": self.status,
            "stdout_preview": self.stdout_preview,
            "stderr_preview": self.stderr_preview,
            "stdout_sha256": self.stdout_sha256,
            "stderr_sha256": self.stderr_sha256,
            "redaction_applied": self.redaction_applied,
            "output_truncated": self.output_truncated,
            "artifact_refs": list(self.artifact_refs),
            "work_session_id": self.work_session_id,
            "brief_id": self.brief_id,
            "check_label": self.check_label,
            "note": self.note,
            "tags": list(self.tags),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HarnessRun:
        mode = str(d.get("mode", "recorded"))
        status = str(d.get("status", "unknown"))
        return cls(
            schema_version=int(d.get("schema_version", SCHEMA_VERSION)),
            run_id=str(d.get("run_id", "")),
            created_at=str(d.get("created_at", "")),
            started_at=_opt(d.get("started_at")),
            ended_at=_opt(d.get("ended_at")),
            duration_ms=_opt_int(d.get("duration_ms")),
            mode=mode if mode in MODES else "recorded",
            command=str(d.get("command", "")),
            cwd=_opt(d.get("cwd")),
            exit_code=_opt_int(d.get("exit_code")),
            status=status if status in STATUSES else "unknown",
            stdout_preview=str(d.get("stdout_preview", "")),
            stderr_preview=str(d.get("stderr_preview", "")),
            stdout_sha256=_opt(d.get("stdout_sha256")),
            stderr_sha256=_opt(d.get("stderr_sha256")),
            redaction_applied=bool(d.get("redaction_applied", False)),
            output_truncated=bool(d.get("output_truncated", False)),
            artifact_refs=_strs(d.get("artifact_refs")),
            work_session_id=_opt(d.get("work_session_id")),
            brief_id=_opt(d.get("brief_id")),
            check_label=_opt(d.get("check_label")),
            note=_opt(d.get("note")),
            tags=_strs(d.get("tags")),
            source=str(d.get("source", "cli")),
        )


def make_run_id(*, created_at: str, command: str, mode: str) -> str:
    digest = hashlib.sha256("\x1f".join((created_at, command, mode)).encode()).hexdigest()[:16]
    return f"run_{digest}"


def _bounded_preview(data: bytes, max_output_bytes: int) -> tuple[str, str | None, bool]:
    """Return (redacted preview, sha256 of full bytes, truncated). Never stores full output."""
    sha = hashlib.sha256(data).hexdigest() if data else None
    truncated = len(data) > max_output_bytes
    preview = data[:max_output_bytes].decode("utf-8", errors="replace")
    return preview, sha, truncated


def _redact_pair(stdout: str, stderr: str) -> tuple[str, str, bool]:
    """Redact both previews; report whether redaction changed either."""
    r_out, r_err = redact(stdout), redact(stderr)
    applied = (r_out != stdout) or (r_err != stderr)
    return r_out, r_err, applied


def build_recorded_run(
    *,
    command: str,
    generated_at: str,
    cwd: str | None = None,
    exit_code: int | None = None,
    work_session_id: str | None = None,
    brief_id: str | None = None,
    check_label: str | None = None,
    note: str | None = None,
    stdout_preview: str | None = None,
    stderr_preview: str | None = None,
    artifact_refs: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    source: str = "cli",
) -> HarnessRun:
    """Build a ``recorded`` run (no execution). Provided previews are redacted."""
    r_out, r_err, applied = _redact_pair(stdout_preview or "", stderr_preview or "")
    return HarnessRun(
        schema_version=SCHEMA_VERSION,
        run_id=make_run_id(created_at=generated_at, command=command, mode="recorded"),
        created_at=generated_at,
        started_at=None,
        ended_at=None,
        duration_ms=None,
        mode="recorded",
        command=command,
        cwd=cwd,
        exit_code=exit_code,
        status="completed",
        stdout_preview=r_out,
        stderr_preview=r_err,
        stdout_sha256=None,
        stderr_sha256=None,
        redaction_applied=applied,
        output_truncated=False,
        artifact_refs=artifact_refs,
        work_session_id=work_session_id,
        brief_id=brief_id,
        check_label=check_label,
        note=note,
        tags=tags,
        source=source,
    )


def _execute(
    command: str, *, cwd: str | None, max_output_bytes: int, timeout: float | None, shell: bool
) -> dict[str, Any]:
    """Run a local command explicitly. Returns capture metadata. No verdict is derived."""
    started = datetime.now(UTC)
    t0 = time.monotonic()
    stdout_bytes, stderr_bytes = b"", b""
    exit_code: int | None = None
    status = "completed"
    try:
        args: Any = command if shell else shlex.split(command)
        proc = subprocess.run(  # noqa: S603 - explicit, user-invoked local run
            args, cwd=cwd or None, capture_output=True, timeout=timeout, shell=shell,
        )
        exit_code = proc.returncode
        stdout_bytes, stderr_bytes = proc.stdout or b"", proc.stderr or b""
    except subprocess.TimeoutExpired as exc:
        status = "interrupted"
        stdout_bytes = exc.stdout or b"" if isinstance(exc.stdout, bytes) else b""
        stderr_bytes = exc.stderr or b"" if isinstance(exc.stderr, bytes) else b""
    except (FileNotFoundError, OSError):
        status = "unknown"
    ended = datetime.now(UTC)
    duration_ms = int((time.monotonic() - t0) * 1000)
    out_preview, out_sha, out_trunc = _bounded_preview(stdout_bytes, max_output_bytes)
    err_preview, err_sha, err_trunc = _bounded_preview(stderr_bytes, max_output_bytes)
    r_out, r_err, applied = _redact_pair(out_preview, err_preview)
    return {
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "duration_ms": duration_ms,
        "exit_code": exit_code,
        "status": status,
        "stdout_preview": r_out,
        "stderr_preview": r_err,
        "stdout_sha256": out_sha,
        "stderr_sha256": err_sha,
        "redaction_applied": applied,
        "output_truncated": out_trunc or err_trunc,
    }


def build_executed_run(
    *,
    command: str,
    generated_at: str,
    cwd: str | None = None,
    work_session_id: str | None = None,
    brief_id: str | None = None,
    check_label: str | None = None,
    note: str | None = None,
    artifact_refs: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    source: str = "cli",
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    timeout: float | None = None,
    shell: bool = False,
) -> HarnessRun:
    """Explicitly run ``command`` locally and build an ``executed`` run observation."""
    cap = _execute(
        command, cwd=cwd, max_output_bytes=max_output_bytes, timeout=timeout, shell=shell
    )
    return HarnessRun(
        schema_version=SCHEMA_VERSION,
        run_id=make_run_id(created_at=generated_at, command=command, mode="executed"),
        created_at=generated_at,
        started_at=cap["started_at"],
        ended_at=cap["ended_at"],
        duration_ms=cap["duration_ms"],
        mode="executed",
        command=command,
        cwd=cwd,
        exit_code=cap["exit_code"],
        status=cap["status"],
        stdout_preview=cap["stdout_preview"],
        stderr_preview=cap["stderr_preview"],
        stdout_sha256=cap["stdout_sha256"],
        stderr_sha256=cap["stderr_sha256"],
        redaction_applied=cap["redaction_applied"],
        output_truncated=cap["output_truncated"],
        artifact_refs=artifact_refs,
        work_session_id=work_session_id,
        brief_id=brief_id,
        check_label=check_label,
        note=note,
        tags=tags,
        source=source,
    )


def append_harness_run(store: MemoryStore, run: HarnessRun) -> None:
    """Append one run to the ledger (the only write path). Creates the store if needed."""
    store.ensure()
    store.append_jsonl(STORE_FILE, run.to_dict())


def read_harness_runs(store: MemoryStore) -> list[HarnessRun]:
    """Read all runs (stored order). Read-only; never creates a store."""
    return [HarnessRun.from_dict(d) for d in store.read_jsonl(STORE_FILE)]


def runs_for_store(store: MemoryStore) -> list[HarnessRun]:
    return read_harness_runs(store)


def find_run(store: MemoryStore, run_id: str) -> HarnessRun | None:
    for run in read_harness_runs(store):
        if run.run_id == run_id:
            return run
    return None


def filter_runs(
    runs: list[HarnessRun],
    *,
    work_session_id: str | None = None,
    brief_id: str | None = None,
    tag: str | None = None,
) -> list[HarnessRun]:
    """Exact-match filter (AND). No fuzzy matching, no ranking."""
    return [
        r
        for r in runs
        if (work_session_id is None or r.work_session_id == work_session_id)
        and (brief_id is None or r.brief_id == brief_id)
        and (tag is None or tag in r.tags)
    ]


def compact_run(run: HarnessRun) -> dict[str, Any]:
    """Compact, output-free run reference for closeout / rollup / session surfaces."""
    return {
        "run_id": run.run_id,
        "created_at": run.created_at,
        "mode": run.mode,
        "command": run.command,
        "cwd": run.cwd,
        "exit_code": run.exit_code,
        "status": run.status,
        "check_label": run.check_label,
        "redaction_applied": run.redaction_applied,
        "output_truncated": run.output_truncated,
        "artifact_refs": list(run.artifact_refs),
    }


def _exit_phrase(exit_code: int | None) -> str:
    if exit_code is None:
        return "exit code unknown"
    return "exit code 0" if exit_code == 0 else f"nonzero exit code ({exit_code})"


def render_run_markdown(run: HarnessRun) -> str:
    """Render one run to advisory markdown. Presentation only; no verdict."""
    lines = [
        "# Chimera Harness Run",
        "",
        "Local run observation. An exit code is recorded, not interpreted as a verdict.",
        "",
        f"- run_id: {run.run_id}",
        f"- mode: {run.mode}",
        f"- command: {run.command}",
        f"- cwd: {run.cwd or '(unset)'}",
        f"- status: {run.status}",
        f"- {_exit_phrase(run.exit_code)}",
        f"- created_at: {run.created_at}",
        f"- duration_ms: {run.duration_ms if run.duration_ms is not None else '(unset)'}",
        f"- work_session_id: {run.work_session_id or '(none)'}",
        f"- brief_id: {run.brief_id or '(none)'}",
        f"- check_label: {run.check_label or '(none)'}",
        f"- redaction_applied: {run.redaction_applied}",
        f"- output_truncated: {run.output_truncated}",
        f"- stdout_sha256: {run.stdout_sha256 or '(none)'}",
        f"- stderr_sha256: {run.stderr_sha256 or '(none)'}",
    ]
    if run.artifact_refs:
        lines.append("- artifacts: " + ", ".join(run.artifact_refs))
    if run.note:
        lines.append(f"- note: {run.note}")
    lines.append("")
    lines.append("## stdout preview (bounded, redacted)")
    lines.append("```")
    lines.append(run.stdout_preview or "(empty)")
    lines.append("```")
    lines.append("## stderr preview (bounded, redacted)")
    lines.append("```")
    lines.append(run.stderr_preview or "(empty)")
    lines.append("```")
    return "\n".join(lines)


HARNESS_CANDIDATE_CAVEAT = (
    "Advisory candidate projected from a recorded run observation; review before saving as a "
    "Tool Note. An exit code is recorded, not interpreted as a verdict."
)


def _candidate_id(run_id: str, lesson: str) -> str:
    return "cand_" + hashlib.sha256(f"{run_id}\x1f{lesson}".encode()).hexdigest()[:16]


def _run_suggests_candidate(run: HarnessRun) -> bool:
    """Conservative trigger: an explicit check_label plus an explicit signal to review."""
    if not run.check_label:
        return False
    return bool(run.note) or run.output_truncated or run.redaction_applied or (
        run.exit_code is not None and run.exit_code != 0
    )


def project_harness_candidates(runs: list[HarnessRun]) -> list[dict[str, Any]]:
    """Read-only HarnessRun -> candidate-lesson projection. No save, no ranking, no fuzzy.

    Conservative and mostly verbatim: the lesson is the run's note when present, else a
    neutral inspection prompt built from the check label. Nothing is saved as a Tool Note.
    """
    out: list[dict[str, Any]] = []
    for run in runs:
        if not _run_suggests_candidate(run):
            continue
        if run.note:
            lesson = run.note
        else:
            lesson = (
                f"For '{run.check_label}', inspect the bounded command output and artifact "
                "refs before closing the session."
            )
        flags = []
        if run.output_truncated:
            flags.append("output truncated")
        if run.redaction_applied:
            flags.append("redaction applied")
        evidence = f"Run {run.run_id} ({run.mode}, {_exit_phrase(run.exit_code)})"
        if flags:
            evidence += "; " + ", ".join(flags)
        out.append({
            "schema_version": SCHEMA_VERSION,
            "candidate_id": _candidate_id(run.run_id, lesson),
            "source_run_ids": [run.run_id],
            "task_kind": None,
            "tool_name": "harness",
            "workflow_name": run.check_label,
            "lesson": lesson,
            "evidence": evidence,
            "caveat": HARNESS_CANDIDATE_CAVEAT,
            "tags": list(run.tags),
        })
    return out


__all__ = [
    "DEFAULT_MAX_OUTPUT_BYTES",
    "MODES",
    "STATUSES",
    "STORE_FILE",
    "HarnessError",
    "HarnessRun",
    "append_harness_run",
    "build_executed_run",
    "build_recorded_run",
    "compact_run",
    "filter_runs",
    "find_run",
    "make_run_id",
    "read_harness_runs",
    "render_run_markdown",
    "runs_for_store",
]
