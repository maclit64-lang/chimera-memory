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


# ---------------------------------------------------------------------------
# Helpers for claim-lock pre-edit state and Merge X-Ray change detection.
#
# All commands run with shell=False and never raise on a non-zero exit; callers
# get honest None/empty/"unknown" results when git is unavailable rather than
# an exception or a fabricated value.
# ---------------------------------------------------------------------------


def git_head_sha(root: Path | str | None = None) -> str | None:
    """Return the current HEAD commit SHA, or None if unavailable."""
    repo = Path(root) if root is not None else Path.cwd()
    result = _run_git(repo, "rev-parse", "HEAD")
    if not result.ok:
        return None
    sha = result.stdout.strip()
    return sha or None


def git_branch(root: Path | str | None = None) -> str | None:
    """Return the current branch name, or None if unavailable/detached."""
    repo = Path(root) if root is not None else Path.cwd()
    result = _run_git(repo, "branch", "--show-current")
    if not result.ok:
        return None
    branch = result.stdout.strip()
    return branch or None


def git_dirty_files(root: Path | str | None = None) -> tuple[str, list[str]]:
    """Return (dirty_state, tracked_dirty_files).

    dirty_state is "clean", "dirty", or "unknown" (git unavailable).
    tracked_dirty_files excludes untracked (``??``) entries.
    """
    repo = Path(root) if root is not None else Path.cwd()
    result = _run_git(repo, "status", "--short")
    if not result.ok:
        return "unknown", []
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    tracked: list[str] = []
    for line in lines:
        if line[:2].strip() == "??":
            continue
        path = _status_path(line)
        if path:
            tracked.append(path)
    dirty_state = "dirty" if lines else "clean"
    return dirty_state, sorted(set(tracked))


def git_untracked_files(root: Path | str | None = None) -> list[str]:
    """Return untracked file paths (``??`` entries from git status)."""
    repo = Path(root) if root is not None else Path.cwd()
    result = _run_git(repo, "status", "--short")
    if not result.ok:
        return []
    untracked: list[str] = []
    for line in result.stdout.splitlines():
        if line[:2] == "??":
            path = _status_path(line)
            if path:
                untracked.append(path)
    return sorted(set(untracked))


def git_changed_files_since(
    ref: str,
    root: Path | str | None = None,
    *,
    include_untracked: bool = True,
) -> list[str]:
    """Return files changed between ``ref`` and the current working tree.

    Combines tracked diffs (``git diff --name-only <ref>``) with optional
    untracked files. Returns a sorted, de-duplicated list of repo-relative
    paths. Returns an empty list if git is unavailable.
    """
    repo = Path(root) if root is not None else Path.cwd()
    result = _run_git(repo, "diff", "--name-only", ref)
    changed: set[str] = set()
    if result.ok:
        changed.update(p.strip() for p in result.stdout.splitlines() if p.strip())
    if include_untracked:
        changed.update(git_untracked_files(repo))
    return sorted(changed)


def git_changed_files_between(
    base: str,
    head: str,
    root: Path | str | None = None,
) -> list[str]:
    """Return files changed between ``base`` and ``head`` (two-dot diff).

    Returns a sorted, de-duplicated list of repo-relative paths, or an empty
    list if git is unavailable.
    """
    repo = Path(root) if root is not None else Path.cwd()
    result = _run_git(repo, "diff", "--name-only", base, head)
    if not result.ok:
        return []
    return sorted({p.strip() for p in result.stdout.splitlines() if p.strip()})


def git_available(root: Path | str | None = None) -> bool:
    """Return True if git is usable in ``root``."""
    repo = Path(root) if root is not None else Path.cwd()
    return _run_git(repo, "rev-parse", "HEAD").ok


def _parse_added_lines(diff_text: str) -> dict[str, list[str]]:
    """Parse a unified diff into ``{path: [added lines without leading '+']}``."""
    added: dict[str, list[str]] = {}
    current: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            path = line[4:].strip()
            if path.startswith("b/"):
                path = path[2:]
            current = None if path == "/dev/null" else path
        elif current and line.startswith("+") and not line.startswith("+++"):
            added.setdefault(current, []).append(line[1:])
    return added


def git_diff_added_lines(
    root: Path | str | None = None,
    *,
    base: str | None = None,
    head: str | None = None,
) -> dict[str, list[str]]:
    """Return added lines per file for the diff (leading ``+`` stripped).

    ``base`` given => commit-range mode (``base``..``head``); otherwise
    working-tree mode (vs ``HEAD``), where untracked files contribute their full
    content as added lines. Read-only; returns an empty dict if git is
    unavailable.
    """
    repo = Path(root) if root is not None else Path.cwd()
    if base is not None:
        result = _run_git(repo, "diff", "--unified=0", base, head or "HEAD")
    else:
        result = _run_git(repo, "diff", "--unified=0", "HEAD")
    added = _parse_added_lines(result.stdout) if result.ok else {}
    if base is None:
        others = _run_git(repo, "ls-files", "--others", "--exclude-standard")
        if others.ok:
            for path in others.stdout.splitlines():
                path = path.strip()
                if not path:
                    continue
                try:
                    text = (repo / path).read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                lines = text.splitlines()
                if lines:
                    added.setdefault(path, []).extend(lines)
    return added


def git_deleted_files(
    root: Path | str | None = None,
    *,
    base: str | None = None,
    head: str | None = None,
) -> list[str]:
    """Return paths deleted in the diff (``git diff --diff-filter=D``).

    ``base`` given => commit-range mode (``base``..``head``); otherwise
    working-tree deletions vs ``HEAD``. Read-only; returns an empty list if git
    is unavailable.
    """
    repo = Path(root) if root is not None else Path.cwd()
    if base is not None:
        result = _run_git(repo, "diff", "--diff-filter=D", "--name-only", base, head or "HEAD")
    else:
        result = _run_git(repo, "diff", "--diff-filter=D", "--name-only", "HEAD")
    if not result.ok:
        return []
    return sorted({p.strip() for p in result.stdout.splitlines() if p.strip()})
