from __future__ import annotations

import ast
import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest
from chimera_memory_types.finding import EvidenceRefType
from chimera_memory_types.knowledge import Claim

from chimera_memory.ledger import (
    export_report,
    query_memory,
    record_claim,
    settle_claim,
)
from chimera_memory.storage import MemoryStore

CLAIM_TIME = datetime(2026, 6, 2, 12, tzinfo=UTC)
OUTCOME_TIME = datetime(2026, 6, 3, 12, tzinfo=UTC)


def _files(root: Path) -> set[Path]:
    return {path.relative_to(root) for path in root.rglob("*") if path.is_file()}


def _evidence(ref_id: str = "git:abc123") -> dict[str, object]:
    return {
        "ref_type": EvidenceRefType.EXTERNAL,
        "ref_id": ref_id,
        "available_at": datetime(2026, 6, 2, 11, tzinfo=UTC),
    }


def _record(
    root: Path,
    *,
    agent_id: str,
    model_version: str,
    task_type: str,
    confidence: float | None = 0.8,
    ref_id: str = "git:abc123",
) -> str:
    return record_claim(
        title=f"{agent_id} predicts validation",
        summary="The coding agent predicts validation will pass.",
        predicted=True,
        evidence=[_evidence(ref_id)],
        root=root,
        claim_time=CLAIM_TIME,
        outcome_time=OUTCOME_TIME,
        confidence=confidence,
        agent_id=agent_id,
        model_version=model_version,
        task_type=task_type,
    )


def _ids(claims: list[Claim]) -> set[str]:
    return {claim.claim_id for claim in claims}


def _group(report: dict[str, object], **expected: str) -> dict[str, object]:
    groups = report["groups"]
    assert isinstance(groups, list)
    for group in groups:
        assert isinstance(group, dict)
        labels = group["group"]
        assert isinstance(labels, dict)
        if all(labels.get(key) == value for key, value in expected.items()):
            return group
    raise AssertionError(f"group not found: {expected}")


def test_nothing_written_outside_chimera_memory_dir(tmp_path) -> None:
    before = _files(tmp_path)

    MemoryStore.from_paths(root=tmp_path).ensure()
    claim_id = _record(
        tmp_path,
        agent_id="agent-4",
        model_version="gpt-5.5",
        task_type="coding",
    )
    settle_claim(claim_id, True, OUTCOME_TIME, root=tmp_path)
    query_memory(root=tmp_path)
    export_report(root=tmp_path)

    created = _files(tmp_path) - before
    assert created
    assert all(path.parts[0] == ".chimera-memory" for path in created)
    assert not (tmp_path / ".gitignore").exists()


def test_query_filters_by_agent_model_task(tmp_path) -> None:
    agent_match = _record(
        tmp_path,
        agent_id="agent-4",
        model_version="gpt-5.5",
        task_type="coding",
        ref_id="git:1",
    )
    model_match = _record(
        tmp_path,
        agent_id="agent-5",
        model_version="gpt-5.5",
        task_type="review",
        ref_id="git:2",
    )
    task_match = _record(
        tmp_path,
        agent_id="agent-6",
        model_version="gpt-6",
        task_type="coding",
        ref_id="git:3",
    )
    unsettled = _record(
        tmp_path,
        agent_id="agent-4",
        model_version="gpt-5.5",
        task_type="coding",
        ref_id="git:4",
    )
    settle_claim(agent_match, True, OUTCOME_TIME, root=tmp_path)
    settle_claim(model_match, True, OUTCOME_TIME, root=tmp_path)
    settle_claim(task_match, False, OUTCOME_TIME, root=tmp_path)

    assert _ids(query_memory(agent_id="agent-4", root=tmp_path)) == {agent_match}
    assert _ids(query_memory(model_version="gpt-5.5", root=tmp_path)) == {
        agent_match,
        model_match,
    }
    assert _ids(query_memory(task_type="coding", root=tmp_path)) == {agent_match, task_match}
    assert _ids(
        query_memory(
            agent_id="agent-4",
            model_version="gpt-5.5",
            task_type="coding",
            root=tmp_path,
        )
    ) == {agent_match}
    assert unsettled not in _ids(query_memory(root=tmp_path))
    assert unsettled in _ids(query_memory(root=tmp_path, settled_only=False))


def test_report_groups_reliability(tmp_path) -> None:
    group_a_valid = _record(
        tmp_path,
        agent_id="agent-4",
        model_version="gpt-5.5",
        task_type="coding",
        confidence=0.8,
        ref_id="git:a1",
    )
    group_a_failed = _record(
        tmp_path,
        agent_id="agent-4",
        model_version="gpt-5.5",
        task_type="coding",
        confidence=0.6,
        ref_id="git:a2",
    )
    group_b_valid = _record(
        tmp_path,
        agent_id="agent-5",
        model_version="gpt-5.5",
        task_type="review",
        confidence=0.7,
        ref_id="git:b1",
    )
    settle_claim(group_a_valid, True, OUTCOME_TIME, root=tmp_path)
    settle_claim(group_a_failed, False, OUTCOME_TIME, root=tmp_path)
    settle_claim(group_b_valid, True, OUTCOME_TIME, root=tmp_path)

    report = export_report(root=tmp_path)
    group_a = _group(
        report,
        agent_id="agent-4",
        model_version="gpt-5.5",
        task_type="coding",
    )
    group_b = _group(
        report,
        agent_id="agent-5",
        model_version="gpt-5.5",
        task_type="review",
    )

    assert group_a["count"] == 2
    assert group_a["settled_count"] == 2
    assert group_a["validation_rate"] == 0.5
    assert group_a["mean_proper_score"] == pytest.approx(((0.8 - 1.0) ** 2 + 0.6**2) / 2)
    assert group_a["contradictions"] == 1
    assert group_b["count"] == 1
    assert group_b["settled_count"] == 1
    assert group_b["validation_rate"] == 1.0
    assert group_b["contradictions"] == 0


def test_overconfidence_only_when_confidence_present(tmp_path) -> None:
    with_confidence = _record(
        tmp_path,
        agent_id="agent-4",
        model_version="gpt-5.5",
        task_type="coding",
        confidence=0.9,
        ref_id="git:confidence",
    )
    without_confidence = _record(
        tmp_path,
        agent_id="agent-5",
        model_version="gpt-5.5",
        task_type="review",
        confidence=None,
        ref_id="git:no-confidence",
    )
    settle_claim(with_confidence, False, OUTCOME_TIME, root=tmp_path)
    settle_claim(without_confidence, True, OUTCOME_TIME, root=tmp_path)

    report = export_report(root=tmp_path)
    group_a = _group(report, agent_id="agent-4")
    group_b = _group(report, agent_id="agent-5")
    latest = query_memory(agent_id="agent-4", root=tmp_path)[0]

    assert group_a["overconfidence"] == pytest.approx(0.9)
    assert group_b["overconfidence"] is None
    assert latest.confidence == 0.5


def test_local_only_no_network(monkeypatch, tmp_path) -> None:
    def fail_connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("network path touched")

    monkeypatch.setattr(socket, "create_connection", fail_connect)
    monkeypatch.setattr(socket.socket, "connect", fail_connect)

    claim_id = _record(
        tmp_path,
        agent_id="agent-4",
        model_version="gpt-5.5",
        task_type="coding",
    )
    settle_claim(claim_id, True, OUTCOME_TIME, root=tmp_path)
    query_memory(root=tmp_path)
    export_report(root=tmp_path)

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
