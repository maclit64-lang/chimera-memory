"""Settlement and wealth bookkeeping schema models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ScoreFamily(StrEnum):
    BRIER = "brier"
    LOG = "log"
    CRPS_GAUSSIAN = "crps_gaussian"
    CRPS_ENSEMBLE = "crps_ensemble"
    INTERVAL = "interval"
    NEGATIVE_DEPTH = "negative_depth"


class ScoreConfig(BaseModel):
    family: ScoreFamily = ScoreFamily.BRIER
    params: dict[str, Any] = Field(default_factory=dict)


class ScoredOutcome(BaseModel):
    value: Any
    observed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SettlementStatus(StrEnum):
    PENDING = "pending"
    SETTLED = "settled"
    VALIDATED = "validated"
    CONTRADICTED = "contradicted"
    INCONCLUSIVE = "inconclusive"


class SettlementEvent(BaseModel):
    event_key: str
    observed_at: datetime
    outcome: Any
    source_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WealthUpdate(BaseModel):
    event_key: str
    proper_score: float | None = None
    wealth_multiplier: float = Field(default=1.0, gt=0.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class WealthState(BaseModel):
    wealth: float = Field(default=1.0, gt=0.0)
    log_wealth: float = 0.0
    updates: list[WealthUpdate] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SettlementState(BaseModel):
    status: SettlementStatus = SettlementStatus.PENDING
    score_config: ScoreConfig = Field(default_factory=ScoreConfig)
    events: list[SettlementEvent] = Field(default_factory=list)
    scored_outcomes: list[ScoredOutcome] = Field(default_factory=list)
    proper_score: float | None = None
    wealth: WealthState = Field(default_factory=WealthState)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SettlementRecord(BaseModel):
    record_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    claim_id: str
    settlement: SettlementState
    content_hash: str | None = None
    signature: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)
