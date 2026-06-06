from __future__ import annotations

from datetime import UTC, datetime

from chimera_memory_types.finding import EvidenceRef, EvidenceRefType
from chimera_memory_types.knowledge import Claim, ClaimStatus, ClaimType, EvidenceBundle
from chimera_memory_types.settlement import (
    ScoreConfig,
    ScoreFamily,
    SettlementState,
    SettlementStatus,
)
from chimera_memory_types.temporal import LeakageStatus

from chimera_memory.drift import detect_drift
from chimera_memory.ledger import settle_claim
from chimera_memory.seal import _seal
from chimera_memory.storage import append_claim


def test_seal_golden_fixture_clean_claim() -> None:
    claim_time = datetime(2026, 6, 2, 12, tzinfo=UTC)
    outcome_time = datetime(2026, 6, 3, 12, tzinfo=UTC)
    available_at = datetime(2026, 6, 2, 11, 30, tzinfo=UTC)
    evidence_ref = EvidenceRef(
        ref_type=EvidenceRefType.EXTERNAL,
        ref_id="git:abc123",
        available_at=available_at,
        content_hash="sha256:abc123",
    )
    claim = Claim(
        claim_id="claim-golden",
        claim_type=ClaimType.BACKTESTED_PREDICTION,
        title="Golden sealed claim",
        summary="Fixture for local seal behavior.",
        evidence=EvidenceBundle(evidence_refs=[]),
        world_type="coding-agent",
    )

    sealed = _seal(
        claim,
        evidence_refs=[evidence_ref],
        claim_time=claim_time,
        outcome_time=outcome_time,
    )

    assert sealed.temporal_seal is not None
    assert sealed.temporal_seal.model_dump(mode="json") == {
        "seal_id": None,
        "claim_time": "2026-06-02T12:00:00Z",
        "evidence_window_start": None,
        "evidence_window_end": "2026-06-02T11:30:00Z",
        "outcome_time": "2026-06-03T12:00:00Z",
        "leakage_status": LeakageStatus.CLEAN,
        "metadata": {},
    }
    assert [ref.model_dump(mode="json") for ref in sealed.evidence.evidence_refs] == [
        {
            "ref_type": EvidenceRefType.EXTERNAL,
            "ref_id": "git:abc123",
            "available_at": "2026-06-02T11:30:00Z",
            "content_hash": "sha256:abc123",
        }
    ]


def test_settle_golden_fixture_binary_brier(tmp_path) -> None:
    claim_time = datetime(2026, 6, 2, 12, tzinfo=UTC)
    observed_at = datetime(2026, 6, 3, 12, tzinfo=UTC)
    evidence_ref = EvidenceRef(
        ref_type=EvidenceRefType.EXTERNAL,
        ref_id="git:abc123",
        available_at=datetime(2026, 6, 2, 11, 30, tzinfo=UTC),
    )
    claim = Claim(
        claim_id="claim-settle-golden",
        claim_type=ClaimType.BACKTESTED_PREDICTION,
        title="Golden settled claim",
        summary="Fixture for local settlement behavior.",
        evidence=EvidenceBundle(evidence_refs=[]),
        settlement=SettlementState(
            score_config=ScoreConfig(family=ScoreFamily.BRIER),
            metadata={"predicted": 0.8},
        ),
        world_type="coding-agent",
        metadata={"predicted_outcome": True},
    )
    sealed = _seal(
        claim,
        evidence_refs=[evidence_ref],
        claim_time=claim_time,
        outcome_time=observed_at,
    )
    append_claim(sealed, tmp_path / ".chimera-memory")

    score = settle_claim("claim-settle-golden", True, observed_at, root=tmp_path)

    assert score == 0.03999999999999998
    latest = [
        Claim.model_validate_json(line)
        for line in (tmp_path / ".chimera-memory" / "claims.jsonl").read_text().splitlines()
    ][-1]
    assert latest.claim_status == ClaimStatus.VALIDATED
    assert latest.settlement is not None
    assert latest.settlement.status == SettlementStatus.VALIDATED
    assert latest.settlement.proper_score == 0.03999999999999998
    assert latest.settlement.score_config.family == ScoreFamily.BRIER
    assert [event.model_dump(mode="json") for event in latest.settlement.events] == [
        {
            "event_key": "claim-settle-golden:2026-06-03T12:00:00+00:00:true",
            "observed_at": "2026-06-03T12:00:00Z",
            "outcome": {"observed": True},
            "source_ref": None,
            "metadata": {},
        }
    ]


def test_drift_golden_fixture_score_shift(tmp_path) -> None:
    for index, score in enumerate([0.01, 0.02, 0.03, 0.40, 0.45, 0.50]):
        claim = Claim(
            claim_id=f"claim-drift-golden-{index}",
            claim_type=ClaimType.BACKTESTED_PREDICTION,
            claim_status=ClaimStatus.VALIDATED,
            title=f"Drift claim {index}",
            summary="Fixture for local drift behavior.",
            evidence=EvidenceBundle(evidence_refs=[]),
            settlement=SettlementState(
                status=SettlementStatus.VALIDATED,
                score_config=ScoreConfig(family=ScoreFamily.BRIER),
                proper_score=score,
                metadata={"predicted": 0.8},
            ),
            world_type="coding-agent",
            metadata={"model_version": "model-golden", "predicted_outcome": True},
        )
        append_claim(claim, tmp_path / ".chimera-memory")

    result = detect_drift(
        root=tmp_path,
        min_claims=6,
        baseline_window=3,
        recent_window=3,
        threshold=0.2,
    )

    assert result == {
        "by": "model_version",
        "min_claims": 6,
        "method": "score_shift",
        "advisory": True,
        "groups": [
            {
                "group": "model-golden",
                "settled_count": 6,
                "status": "DRIFT_ADVISORY",
                "baseline_mean_score": 0.02,
                "recent_mean_score": 0.45,
                "score_shift": 0.43,
                "threshold": 0.2,
                "message": "advisory only; not statistical proof",
            }
        ],
    }
