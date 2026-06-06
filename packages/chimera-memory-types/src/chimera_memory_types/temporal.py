"""Temporal sealing schema models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class LeakageStatus(StrEnum):
    CLEAN = "clean"
    POISONED = "poisoned"


class TemporalSeal(BaseModel):
    seal_id: str | None = None
    claim_time: datetime
    evidence_window_start: datetime | None = None
    evidence_window_end: datetime | None = None
    outcome_time: datetime | None = None
    leakage_status: LeakageStatus = LeakageStatus.CLEAN
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def compute_leakage_status(self) -> TemporalSeal:
        if self.claim_time.tzinfo is None:
            self.claim_time = self.claim_time.replace(tzinfo=UTC)
        if self.evidence_window_start is not None and self.evidence_window_start.tzinfo is None:
            self.evidence_window_start = self.evidence_window_start.replace(tzinfo=UTC)
        if self.evidence_window_end is not None and self.evidence_window_end.tzinfo is None:
            self.evidence_window_end = self.evidence_window_end.replace(tzinfo=UTC)
        if self.outcome_time is not None and self.outcome_time.tzinfo is None:
            self.outcome_time = self.outcome_time.replace(tzinfo=UTC)

        poisoned = False
        if self.evidence_window_end is not None:
            poisoned = self.evidence_window_end > self.claim_time
        if self.outcome_time is not None:
            poisoned = poisoned or self.outcome_time <= self.claim_time

        self.leakage_status = LeakageStatus.POISONED if poisoned else LeakageStatus.CLEAN
        return self
