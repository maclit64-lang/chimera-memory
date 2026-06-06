from collections.abc import Sequence
from datetime import datetime

from chimera_memory_types.finding import EvidenceRef
from chimera_memory_types.knowledge import Claim
from chimera_memory_types.temporal import LeakageStatus, TemporalSeal


def _seal(
    claim: Claim,
    evidence_refs: Sequence[EvidenceRef],
    claim_time: datetime,
    outcome_time: datetime | None = None,
) -> Claim:
    if not evidence_refs:
        raise ValueError("at least one evidence ref is required")
    if any(ref.available_at is None for ref in evidence_refs):
        raise ValueError("all evidence refs must include available_at")

    evidence_window_end = max(
        ref.available_at for ref in evidence_refs if ref.available_at is not None
    )
    temporal_seal = TemporalSeal(
        claim_time=claim_time,
        evidence_window_end=evidence_window_end,
        outcome_time=outcome_time,
    )
    if temporal_seal.leakage_status == LeakageStatus.POISONED:
        raise ValueError("temporal seal is poisoned")

    evidence = claim.evidence.model_copy(update={"evidence_refs": list(evidence_refs)})
    return claim.model_copy(update={"evidence": evidence, "temporal_seal": temporal_seal})
