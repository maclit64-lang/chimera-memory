"""Finding, EvidencePack, Scorecard — the output contracts of a run."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class FindingSeverity(StrEnum):
    BLOCKER = "blocker"
    WARNING = "warning"
    INFO = "info"


class EvidenceRefType(StrEnum):
    """Discriminant for a typed evidence reference."""

    SESSION = "session"
    ARTIFACT = "artifact"
    SPAN = "span"
    FINDING = "finding"
    RUN = "run"
    EXTERNAL = "external"


class EvidenceRef(BaseModel):
    """Typed, machine-parseable reference to a piece of evidence."""

    ref_type: EvidenceRefType
    ref_id: str
    available_at: datetime | None = None
    content_hash: str | None = None


class BaselineComparison(BaseModel):
    baseline_run_id: str
    was_present_in_baseline: bool
    severity_change: Literal["new", "worsened", "unchanged", "improved"] | None = None
    delta_summary: str | None = None


class Finding(BaseModel):
    finding_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    severity: FindingSeverity
    category: str
    title: str
    summary: str
    evidence_refs: list[str] = []
    typed_evidence_refs: list[EvidenceRef] = []
    reproduction_path: list[str] = []
    affected_segments: list[str] = []
    root_cause_hypothesis: str | None = None
    suggested_fix: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    baseline_comparison: BaselineComparison | None = None
    branch_id: str | None = None
    divergence_point: int | None = None
    branch_lineage_ref: str | None = None
    determinism_certificate_id: str | None = None


class ArtifactRef(BaseModel):
    artifact_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    artifact_type: str
    storage_uri: str
    content_hash: str
    run_id: str


class Scorecard(BaseModel):
    run_id: str
    overall_result: Literal["pass", "block", "review_required"]
    metric_results: dict[str, float] = {}
    rule_results: dict[str, Any] = {}
    finding_count_by_severity: dict[str, int] = {}
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EvidencePack(BaseModel):
    evidence_pack_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    artifact_refs: list[ArtifactRef] = []
    span_refs: list[str] = []
    scorecard: Scorecard | None = None
