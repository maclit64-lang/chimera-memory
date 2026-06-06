from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from chimera_memory_types.finding import EvidenceRefType
from chimera_memory_types.knowledge import Claim, ClaimStatus
from chimera_memory_types.settlement import ScoreConfig, ScoreFamily, SettlementStatus

import chimera_memory
import chimera_memory.ledger
import chimera_memory.seal
from chimera_memory.ledger import record_claim, settle_claim
from chimera_memory.scoring import score_claim


def _evidence(available_at: datetime) -> dict[str, object]:
    return {
        "ref_type": EvidenceRefType.EXTERNAL,
        "ref_id": "git:abc123",
        "available_at": available_at,
    }


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _latest_claim(root: Path, claim_id: str) -> Claim:
    claims = [
        Claim.model_validate(payload)
        for payload in _jsonl(root / ".chimera-memory" / "claims.jsonl")
    ]
    matches = [claim for claim in claims if claim.claim_id == claim_id]
    assert matches
    return matches[-1]


def _record(
    root: Path,
    *,
    confidence: float = 0.8,
    score_config: ScoreConfig | None = None,
) -> str:
    return record_claim(
        title="Agent predicts passing validation",
        summary="The coding agent predicts validation will pass.",
        predicted=True,
        evidence=[_evidence(datetime(2026, 6, 2, 11, tzinfo=UTC))],
        root=root,
        claim_time=datetime(2026, 6, 2, 12, tzinfo=UTC),
        outcome_time=datetime(2026, 6, 3, 12, tzinfo=UTC),
        confidence=confidence,
        score_config=score_config,
    )


def test_settle_scores_binary_brier(tmp_path) -> None:
    claim_id = _record(tmp_path, confidence=0.8)

    score = settle_claim(
        claim_id,
        True,
        datetime(2026, 6, 3, 12, tzinfo=UTC),
        root=tmp_path,
    )

    assert score == pytest.approx((0.8 - 1.0) ** 2)


def test_settle_supports_binary_log(tmp_path) -> None:
    score_config = ScoreConfig(family=ScoreFamily.LOG)
    claim_id = _record(tmp_path, confidence=0.8, score_config=score_config)

    score = settle_claim(
        claim_id,
        True,
        datetime(2026, 6, 3, 12, tzinfo=UTC),
        root=tmp_path,
    )

    assert score == pytest.approx(score_claim(score_config, 0.8, True))


def test_settle_writes_outcome_and_score(tmp_path) -> None:
    claim_id = _record(tmp_path, confidence=0.8)

    settle_claim(
        claim_id,
        False,
        datetime(2026, 6, 3, 12, tzinfo=UTC),
        root=tmp_path,
    )

    memory_dir = tmp_path / ".chimera-memory"
    outcomes = _jsonl(memory_dir / "outcomes.jsonl")
    scores = _jsonl(memory_dir / "scores.jsonl")
    latest = _latest_claim(tmp_path, claim_id)

    assert outcomes[-1]["claim_id"] == claim_id
    assert outcomes[-1]["outcome"] == {"observed": False}
    assert scores[-1]["claim_id"] == claim_id
    assert scores[-1]["settlement"]["proper_score"] == pytest.approx((0.8 - 0.0) ** 2)
    assert latest.settlement is not None
    assert latest.settlement.status == SettlementStatus.CONTRADICTED
    assert latest.claim_status == ClaimStatus.CONTRADICTED


def test_storage_is_append_only(tmp_path) -> None:
    first_claim_id = _record(tmp_path, confidence=0.8)
    settle_claim(
        first_claim_id,
        True,
        datetime(2026, 6, 3, 12, tzinfo=UTC),
        root=tmp_path,
    )
    memory_dir = tmp_path / ".chimera-memory"
    paths = [
        memory_dir / "claims.jsonl",
        memory_dir / "outcomes.jsonl",
        memory_dir / "scores.jsonl",
    ]
    before_text = {path: path.read_text() for path in paths}

    second_claim_id = _record(tmp_path, confidence=0.7)
    settle_claim(
        second_claim_id,
        False,
        datetime(2026, 6, 3, 12, tzinfo=UTC),
        root=tmp_path,
    )

    for path in paths:
        after = path.read_text()
        assert after.startswith(before_text[path])
        assert len(after.splitlines()) > len(before_text[path].splitlines())


def test_no_evalue_or_martingale_terms() -> None:
    root = Path("packages/chimera-memory/src/chimera_memory")
    forbidden = ("e-value", "evalue", "martingale", "anytime", "finance", "trading")
    for path in root.rglob("*.py"):
        text = path.read_text()
        for token in forbidden:
            assert token not in text


def test_public_settle_claim_lives_in_ledger() -> None:
    assert chimera_memory.settle_claim is chimera_memory.ledger.settle_claim
    assert "settle_claim" not in vars(chimera_memory.seal)
