from __future__ import annotations

import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from chimera_memory_types.finding import EvidenceRefType

from chimera_memory.adapters.git import capture_git_evidence
from chimera_memory.cli import main
from chimera_memory.storage import MemoryStore

FIXED_TIME = datetime(2026, 6, 2, 12, tzinfo=UTC)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def _init_repo(root: Path) -> None:
    _git(root, "init")
    _git(root, "config", "user.name", "Chimera Test")
    _git(root, "config", "user.email", "chimera@example.test")


def test_git_adapter_captures_commit_evidence(tmp_path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "tracked.txt").write_text("initial\n")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "-m", "initial")
    (tmp_path / "dirty.txt").write_text("dirty\n")
    commit_sha = _git(tmp_path, "rev-parse", "HEAD")

    evidence_refs, metadata = capture_git_evidence(root=tmp_path, claim_time=FIXED_TIME)

    assert metadata["git_available"] is True
    assert metadata["commit_sha"] == commit_sha
    assert metadata["branch"]
    assert "dirty.txt" in metadata["files_changed"]
    assert metadata["dirty_state"] is True
    assert metadata["status"]
    assert len(evidence_refs) == 1
    assert evidence_refs[0].ref_type == EvidenceRefType.EXTERNAL
    assert evidence_refs[0].ref_id == f"git:{commit_sha}"
    assert evidence_refs[0].available_at == FIXED_TIME


def test_git_adapter_handles_no_git_repo_gracefully(tmp_path) -> None:
    evidence_refs, metadata = capture_git_evidence(root=tmp_path, claim_time=FIXED_TIME)

    assert evidence_refs == []
    assert metadata["git_available"] is False
    assert metadata["reason"]


def test_git_adapter_uses_local_git_only(monkeypatch, tmp_path) -> None:
    commands: list[list[str]] = []

    def fail_connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("network path touched")

    class Result:
        def __init__(self, stdout: str = "", returncode: int = 0) -> None:
            self.stdout = stdout
            self.stderr = ""
            self.returncode = returncode

    def fake_run(command: list[str], **kwargs: object) -> Result:
        commands.append(command)
        assert kwargs.get("shell") is not True
        if command[-2:] == ["rev-parse", "HEAD"]:
            return Result("abc123\n")
        if command[-2:] == ["branch", "--show-current"]:
            return Result("main\n")
        if command[-2:] == ["status", "--short"]:
            return Result(" M file.py\n")
        return Result(returncode=1)

    monkeypatch.setattr(socket, "create_connection", fail_connect)
    monkeypatch.setattr(socket.socket, "connect", fail_connect)
    monkeypatch.setattr("chimera_memory.adapters.git.subprocess.run", fake_run)

    capture_git_evidence(root=tmp_path, claim_time=FIXED_TIME)

    forbidden = {"fetch", "pull", "push", "clone", "ls-remote", "remote update"}
    for command in commands:
        joined = " ".join(command)
        assert not any(term in joined for term in forbidden)


def test_wrap_includes_git_metadata_when_available(monkeypatch, tmp_path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "test_sample.py").write_text("def test_pass():\n    assert True\n")
    _git(tmp_path, "add", "test_sample.py")
    _git(tmp_path, "commit", "-m", "add test")
    monkeypatch.chdir(tmp_path)

    assert main(["wrap", "pytest", "-q"]) == 0

    claim = MemoryStore.from_paths(root=tmp_path).latest_claims()[-1]
    assert claim.metadata["git"]["git_available"] is True
    assert claim.metadata["git"]["commit_sha"]
    assert claim.metadata["git"]["branch"]
    assert "files_changed" in claim.metadata["git"]
    assert "dirty_state" in claim.metadata["git"]
    assert any(ref.ref_id.startswith("git:") for ref in claim.evidence.evidence_refs)
    assert claim.confidence == 0.5


def test_wrap_includes_no_git_metadata_gracefully(monkeypatch, tmp_path) -> None:
    (tmp_path / "test_sample.py").write_text("def test_pass():\n    assert True\n")
    monkeypatch.chdir(tmp_path)

    assert main(["wrap", "pytest", "-q"]) == 0

    claim = MemoryStore.from_paths(root=tmp_path).latest_claims()[-1]
    assert claim.metadata["git"]["git_available"] is False
    assert claim.metadata["git"]["reason"]
