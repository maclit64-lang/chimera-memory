from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chimera_memory.scoring import _score
from chimera_memory.seal import _seal
from chimera_memory.storage import MemoryStore
from chimera_memory_types.falsifier import Falsifier
from chimera_memory_types.finding import EvidenceRef, EvidenceRefType
from chimera_memory_types.knowledge import Claim, ClaimStatus, ClaimType, EvidenceBundle
from chimera_memory_types.settlement import (
    ScoreConfig,
    ScoredOutcome,
    SettlementEvent,
    SettlementRecord,
    SettlementState,
    SettlementStatus,
)
from chimera_memory_types.temporal import LeakageStatus, TemporalSeal


def record_claim(
    *,
    title: str,
    summary: str,
    predicted: bool,
    evidence: list[EvidenceRef | dict[str, Any]],
    root: str | Path | None = None,
    memory_dir: str | Path | None = None,
    store_path: str | Path | None = None,
    claim_time: datetime | None = None,
    outcome_time: datetime | None = None,
    confidence: float | None = None,
    agent_id: str | None = None,
    model_version: str | None = None,
    task_type: str | None = None,
    claim_type: ClaimType | str | None = None,
    score_config: ScoreConfig | None = None,
    extra_metadata: dict[str, Any] | None = None,
    world_type: str = "coding-agent",
) -> str:
    if not isinstance(predicted, bool):
        raise ValueError("M0/M1 record_claim supports only binary predicted values")

    refs = [_coerce_evidence_ref(ref) for ref in evidence]
    prediction_probability = float(confidence) if confidence is not None else float(predicted)
    metadata: dict[str, Any] = {
        "agent_id": agent_id,
        "predicted_outcome": predicted,
    }
    if confidence is not None:
        metadata["confidence"] = confidence
    if model_version is not None:
        metadata["model_version"] = model_version
    if task_type is not None:
        metadata["task_type"] = task_type
    metadata = {key: value for key, value in metadata.items() if value is not None}
    if extra_metadata is not None:
        for key, value in extra_metadata.items():
            if key not in {
                "agent_id",
                "model_version",
                "task_type",
                "predicted_outcome",
                "confidence",
            }:
                metadata[key] = value

    claim = Claim(
        claim_type=_coerce_claim_type(claim_type),
        title=title,
        summary=summary,
        evidence=EvidenceBundle(evidence_refs=refs),
        falsifier=Falsifier(
            predicate="observed == predicted",
            predicate_kind="boolean",
            metadata={"predicted": predicted},
        ),
        settlement=SettlementState(
            score_config=score_config or ScoreConfig(),
            metadata={"predicted": prediction_probability},
        ),
        world_type=world_type,
        model_version=model_version,
        metadata=metadata,
    )
    sealed = _seal(
        claim,
        evidence_refs=refs,
        claim_time=claim_time or datetime.now(UTC),
        outcome_time=outcome_time,
    )
    store = MemoryStore.from_paths(root=root, memory_dir=memory_dir, store_path=store_path)
    store.append_claim(sealed)
    return sealed.claim_id


def settle_claim(
    claim_id: str,
    observed: object,
    observed_at: datetime,
    *,
    root: str | Path | None = None,
    memory_dir: str | Path | None = None,
    store_path: str | Path | None = None,
    event_metadata: dict[str, object] | None = None,
) -> float:
    store = MemoryStore.from_paths(root=root, memory_dir=memory_dir, store_path=store_path)
    claim = store.latest_claim(claim_id)
    if claim is None:
        raise ValueError(f"claim not found: {claim_id}")
    if claim.temporal_seal is None:
        raise ValueError("claim cannot be settled without a temporal seal")
    if claim.temporal_seal.leakage_status is not LeakageStatus.CLEAN:
        raise ValueError("claim cannot be settled with a poisoned temporal seal")
    if observed_at <= claim.temporal_seal.claim_time:
        raise ValueError("observed_at must be after claim_time")

    temporal_seal = claim.temporal_seal
    if temporal_seal.outcome_time is None:
        temporal_seal = TemporalSeal.model_validate(
            {
                **temporal_seal.model_dump(),
                "outcome_time": observed_at,
            }
        )
        if temporal_seal.leakage_status is LeakageStatus.POISONED:
            raise ValueError("settlement would poison the temporal seal")

    if claim.settlement is None:
        raise ValueError("claim cannot be settled without settlement metadata")
    predicted_probability = claim.settlement.metadata["predicted"]
    observed_bool = bool(observed)
    proper_score = _score(claim.settlement.score_config, predicted_probability, observed_bool)
    predicted_outcome = bool(claim.metadata["predicted_outcome"])
    claim_status = (
        ClaimStatus.VALIDATED if observed_bool == predicted_outcome else ClaimStatus.CONTRADICTED
    )
    settlement_status = (
        SettlementStatus.VALIDATED
        if observed_bool == predicted_outcome
        else SettlementStatus.CONTRADICTED
    )
    event = SettlementEvent(
        event_key=_event_key(claim_id, observed_at, observed_bool),
        observed_at=observed_at,
        outcome={"observed": observed_bool},
        metadata=event_metadata or {},
    )
    settlement = claim.settlement.model_copy(
        update={
            "status": settlement_status,
            "events": [*claim.settlement.events, event],
            "scored_outcomes": [
                *claim.settlement.scored_outcomes,
                ScoredOutcome(
                    value=observed_bool,
                    observed_at=observed_at,
                    metadata={"proper_score": proper_score, **(event_metadata or {})},
                ),
            ],
            "proper_score": proper_score,
        }
    )
    settled_claim = claim.model_copy(
        update={
            "claim_status": claim_status,
            "settlement": settlement,
            "temporal_seal": temporal_seal,
            "updated_at": datetime.now(UTC),
        }
    )
    store.append_outcome({"claim_id": claim_id, **event.model_dump(mode="json")})
    store.append_score(
        SettlementRecord(claim_id=claim_id, settlement=settlement).model_dump(mode="json")
    )
    store.append_claim(settled_claim)
    return proper_score


def query_memory(
    *,
    agent_id: str | None = None,
    model_version: str | None = None,
    task_type: str | None = None,
    settled_only: bool = True,
    root: str | Path | None = None,
    memory_dir: str | Path | None = None,
    store_path: str | Path | None = None,
) -> list[Claim]:
    store = MemoryStore.from_paths(root=root, memory_dir=memory_dir, store_path=store_path)
    claims = store.latest_claims()
    return [
        claim
        for claim in claims
        if _matches_claim(
            claim,
            agent_id=agent_id,
            model_version=model_version,
            task_type=task_type,
            settled_only=settled_only,
        )
    ]


def export_report(
    *,
    group_by: tuple[str, ...] = ("agent_id", "model_version", "task_type"),
    root: str | Path | None = None,
    memory_dir: str | Path | None = None,
    store_path: str | Path | None = None,
) -> dict[str, object]:
    claims = query_memory(
        settled_only=False,
        root=root,
        memory_dir=memory_dir,
        store_path=store_path,
    )
    groups: dict[tuple[object, ...], list[Claim]] = {}
    for claim in claims:
        key = tuple(_group_value(claim, field) for field in group_by)
        groups.setdefault(key, []).append(claim)

    return {
        "groups": [
            _report_group(group_by, key, group_claims)
            for key, group_claims in sorted(groups.items(), key=lambda item: str(item[0]))
        ]
    }


def _coerce_claim_type(claim_type: ClaimType | str | None) -> ClaimType:
    if claim_type is None:
        return ClaimType.BACKTESTED_PREDICTION
    return ClaimType(claim_type)


def _coerce_evidence_ref(ref: EvidenceRef | dict[str, Any]) -> EvidenceRef:
    if isinstance(ref, EvidenceRef):
        return ref
    return EvidenceRef.model_validate({"ref_type": EvidenceRefType.EXTERNAL, **ref})


def _event_key(claim_id: str, observed_at: datetime, observed: bool) -> str:
    return f"{claim_id}:{observed_at.isoformat()}:{str(observed).lower()}"


def _matches_claim(
    claim: Claim,
    *,
    agent_id: str | None,
    model_version: str | None,
    task_type: str | None,
    settled_only: bool,
) -> bool:
    if agent_id is not None and claim.metadata.get("agent_id") != agent_id:
        return False
    if model_version is not None and _group_value(claim, "model_version") != model_version:
        return False
    if task_type is not None and claim.metadata.get("task_type") != task_type:
        return False
    return not settled_only or _is_settled(claim)


def _is_settled(claim: Claim) -> bool:
    if claim.settlement is None:
        return False
    return (
        claim.settlement.status in {SettlementStatus.VALIDATED, SettlementStatus.CONTRADICTED}
        or bool(claim.settlement.events)
        or claim.settlement.proper_score is not None
    )


def _group_value(claim: Claim, field: str) -> object:
    if field == "model_version":
        return claim.metadata.get("model_version") or claim.model_version
    return claim.metadata.get(field)


def _report_group(
    group_by: tuple[str, ...],
    key: tuple[object, ...],
    claims: list[Claim],
) -> dict[str, object]:
    settled = [claim for claim in claims if _is_settled(claim)]
    validated = [
        claim for claim in settled if claim.settlement is not None
        and claim.settlement.status is SettlementStatus.VALIDATED
    ]
    contradicted = [
        claim for claim in settled if claim.settlement is not None
        and claim.settlement.status is SettlementStatus.CONTRADICTED
    ]
    scores = [
        claim.settlement.proper_score
        for claim in settled
        if claim.settlement is not None and claim.settlement.proper_score is not None
    ]
    confidences = [
        float(claim.metadata["confidence"])
        for claim in settled
        if "confidence" in claim.metadata
    ]
    validation_rate = len(validated) / len(settled) if settled else None
    mean_confidence = sum(confidences) / len(confidences) if confidences else None

    return {
        "group": dict(zip(group_by, key, strict=True)),
        "count": len(claims),
        "settled_count": len(settled),
        "validation_rate": validation_rate,
        "mean_proper_score": sum(scores) / len(scores) if scores else None,
        "contradictions": len(contradicted),
        "overconfidence": (
            mean_confidence - validation_rate
            if mean_confidence is not None and validation_rate is not None
            else None
        ),
    }


def build_dogfood_status(
    *,
    root: str | Path | None = None,
    memory_dir: str | Path | None = None,
    store_path: str | Path | None = None,
    gate_target: int = 30,
) -> dict[str, Any]:
    """Return a structured dogfood gate status dict.

    Applies D0 §9 clean-claim counting rules via the shared query read model.
    """
    from chimera_memory.query import build_claim_read_model

    store = MemoryStore.from_paths(root=root, memory_dir=memory_dir, store_path=store_path)
    rm = build_claim_read_model(store)
    excl = rm.exclusions
    seg = rm.segments

    def _gate_values(d: dict[str, int]) -> dict[str, int]:
        return {k: v for k, v in d.items() if v >= 5}

    gate_met = rm.clean_unique_claims >= gate_target

    return {
        "raw_records": rm.raw_records,
        "unique_claims": rm.unique_claims,
        "settled_unique_claims": rm.settled_unique_claims,
        "clean_unique_claims": rm.clean_unique_claims,
        "progress": {
            "current": rm.clean_unique_claims,
            "target": gate_target,
            "met": gate_met,
        },
        "excluded": {
            "missing_session_id": excl.missing_session_id,
            "unknown_agent": excl.unknown_agent,
            "model_version_null": excl.model_version_null,
            "missing_task_type": excl.missing_task_type,
            "missing_attribution_confidence": excl.missing_attribution_confidence,
            "missing_identity_source": excl.missing_identity_source,
            "unsettled": excl.unsettled,
        },
        "segments": {
            "agent_id": seg.by_agent_id,
            "model_version": seg.by_model_version,
            "harness_id": seg.by_harness_id,
            "task_type": seg.by_task_type,
            "attribution_confidence": seg.by_attribution_confidence,
            "identity_source": seg.by_identity_source,
        },
        "comparison_gate": {
            "agent_id": _gate_values(seg.by_agent_id),
            "model_version": _gate_values(seg.by_model_version),
            "harness_id": _gate_values(seg.by_harness_id),
            "task_type": _gate_values(seg.by_task_type),
        },
        "m2_ready": False,
        "reason": "INSUFFICIENT_DATA",
        "integrity": _integrity_summary(store),
        "data_quality": _dq_summary(rm, store),
        "m2b_readiness_level": _m2b_readiness_level(store)[0],
        "m2b_readiness_evaluation_mode": _m2b_readiness_level(store)[1],
    }


def _m2b_readiness_level(store: MemoryStore) -> tuple[str, str]:
    """Return (readiness_level, evaluation_mode) for status output."""
    try:
        from chimera_memory.m2b_readiness import compute_m2b_readiness
        report = compute_m2b_readiness(store)
        return report.readiness_level, report.evaluation_mode
    except Exception:
        return "unknown", "unknown"


def _dq_summary(rm: Any, store: Any = None) -> dict[str, Any]:
    """Build a data-quality summary from the read model's clean claims."""
    from chimera_memory.data_quality import dq_summary as _dq
    from chimera_memory.errata import effective_failure_origin, load_errata

    claims = rm.clean_claims
    metadatas = [c.metadata or {} for c in claims]
    summary = _dq(metadatas)
    summary["claims_with_repair_loop_id"] = sum(
        1 for m in metadatas if m.get("repair_loop_id")
    )

    # Add effective counts using store.memory_dir (never Path.cwd fallback)
    try:
        mem_dir = store.memory_dir if store is not None else None
        if mem_dir is not None:
            errata_map = load_errata(mem_dir)
            if errata_map:
                from collections import Counter
                eff_origins: Counter = Counter()
                for c in claims:
                    eff_origins[effective_failure_origin(c, errata_map) or "unknown"] += 1
                summary["effective_failure_origin_counts"] = dict(eff_origins)
                summary["errata_applied_count"] = len(errata_map)
    except Exception:
        pass

    return summary


def _integrity_summary(store: MemoryStore) -> dict[str, object]:
    """Compute and embed a compact integrity summary for status output."""
    from pathlib import Path as _Path

    from chimera_memory.integrity import integrity_report_to_summary, verify_integrity

    try:
        report = verify_integrity(_Path(store.memory_dir))
        return integrity_report_to_summary(report)
    except Exception:
        return {"status": "UNKNOWN", "errors_count": 1}
