"""J1C: golden fixture contract tests for engine event export schema."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from chimera_memory_types.finding import EvidenceRefType

from chimera_memory.export import build_engine_events
from chimera_memory.ledger import record_claim, settle_claim
from chimera_memory.storage import MemoryStore

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "export"

# Volatile fields that differ between test runs and must be normalized
VOLATILE_FIELDS = {"event_id", "claim_id", "session_id", "timestamp"}


def _init(tmp_path: Path) -> MemoryStore:
    store = MemoryStore.from_paths(root=tmp_path)
    store.initialize()
    return store


def _ev(t: datetime) -> dict:
    return {"ref_type": EvidenceRefType.EXTERNAL, "ref_id": "git:abc123", "available_at": t}


def _normalize(event: dict, *, override: dict | None = None) -> dict:
    """Replace volatile fields with stable fixture values for comparison."""
    normalized = dict(event)
    if override:
        normalized.update(override)
    return normalized


def _build_validated_event(tmp_path: Path) -> dict:
    t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    t1 = t0 + timedelta(seconds=5)
    cid = record_claim(
        title="uv run pytest -q will pass", summary="s", predicted=True,
        evidence=[_ev(t0)], root=tmp_path, claim_time=t0,
        agent_id="kiro", model_version="claude-sonnet-4.6", task_type="test",
        extra_metadata={
            "session_id": "sess-fixture-validated",
            "harness_id": "kiro-cli",
            "attribution_confidence": "high",
            "identity_source": "cli_flag",
        },
    )
    settle_claim(cid, True, t1, root=tmp_path, event_metadata={
        "exit_code": 0,
        "wrapped_args": ["uv", "run", "pytest", "-q"],
        "stdout_excerpt": "",
        "stderr_excerpt": "",
        "duration_seconds": 1.2,
        "command": ["uv", "run", "pytest", "-q"],
    })
    store = MemoryStore.from_paths(root=tmp_path)
    events = build_engine_events(store)
    validated = [e for e in events if e["outcome"]["status"] == "VALIDATED"]
    assert validated, "no validated events found"
    return validated[0]


def _build_contradicted_event(tmp_path: Path) -> dict:
    t0 = datetime(2026, 1, 1, 0, 0, 10, tzinfo=UTC)
    t1 = t0 + timedelta(seconds=5)
    cid = record_claim(
        title="uv run mypy src will pass", summary="s", predicted=True,
        evidence=[_ev(t0)], root=tmp_path, claim_time=t0,
        agent_id="kiro", model_version="claude-sonnet-4.6", task_type="type",
        extra_metadata={
            "session_id": "sess-fixture-contradicted",
            "harness_id": "kiro-cli",
            "attribution_confidence": "high",
            "identity_source": "cli_flag",
        },
    )
    settle_claim(cid, False, t1, root=tmp_path, event_metadata={
        "exit_code": 1,
        "wrapped_args": ["uv", "run", "mypy", "src"],
        "stdout_excerpt": "error: Value of type object is not indexable",
        "stderr_excerpt": "",
        "duration_seconds": 2.1,
        "command": ["uv", "run", "mypy", "src"],
    })
    store = MemoryStore.from_paths(root=tmp_path)
    events = build_engine_events(store)
    contradicted = [e for e in events if e["outcome"]["status"] == "CONTRADICTED"]
    assert contradicted, "no contradicted events found"
    return contradicted[0]


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


def test_validated_event_matches_golden_fixture(tmp_path) -> None:
    """Exported VALIDATED event matches the golden fixture (volatile fields excluded)."""
    fixture = json.loads((FIXTURE_DIR / "validated_event_v1.json").read_text())
    event = _build_validated_event(tmp_path)

    # Normalize volatile fields to fixture values
    event = _normalize(event, override={
        "event_id": fixture["event_id"],
        "claim_id": fixture["claim_id"],
        "session_id": fixture["session_id"],
        "timestamp": fixture["timestamp"],
    })
    # Normalize git (test store has no git; fixture has nulls)
    event["git"] = fixture["git"]

    assert event == fixture


def test_contradicted_event_with_witness_matches_golden_fixture(tmp_path) -> None:
    """Exported CONTRADICTED event with witness matches the golden fixture."""
    fixture = json.loads((FIXTURE_DIR / "contradicted_event_v1.json").read_text())
    event = _build_contradicted_event(tmp_path)

    event = _normalize(event, override={
        "event_id": fixture["event_id"],
        "claim_id": fixture["claim_id"],
        "session_id": fixture["session_id"],
        "timestamp": fixture["timestamp"],
    })
    event["git"] = fixture["git"]

    assert event == fixture


def test_export_event_contract_rejects_missing_required_top_level_keys(tmp_path) -> None:
    """Every exported event must have all required top-level keys."""
    _init(tmp_path)
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = t0 + timedelta(seconds=5)
    cid = record_claim(
        title="t", summary="s", predicted=True, evidence=[_ev(t0)],
        root=tmp_path, claim_time=t0, agent_id="kiro",
    )
    settle_claim(cid, True, t1, root=tmp_path)

    store = MemoryStore.from_paths(root=tmp_path)
    events = build_engine_events(store)
    required = {
        "schema_version", "event_type", "event_id", "source",
        "session_id", "claim_id", "timestamp",
        "agent", "task", "command", "outcome", "witness", "git", "integrity",
    }
    for event in events:
        missing = required - set(event.keys())
        assert not missing, f"Event missing required keys: {missing}"


def test_export_golden_fixtures_are_parseable_json() -> None:
    """Both golden fixtures are valid JSON and have schema_version=1."""
    for name in ("validated_event_v1.json", "contradicted_event_v1.json"):
        data = json.loads((FIXTURE_DIR / name).read_text())
        assert data["schema_version"] == 1
        assert data["event_type"] == "memory.claim.settled"
        assert data["source"] == "chimera-memory"
