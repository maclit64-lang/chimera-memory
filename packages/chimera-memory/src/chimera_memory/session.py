"""Chimera Memory M1-4: local session model.

A Session groups a coding-agent/dev run into one receipt. Sessions are stored
append-only in `<memory_dir>/sessions.jsonl` as a stream of `start`/`end` events.
The "current" session is the most recent session with no `end` event after it
(derived, not pointer-based — single source of truth).

Constraint: stdlib only. No Pydantic, no external deps. Frozen dataclass.
"""
from __future__ import annotations

import enum
import json
import secrets
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from typing import Any

UNKNOWN = "unknown"


class AttributionConfidence(enum.Enum):
    """Five-tier honest attribution scale (per brief)."""

    VERIFIED = "verified"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class IdentitySource(enum.Enum):
    """Where the attribution signal came from."""

    CLI_FLAG = "cli_flag"
    ENV_VAR = "env_var"
    GIT_CONFIG = "git_config"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


class FinalStatus(enum.Enum):
    """Outcome of a session (reconciliation of settled claims)."""

    PASSED = "passed"
    FAILED = "failed"
    MIXED = "mixed"
    INTERRUPTED = "interrupted"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Session:
    """One coding-agent/dev run. Append-only — never mutate historical sessions."""

    session_id: str
    repo_path: str = ""
    branch: str = ""
    task_label: str = ""
    agent_app: str = UNKNOWN
    provider: str | None = None
    model: str = UNKNOWN
    harness_id: str | None = None
    attribution_confidence: AttributionConfidence = AttributionConfidence.UNKNOWN
    identity_source: IdentitySource = IdentitySource.UNKNOWN
    started_at: str = ""
    ended_at: str | None = None
    start_commit: str | None = None
    end_commit: str | None = None
    start_dirty_state: bool = False
    end_dirty_state: bool = False
    start_files_changed: list[str] = field(default_factory=list)
    end_files_changed: list[str] = field(default_factory=list)
    files_changed_during: int = 0
    commands_observed: list[str] = field(default_factory=list)
    claims_created: list[str] = field(default_factory=list)
    outcomes_settled: list[str] = field(default_factory=list)
    final_status: FinalStatus | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize. Enum values become their string .value."""
        d = asdict(self)
        d["attribution_confidence"] = self.attribution_confidence.value
        d["identity_source"] = self.identity_source.value
        d["final_status"] = self.final_status.value if self.final_status is not None else None
        return d

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Session:
        """Reverse of to_dict. Strings are converted back to enum members."""
        # Build kwargs from the payload, only passing known fields
        valid = {f.name for f in fields(cls)}
        kwargs: dict[str, Any] = {k: v for k, v in payload.items() if k in valid}
        # Convert enum strings back to enum members
        if "attribution_confidence" in kwargs:
            kwargs["attribution_confidence"] = AttributionConfidence(
                kwargs["attribution_confidence"]
            )
        if "identity_source" in kwargs:
            kwargs["identity_source"] = IdentitySource(kwargs["identity_source"])
        if kwargs.get("final_status") is not None:
            kwargs["final_status"] = FinalStatus(kwargs["final_status"])
        else:
            kwargs["final_status"] = None
        return cls(**kwargs)


def new_session_id() -> str:
    """Sortable, readable session id. `sess-20260603T201530Z-a1b2c3d4`.

    Format: `sess-{ISO8601 compact}-{8 hex}`.
    - Sortable lexicographically by time
    - 8 hex suffix is a 4-byte random token (collision-safe for local use)
    - No external deps (no ULID library)
    """
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = secrets.token_hex(4)
    return f"sess-{ts}-{suffix}"


def session_to_json(session: Session) -> str:
    """JSON-serialize a session. Round-trips through Session.from_dict."""
    return json.dumps(session.to_dict(), sort_keys=True)
