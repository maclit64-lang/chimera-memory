"""Optimization and decision layer contracts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class OptimizationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


OPTIMIZATION_STATUS_TRANSITIONS: dict[OptimizationStatus, set[OptimizationStatus]] = {
    OptimizationStatus.PENDING: {OptimizationStatus.RUNNING, OptimizationStatus.CANCELLED},
    OptimizationStatus.RUNNING: {
        OptimizationStatus.COMPLETED,
        OptimizationStatus.FAILED,
        OptimizationStatus.CANCELLED,
    },
    OptimizationStatus.COMPLETED: set(),
    OptimizationStatus.FAILED: set(),
    OptimizationStatus.CANCELLED: set(),
}


def validate_optimization_status_transition(
    current: OptimizationStatus,
    target: OptimizationStatus,
) -> None:
    allowed = OPTIMIZATION_STATUS_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ValueError(f"Invalid OptimizationStatus transition: {current.value} → {target.value}")


class Intervention(BaseModel):
    """A generic change applied to a world snapshot."""

    intervention_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    intervention_type: str
    target: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    label: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class InterventionSet(BaseModel):
    set_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    label: str
    interventions: list[Intervention]
    world_type: str
    version: str = "0.1.0"
    metadata: dict[str, Any] = Field(default_factory=dict)


class CandidateIntervention(BaseModel):
    candidate_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    intervention: Intervention
    run_id: str | None = None
    score_delta: dict[str, float] = Field(default_factory=dict)
    scorecard: dict[str, Any] = Field(default_factory=dict)
    rank: int | None = None
    status: Literal["pending", "running", "simulation_launched", "scored", "failed", "skipped"] = (
        "pending"
    )
    error: str | None = None
    evaluated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Constraint(BaseModel):
    constraint_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    label: str
    metric: str
    operator: Literal["gte", "lte", "gt", "lt", "eq", "neq"]
    threshold: float


class Objective(BaseModel):
    objective_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    label: str
    metric: str
    direction: Literal["maximize", "minimize"]
    weight: float = 1.0


class SearchStrategy(StrEnum):
    NONE = "none"
    RANDOM = "random"
    GRID = "grid"


class OptimizationSpec(BaseModel):
    spec_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    world_type: str
    snapshot_id: str
    baseline_run_id: str
    objectives: list[Objective]
    constraints: list[Constraint] = Field(default_factory=list)
    candidates: list[CandidateIntervention]
    search_budget: int = 20
    seed: int = 0
    search_strategy: SearchStrategy = SearchStrategy.NONE
    warm_start_candidates: list[Intervention] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Recommendation(BaseModel):
    recommendation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    summary: str
    intervention: Intervention
    evidence_run_ids: list[str]
    tradeoffs: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    rank: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TradeoffSummary(BaseModel):
    summary_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    optimization_run_id: str
    dominated_pairs: list[dict[str, Any]] = Field(default_factory=list)
    pareto_front_candidate_ids: list[str] = Field(default_factory=list)
    metric_improvements: dict[str, int] = Field(default_factory=dict)
    narrative: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class OptimizationResult(BaseModel):
    result_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    optimization_run_id: str
    top_candidates: list[CandidateIntervention]
    recommendations: list[Recommendation]
    tradeoff_summary: TradeoffSummary | None = None
    candidates_evaluated: int
    candidates_skipped: int
    status: OptimizationStatus
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DecisionMemoryEntry(BaseModel):
    entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    optimization_run_id: str
    candidate_id: str
    intervention: Intervention
    world_type: str
    snapshot_id: str
    run_id: str
    score_delta: dict[str, float] = Field(default_factory=dict)
    passed_constraints: bool = True
    rank: int | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
