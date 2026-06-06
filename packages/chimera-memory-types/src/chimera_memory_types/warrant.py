"""Warrant schema models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ComputabilityVerdict(StrEnum):
    COMPUTABLE = "computable"
    APPROXIMABLE = "approximable"
    UNCOMPUTABLE = "uncomputable"


class CausalVerdict(StrEnum):
    IDENTIFIED = "identified"
    BOUNDED = "bounded"
    UNIDENTIFIABLE = "unidentifiable"


class ExperimentSpec(BaseModel):
    name: str
    design: str
    assignment_unit: str | None = None
    outcome_metric: str | None = None
    minimum_sample_size: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Warrant(BaseModel):
    computability: ComputabilityVerdict = ComputabilityVerdict.COMPUTABLE
    causal_verdict: CausalVerdict
    estimand: str | None = None
    bounds: tuple[float, float] | None = None
    experiment_spec: ExperimentSpec | None = None
    assumptions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_verdict_requirements(self) -> Warrant:
        if self.causal_verdict is CausalVerdict.IDENTIFIED and self.estimand is None:
            raise ValueError("IDENTIFIED warrant requires estimand")
        if self.causal_verdict is CausalVerdict.BOUNDED and self.bounds is None:
            raise ValueError("BOUNDED warrant requires bounds")
        if (
            self.causal_verdict is CausalVerdict.UNIDENTIFIABLE
            and self.experiment_spec is None
        ):
            raise ValueError("UNIDENTIFIABLE warrant requires experiment_spec")
        return self
