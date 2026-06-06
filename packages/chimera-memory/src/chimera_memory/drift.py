from __future__ import annotations

from pathlib import Path

from chimera_memory.ledger import query_memory
from chimera_memory_types.knowledge import Claim

ADVISORY_MESSAGE = "advisory only; not statistical proof"


def detect_drift(
    *,
    by: str = "model_version",
    min_claims: int = 30,
    baseline_window: int = 15,
    recent_window: int = 15,
    threshold: float = 0.20,
    root: str | Path | None = None,
    memory_dir: str | Path | None = None,
    store_path: str | Path | None = None,
) -> dict[str, object]:
    claims = query_memory(
        settled_only=True,
        root=root,
        memory_dir=memory_dir,
        store_path=store_path,
    )
    grouped: dict[object, list[Claim]] = {}
    for claim in claims:
        grouped.setdefault(_group_value(claim, by), []).append(claim)

    return {
        "by": by,
        "min_claims": min_claims,
        "method": "score_shift",
        "advisory": True,
        "groups": [
            _drift_group(group, group_claims, min_claims, baseline_window, recent_window, threshold)
            for group, group_claims in sorted(grouped.items(), key=lambda item: str(item[0]))
        ],
    }


def _drift_group(
    group: object,
    claims: list[Claim],
    min_claims: int,
    baseline_window: int,
    recent_window: int,
    threshold: float,
) -> dict[str, object]:
    scores = [
        float(claim.settlement.proper_score)
        for claim in claims
        if claim.settlement is not None and claim.settlement.proper_score is not None
    ]
    settled_count = len(scores)
    if settled_count < min_claims:
        return {
            "group": group,
            "settled_count": settled_count,
            "status": "INSUFFICIENT_DATA",
            "baseline_mean_score": None,
            "recent_mean_score": None,
            "score_shift": None,
            "threshold": threshold,
            "message": ADVISORY_MESSAGE,
        }

    baseline_scores = scores[:baseline_window]
    recent_scores = scores[-recent_window:]
    baseline_mean = _mean(baseline_scores)
    recent_mean = _mean(recent_scores)
    shift = recent_mean - baseline_mean
    return {
        "group": group,
        "settled_count": settled_count,
        "status": "DRIFT_ADVISORY" if shift >= threshold else "OK",
        "baseline_mean_score": _stable_float(baseline_mean),
        "recent_mean_score": _stable_float(recent_mean),
        "score_shift": _stable_float(shift),
        "threshold": threshold,
        "message": ADVISORY_MESSAGE,
    }


def _group_value(claim: Claim, by: str) -> object:
    if by == "model_version":
        return claim.metadata.get("model_version") or claim.model_version
    return claim.metadata.get(by)


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _stable_float(value: float) -> float:
    return round(value, 12)
