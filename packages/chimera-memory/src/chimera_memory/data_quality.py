"""Chimera Memory data-quality metadata contract.

Additive metadata fields stored in claim.metadata. All fields are optional;
existing claims without them are valid and default to 'unknown'.
This contract is the foundation for future M2B reliability intelligence.
It does NOT implement M2B, routing, or statistical drift.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class FailureOrigin(StrEnum):
    """Why a failure (CONTRADICTED claim) occurred."""

    ORGANIC_REAL = "organic_real"        # genuine failure from real work
    SYNTHETIC = "synthetic"              # intentional test fixture (e.g. python -c raise)
    INVOCATION_ARTIFACT = "invocation_artifact"  # command typo / wrong args
    CONTROLLED_REAL = "controlled_real"  # intentional real failure for baseline
    TEST_FIRST_CONTRACT = "test_first_contract"  # TDD — test written before fix
    UNRESOLVED_DOWNSTREAM = "unresolved_downstream"  # failure caused by other broken thing
    UNKNOWN = "unknown"


class VerificationScope(StrEnum):
    """What scope a wrapped command covered."""

    FOCUSED_FILE = "focused_file"
    FOCUSED_SUBDIR = "focused_subdir"
    PACKAGE = "package"
    WORKSPACE = "workspace"
    FULL_SUITE = "full_suite"
    BASELINE_SWEEP = "baseline_sweep"
    REPAIR_CHECK = "repair_check"
    REGRESSION_CHECK = "regression_check"
    UNKNOWN = "unknown"


class RepairPhase(StrEnum):
    """Where in a repair loop this claim sits."""

    BASELINE = "baseline"                    # the failing claim being repaired
    REPAIR_ATTEMPT = "repair_attempt"        # a fix attempt
    SAME_SCOPE_AFTER_FIX = "same_scope_after_fix"  # re-run after fix — should pass
    REGRESSION_CHECK = "regression_check"    # broader check after fix
    NONE = "none"                            # not part of a repair loop


# ---------------------------------------------------------------------------
# Allowed value sets (for CLI validation)
# ---------------------------------------------------------------------------

FAILURE_ORIGIN_VALUES: set[str] = {v.value for v in FailureOrigin}
VERIFICATION_SCOPE_VALUES: set[str] = {v.value for v in VerificationScope}
REPAIR_PHASE_VALUES: set[str] = {v.value for v in RepairPhase}

# Metadata keys
K_FAILURE_ORIGIN = "failure_origin"
K_VERIFICATION_SCOPE = "verification_scope"
K_SCOPE_PATHS = "scope_paths"
K_SCOPE_INTENT = "scope_intent"
K_REPAIR_LOOP_ID = "repair_loop_id"
K_REPAIR_PHASE = "repair_phase"
K_REPAIR_OF_CLAIM_ID = "repair_of_claim_id"
K_BASELINE_CLAIM_ID = "baseline_claim_id"
K_RESIDUAL_OUT_OF_SCOPE = "residual_out_of_scope"

ALL_DQ_KEYS = frozenset({
    K_FAILURE_ORIGIN, K_VERIFICATION_SCOPE, K_SCOPE_PATHS, K_SCOPE_INTENT,
    K_REPAIR_LOOP_ID, K_REPAIR_PHASE, K_REPAIR_OF_CLAIM_ID,
    K_BASELINE_CLAIM_ID, K_RESIDUAL_OUT_OF_SCOPE,
})


def validate_failure_origin(value: str) -> str:
    if value not in FAILURE_ORIGIN_VALUES:
        raise ValueError(
            f"Invalid --failure-origin {value!r}. Allowed: {sorted(FAILURE_ORIGIN_VALUES)}"
        )
    return value


def validate_verification_scope(value: str) -> str:
    if value not in VERIFICATION_SCOPE_VALUES:
        raise ValueError(
            f"Invalid --verification-scope {value!r}. "
            f"Allowed: {sorted(VERIFICATION_SCOPE_VALUES)}"
        )
    return value


def validate_repair_phase(value: str) -> str:
    if value not in REPAIR_PHASE_VALUES:
        raise ValueError(
            f"Invalid --repair-phase {value!r}. Allowed: {sorted(REPAIR_PHASE_VALUES)}"
        )
    return value


# ---------------------------------------------------------------------------
# Metadata extraction helpers
# ---------------------------------------------------------------------------


def extract_dq_metadata(claim_metadata: dict[str, Any]) -> dict[str, Any]:
    """Extract data-quality fields from a claim's metadata dict."""
    return {k: claim_metadata[k] for k in ALL_DQ_KEYS if k in claim_metadata}


def dq_summary(claims_metadata_list: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate data-quality field counts across a list of claim metadata dicts."""
    from collections import Counter

    origins: Counter[str] = Counter()
    scopes: Counter[str] = Counter()
    phases: Counter[str] = Counter()
    repair_loops: set[str] = set()

    for m in claims_metadata_list:
        origins[m.get(K_FAILURE_ORIGIN, "unknown")] += 1
        scopes[m.get(K_VERIFICATION_SCOPE, "unknown")] += 1
        phases[m.get(K_REPAIR_PHASE, "none")] += 1
        if rl := m.get(K_REPAIR_LOOP_ID):
            repair_loops.add(str(rl))

    return {
        "failure_origin_counts": dict(origins),
        "verification_scope_counts": dict(scopes),
        "repair_phase_counts": dict(phases),
        "repair_loop_ids": sorted(repair_loops),
    }
