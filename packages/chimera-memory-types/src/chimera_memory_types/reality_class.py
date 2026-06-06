"""Reality classification enum for chimera-memory-types.

Standalone copy — no chimera_substrate dependency.
"""

from __future__ import annotations

from enum import StrEnum


class RealityClass(StrEnum):
    """Explicit classification of what kind of truth a record represents."""

    OBSERVED = "observed"
    SIMULATED = "simulated"
    COUNTERFACTUAL = "counterfactual"
    INFERRED = "inferred"
    RECOMMENDED = "recommended"

    @classmethod
    def require(cls, value: RealityClass | str | None) -> RealityClass:
        if value is None:
            raise ValueError("reality_class is required.")
        if isinstance(value, cls):
            return value
        return cls(value)


class SubstrateLayer(StrEnum):
    """Which logical substrate layer produced or owns a record."""

    CANONICAL = "canonical"
    SIGNAL = "signal"
    PROJECTION = "projection"
    CONTROL = "control"
