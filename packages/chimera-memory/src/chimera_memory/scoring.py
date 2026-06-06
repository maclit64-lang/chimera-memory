"""Proper scoring rules — inlined from chimera-core-score for standalone packaging."""

from __future__ import annotations

import math
from typing import Any

from chimera_memory_types.settlement import ScoreConfig, ScoreFamily


def _as_finite_float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be numeric, not bool")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _as_binary_observed(observed: Any) -> float:
    if isinstance(observed, bool):
        return 1.0 if observed else 0.0
    if isinstance(observed, int | float) and not isinstance(observed, bool):
        value = float(observed)
        if value in (0.0, 1.0):
            return value
    raise TypeError("observed must be bool or 0/1")


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def brier_score(predicted_probability: float, observed: bool | int | float) -> float:
    probability = _clamp(_as_finite_float(predicted_probability, "predicted_probability"), 0.0, 1.0)
    outcome = _as_binary_observed(observed)
    return (probability - outcome) ** 2


def log_score(
    predicted_probability: float,
    observed: bool | int | float,
    eps: float = 1e-15,
) -> float:
    epsilon = _as_finite_float(eps, "eps")
    if not 0.0 < epsilon < 0.5:
        raise ValueError("eps must be between 0 and 0.5")
    probability = _clamp(
        _as_finite_float(predicted_probability, "predicted_probability"),
        epsilon,
        1.0 - epsilon,
    )
    outcome = _as_binary_observed(observed)
    return -((outcome * math.log(probability)) + ((1.0 - outcome) * math.log(1.0 - probability)))


def _score(score_config: ScoreConfig, predicted: Any, observed: Any) -> float:
    if score_config.family is ScoreFamily.BRIER:
        return brier_score(predicted, observed)
    if score_config.family is ScoreFamily.LOG:
        return log_score(predicted, observed, eps=score_config.params.get("eps", 1e-15))
    raise ValueError(f"unsupported M0/M1 score family: {score_config.family}")


# Public alias matching chimera_core_score.proper.score_claim interface.
score_claim = _score
