from __future__ import annotations

import ast
import socket
from datetime import datetime
from pathlib import Path

from chimera_memory_types.knowledge import Claim, ClaimStatus
from chimera_memory_types.settlement import SettlementStatus

from chimera_memory.cli import main
from chimera_memory.storage import MemoryStore


def _latest_claim(root: Path) -> Claim:
    claims = MemoryStore.from_paths(root=root).latest_claims()
    assert claims
    return claims[-1]


def _latest_outcome(root: Path) -> dict[str, object]:
    outcomes = MemoryStore.from_paths(root=root).read_outcomes()
    assert outcomes
    return outcomes[-1]


def _write_pytest_file(root: Path, body: str) -> None:
    (root / "test_sample.py").write_text(body)


def test_init_creates_local_memory_files(monkeypatch, tmp_path, capsys) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)

    assert main(["init"]) == 0

    memory_dir = tmp_path / ".chimera-memory"
    assert (memory_dir / "claims.jsonl").exists()
    assert (memory_dir / "outcomes.jsonl").exists()
    assert (memory_dir / "scores.jsonl").exists()
    assert (memory_dir / "index.sqlite").exists()
    assert not (tmp_path / ".gitignore").exists() or ".chimera-memory/" in (tmp_path / ".gitignore").read_text()
    assert str(memory_dir) in capsys.readouterr().out


def test_wrap_pytest_records_before_run(monkeypatch, tmp_path) -> None:
    marker = tmp_path / "marker.txt"
    _write_pytest_file(
        tmp_path,
        "from datetime import UTC, datetime\n"
        "from pathlib import Path\n"
        f"def test_marker():\n    Path({str(marker)!r}).write_text(datetime.now(UTC).isoformat())\n",
    )
    monkeypatch.chdir(tmp_path)

    assert main(["wrap", "pytest", "-q"]) == 0

    claim = _latest_claim(tmp_path)
    marker_time = datetime.fromisoformat(marker.read_text())
    outcome = _latest_outcome(tmp_path)
    observed_at = datetime.fromisoformat(str(outcome["observed_at"]))
    assert claim.temporal_seal is not None
    assert claim.temporal_seal.claim_time <= marker_time
    assert observed_at >= marker_time


def test_wrap_pytest_settles_on_exit_code(monkeypatch, tmp_path) -> None:
    passing = tmp_path / "passing"
    passing.mkdir()
    _write_pytest_file(passing, "def test_pass():\n    assert True\n")
    monkeypatch.chdir(passing)

    assert main(["wrap", "pytest", "-q"]) == 0
    passing_claim = _latest_claim(passing)
    assert passing_claim.claim_status == ClaimStatus.VALIDATED
    assert passing_claim.settlement is not None
    assert passing_claim.settlement.status == SettlementStatus.VALIDATED
    assert _latest_outcome(passing)["outcome"] == {"observed": True}

    failing = tmp_path / "failing"
    failing.mkdir()
    _write_pytest_file(failing, "def test_fail():\n    assert False\n")
    monkeypatch.chdir(failing)

    assert main(["wrap", "pytest", "-q"]) != 0
    failing_claim = _latest_claim(failing)
    assert failing_claim.claim_status == ClaimStatus.CONTRADICTED
    assert failing_claim.settlement is not None
    assert failing_claim.settlement.status == SettlementStatus.CONTRADICTED
    assert _latest_outcome(failing)["outcome"] == {"observed": False}


def test_wrap_pytest_preserves_exit_code(monkeypatch, tmp_path) -> None:
    _write_pytest_file(tmp_path, "def test_fail():\n    assert False\n")
    monkeypatch.chdir(tmp_path)

    assert main(["wrap", "pytest", "-q"]) == 1


def test_wrap_uses_env_defaults(monkeypatch, tmp_path) -> None:
    _write_pytest_file(tmp_path, "def test_pass():\n    assert True\n")
    monkeypatch.setenv("CHIMERA_AGENT", "agent-env")
    monkeypatch.setenv("CHIMERA_MODEL", "model-env")
    monkeypatch.setenv("CHIMERA_TASK_TYPE", "task-env")
    monkeypatch.chdir(tmp_path)

    assert main(["wrap", "pytest", "-q"]) == 0

    claim = _latest_claim(tmp_path)
    assert claim.metadata["agent_id"] == "agent-env"
    assert claim.metadata["model_version"] == "model-env"
    assert claim.metadata["task_type"] == "task-env"


def test_cli_help(capsys) -> None:
    assert main(["--help"]) == 0
    assert main(["init", "--help"]) == 0
    assert main(["wrap", "--help"]) == 0
    assert "wrap" in capsys.readouterr().out


def test_wrap_no_shell_no_network(monkeypatch, tmp_path) -> None:
    def fail_connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("network path touched")

    calls: list[dict[str, object]] = []

    def fake_run(command: list[str], **kwargs: object) -> object:
        calls.append({"command": command, **kwargs})

        class Result:
            stdout = ""
            stderr = ""
            returncode = 0

        if command[0] == "git":
            Result.returncode = 1
            Result.stderr = "not a git repository"
        return Result()

    monkeypatch.setattr(socket, "create_connection", fail_connect)
    monkeypatch.setattr(socket.socket, "connect", fail_connect)
    monkeypatch.setattr("chimera_memory.adapters.pytest_ci.subprocess.run", fake_run)
    monkeypatch.chdir(tmp_path)

    assert main(["wrap", "pytest", "-q"]) == 0

    assert calls
    assert calls[0].get("shell") is not True
    root = Path("packages/chimera-memory/src/chimera_memory")
    forbidden = {"requests", "httpx", "urllib.request", "aiohttp", "socket"}
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                assert module not in forbidden
                assert not any(module.startswith(f"{name}.") for name in forbidden)


def test_wrap_prints_plain_report(monkeypatch, tmp_path, capsys) -> None:
    _write_pytest_file(tmp_path, "def test_pass():\n    assert True\n")
    monkeypatch.chdir(tmp_path)

    assert main(["wrap", "pytest", "-q"]) == 0

    output = capsys.readouterr().out
    assert "VALIDATED" in output


def test_wrap_persists_command_metadata(monkeypatch, tmp_path) -> None:
    _write_pytest_file(tmp_path, "def test_pass():\n    assert True\n")
    monkeypatch.chdir(tmp_path)

    assert main(["wrap", "pytest", "-q"]) == 0

    outcome = _latest_outcome(tmp_path)
    claim = _latest_claim(tmp_path)
    assert claim.settlement is not None
    event = claim.settlement.events[-1]
    assert outcome["metadata"]["exit_code"] == 0
    assert event.metadata["exit_code"] == 0
    assert "pytest" in event.metadata["command"]
    assert "-m" in event.metadata["command"]
    assert event.metadata["wrapped_args"] == ["pytest", "-q"]
    assert event.metadata["duration_seconds"] >= 0.0
    assert "git" in claim.metadata
    assert claim.confidence == 0.5
