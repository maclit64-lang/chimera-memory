"""Falsifier schema models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SettlementWindow(BaseModel):
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    max_delay_seconds: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Falsifier(BaseModel):
    predicate: str
    predicate_kind: Literal["threshold", "boolean", "membership", "absence"]
    settlement_window: SettlementWindow | None = None
    vacuous: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    def require_promotable(self) -> None:
        if self.vacuous:
            raise ValueError("vacuous falsifier cannot be promoted")
