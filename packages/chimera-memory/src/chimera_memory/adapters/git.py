from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from chimera_memory_types.finding import EvidenceRef, EvidenceRefType


def capture_git_evidence(
    root: Path | str | None = None,
    claim_time: datetime | None = None,
) -> tuple[list[EvidenceRef], dict[str, object]]:
    repo = Path(root) if root is not None else Path.cwd()
    available_at = claim_time or datetime.now(UTC)

    head = _run_git(repo, "rev-parse", "HEAD")
    if head.missing:
        return [], {"git_available": False, "reason": "git executable not available"}
    if not head.ok:
        return [], {"git_available": False, "reason": head.reason}

    commit_sha = head.stdout.strip()
    branch_result = _run_git(repo, "branch", "--show-current")
    branch = branch_result.stdout.strip() if branch_result.ok else ""
    if not branch:
        branch = "HEAD"

    status_result = _run_git(repo, "status", "--short")
    status = status_result.stdout.splitlines() if status_result.ok else []
    files_changed = [_status_path(line) for line in status if _status_path(line)]

    metadata: dict[str, object] = {
        "git_available": True,
        "commit_sha": commit_sha,
        "branch": branch,
        "files_changed": files_changed,
        "dirty_state": bool(status),
        "status": status,
    }
    return [
        EvidenceRef(
            ref_type=EvidenceRefType.EXTERNAL,
            ref_id=f"git:{commit_sha}",
            available_at=available_at,
        )
    ], metadata


class _GitResult:
    def __init__(
        self,
        *,
        ok: bool,
        stdout: str = "",
        reason: str = "",
        missing: bool = False,
    ) -> None:
        self.ok = ok
        self.stdout = stdout
        self.reason = reason
        self.missing = missing


def _run_git(root: Path, *args: str) -> _GitResult:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            check=False,
            text=True,
            capture_output=True,
            shell=False,
        )
    except FileNotFoundError:
        return _GitResult(ok=False, reason="git executable not available", missing=True)

    if result.returncode != 0:
        reason = result.stderr.strip() or result.stdout.strip() or "git command failed"
        return _GitResult(ok=False, reason=reason)
    return _GitResult(ok=True, stdout=result.stdout)


def _status_path(line: str) -> str:
    if " -> " in line:
        return line.split(" -> ", 1)[1].strip()
    return line[3:].strip()
