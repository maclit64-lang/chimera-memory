"""Chimera Memory I3A: shared query / read-model layer.

Centralises claim classification so status, failures, report, and
future M2 all use one consistent source of truth.

Rules (D0 §9):
- unique claims: latest_claims() (deduped by claim_id)
- settled: claim_status is not None
- clean: settled + session_id + agent_id ≠ unknown-agent + model_version present
         + task_type + attribution_confidence + identity_source
- harness_id absence does NOT disqualify a clean claim
- failures: settled unique claims with claim_status == CONTRADICTED
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from chimera_memory_types.knowledge import Claim, ClaimStatus

if TYPE_CHECKING:
    from chimera_memory.storage import MemoryStore


# ---------------------------------------------------------------------------
# data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CleanClaimExclusions:
    missing_session_id: int
    unknown_agent: int
    model_version_null: int
    missing_task_type: int
    missing_attribution_confidence: int
    missing_identity_source: int
    unsettled: int


@dataclass(frozen=True)
class ClaimSegmentCounts:
    by_agent_id: dict[str, int]
    by_model_version: dict[str, int]
    by_harness_id: dict[str, int]
    by_task_type: dict[str, int]
    by_attribution_confidence: dict[str, int]
    by_identity_source: dict[str, int]


@dataclass
class ClaimReadModel:
    raw_records: int
    unique_claims: int
    settled_unique_claims: int
    clean_unique_claims: int
    clean_claims: list[Claim] = field(default_factory=list)
    failures: list[Claim] = field(default_factory=list)
    exclusions: CleanClaimExclusions = field(
        default_factory=lambda: CleanClaimExclusions(0, 0, 0, 0, 0, 0, 0)
    )
    segments: ClaimSegmentCounts = field(
        default_factory=lambda: ClaimSegmentCounts({}, {}, {}, {}, {}, {})
    )


# ---------------------------------------------------------------------------
# is_clean helper
# ---------------------------------------------------------------------------


def is_clean(claim: Claim) -> bool:
    """Return True if a settled claim meets D0 §9 clean-claim rules."""
    if claim.claim_status is None:
        return False
    m = claim.metadata or {}
    return (
        bool(m.get("session_id"))
        and m.get("agent_id") not in (None, "unknown-agent")
        and m.get("model_version") is not None
        and bool(m.get("task_type"))
        and bool(m.get("attribution_confidence"))
        and bool(m.get("identity_source"))
    )


# ---------------------------------------------------------------------------
# main read model builder
# ---------------------------------------------------------------------------


def latest_claims_from_records(records: list[Claim]) -> list[Claim]:
    """Deduplicate raw claim records to latest per claim_id.

    Processes in order so the last record per claim_id wins,
    matching store.latest_claims() semantics.
    """
    seen: dict[str, Claim] = {}
    for claim in records:
        seen[claim.claim_id] = claim
    return list(seen.values())


def build_claim_read_model(store: MemoryStore) -> ClaimReadModel:
    """Build the shared claim read model from the given store.

    Single-pass: calls store.read_claims() once and derives unique claims
    in memory, avoiding a second JSONL scan.
    """
    raw = store.read_claims()
    unique = latest_claims_from_records(raw)
    settled = [c for c in unique if c.claim_status is not None]

    # Exclusion counting (non-exclusive per claim)
    excl_no_session = 0
    excl_unknown_agent = 0
    excl_null_model = 0
    excl_no_task = 0
    excl_no_conf = 0
    excl_no_source = 0
    excl_unsettled = len(unique) - len(settled)

    clean: list[Claim] = []
    for c in settled:
        m = c.metadata or {}
        dirty = False
        if not m.get("session_id"):
            excl_no_session += 1
            dirty = True
        if m.get("agent_id") in (None, "unknown-agent"):
            excl_unknown_agent += 1
            dirty = True
        if m.get("model_version") is None:
            excl_null_model += 1
            dirty = True
        if not m.get("task_type"):
            excl_no_task += 1
            dirty = True
        if not m.get("attribution_confidence"):
            excl_no_conf += 1
            dirty = True
        if not m.get("identity_source"):
            excl_no_source += 1
            dirty = True
        if not dirty:
            clean.append(c)

    failures = [c for c in settled if c.claim_status == ClaimStatus.CONTRADICTED]

    # Segment counts over clean claims
    def _seg(field_name: str) -> dict[str, int]:
        ctr: Counter[str] = Counter()
        for c in clean:
            val = (c.metadata or {}).get(field_name)
            ctr[str(val) if val is not None else "None"] += 1
        return dict(ctr)

    return ClaimReadModel(
        raw_records=len(raw),
        unique_claims=len(unique),
        settled_unique_claims=len(settled),
        clean_unique_claims=len(clean),
        clean_claims=clean,
        failures=failures,
        exclusions=CleanClaimExclusions(
            missing_session_id=excl_no_session,
            unknown_agent=excl_unknown_agent,
            model_version_null=excl_null_model,
            missing_task_type=excl_no_task,
            missing_attribution_confidence=excl_no_conf,
            missing_identity_source=excl_no_source,
            unsettled=excl_unsettled,
        ),
        segments=ClaimSegmentCounts(
            by_agent_id=_seg("agent_id"),
            by_model_version=_seg("model_version"),
            by_harness_id=_seg("harness_id"),
            by_task_type=_seg("task_type"),
            by_attribution_confidence=_seg("attribution_confidence"),
            by_identity_source=_seg("identity_source"),
        ),
    )
