"""Knowledge layer contracts for chimera-memory-types."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from chimera_memory_types.falsifier import Falsifier
from chimera_memory_types.finding import EvidenceRef
from chimera_memory_types.optimization import Intervention
from chimera_memory_types.reality_class import RealityClass
from chimera_memory_types.settlement import SettlementState
from chimera_memory_types.temporal import TemporalSeal
from chimera_memory_types.warrant import Warrant


class ClaimType(StrEnum):
    INTERVENTION_EFFECT = "intervention_effect"
    FAILURE_PATTERN = "failure_pattern"
    REGRESSION_RISK = "regression_risk"
    TRADEOFF_PATTERN = "tradeoff_pattern"
    DOMINANCE_PATTERN = "dominance_pattern"
    BACKTESTED_PREDICTION = "backtested_prediction"
    CAUSAL_POINT = "causal_point"
    CAUSAL_BOUNDED = "causal_bounded"
    NEGATIVE = "negative"
    ADMISSIBLE_WORLD = "admissible_world"
    UNANSWERABLE = "unanswerable"


class ClaimStatus(StrEnum):
    PROPOSED = "proposed"
    SUPPORTED = "supported"
    VALIDATED = "validated"
    STALE = "stale"
    CONTRADICTED = "contradicted"
    REJECTED = "rejected"


class DriftStatus(StrEnum):
    FRESH = "fresh"
    AGING = "aging"
    STALE = "stale"
    CONTRADICTED = "contradicted"


class PatternType(StrEnum):
    REPEATED_FINDING = "repeated_finding"
    REPEATED_SUCCESS = "repeated_success"
    REPEATED_FAILURE = "repeated_failure"
    REPEATED_TRADEOFF = "repeated_tradeoff"
    DOMINANCE_CLUSTER = "dominance_cluster"


class EvidenceBundle(BaseModel):
    """A traceable collection of evidence linked to a Claim or Pattern."""

    bundle_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_ids: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    recommendation_ids: list[str] = Field(default_factory=list)
    branch_refs: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    summary: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reality_class: RealityClass = RealityClass.INFERRED


class ValidityRange(BaseModel):
    world_types: list[str] = Field(default_factory=list)
    context_signature_ids: list[str] = Field(default_factory=list)
    min_evidence_count: int = 1
    expires_after_runs: int | None = None
    scope_note: str = ""


class ContextSignature(BaseModel):
    signature_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    world_type: str
    target_class: str | None = None
    actor_mix: dict[str, Any] = Field(default_factory=dict)
    scenario_family: str | None = None
    mutation_family: str | None = None
    objective_family: str | None = None
    complexity_bucket: str | None = None
    resource_regime: dict[str, Any] = Field(default_factory=dict)
    dimensions: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Claim(BaseModel):
    """An evidence-backed assertion about world behavior."""

    claim_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    claim_type: ClaimType
    claim_status: ClaimStatus = ClaimStatus.PROPOSED
    title: str
    summary: str
    evidence: EvidenceBundle
    context_signature_id: str | None = None
    validity_range: ValidityRange = Field(default_factory=ValidityRange)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    formal_statement: str | None = None
    temporal_seal: TemporalSeal | None = None
    warrant: Warrant | None = None
    falsifier: Falsifier | None = None
    settlement: SettlementState | None = None
    world_version: str | None = None
    model_version: str | None = None
    registry_record_id: str | None = None
    drift_status: DriftStatus = DriftStatus.FRESH
    supporting_run_ids: list[str] = Field(default_factory=list)
    contradicting_run_ids: list[str] = Field(default_factory=list)
    linked_intervention_ids: list[str] = Field(default_factory=list)
    linked_pattern_ids: list[str] = Field(default_factory=list)
    world_type: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)
    reality_class: RealityClass = RealityClass.INFERRED


class Pattern(BaseModel):
    pattern_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    pattern_type: PatternType
    title: str
    description: str
    supporting_claim_ids: list[str] = Field(default_factory=list)
    occurrence_count: int = 1
    world_type: str
    context_signature_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)
    reality_class: RealityClass = RealityClass.INFERRED


class InterventionEvaluation(BaseModel):
    optimization_run_id: str
    candidate_id: str
    score_delta: dict[str, float] = Field(default_factory=dict)
    status: str = "scored"
    rank: int | None = None
    accepted: bool = False
    evaluated_at: datetime | None = None


class InterventionMemory(BaseModel):
    memory_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    intervention: Intervention
    world_type: str
    context_signature_id: str | None = None
    evaluations: list[InterventionEvaluation] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    pattern_ids: list[str] = Field(default_factory=list)
    times_tried: int = 0
    times_succeeded: int = 0
    times_failed: int = 0
    times_dominated: int = 0
    last_evaluated_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeRef(BaseModel):
    ref_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    ref_type: Literal["claim", "pattern", "intervention_memory"]
    ref_target_id: str
    world_type: str
    context_note: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
