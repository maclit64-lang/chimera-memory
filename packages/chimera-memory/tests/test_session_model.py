"""Slice 1: Session model + enums + from_dict/to_dict (no Pydantic)."""
from __future__ import annotations

import json

from chimera_memory.session import (
    UNKNOWN,
    AttributionConfidence,
    FinalStatus,
    IdentitySource,
    Session,
)


def _bare_session() -> Session:
    return Session(
        session_id="sess-test-1",
        repo_path="/tmp/repo",
        branch="main",
        task_label="fix bug",
        agent_app="claude-code",
        model="claude-opus-4",
        attribution_confidence=AttributionConfidence.HIGH,
        identity_source=IdentitySource.CLI_FLAG,
        started_at="2026-06-03T20:00:00+00:00",
        start_commit="abc1234",
        start_dirty_state=False,
    )


def test_session_round_trips_through_to_dict_from_dict() -> None:
    s = _bare_session()
    payload = s.to_dict()
    restored = Session.from_dict(payload)
    assert restored == s


def test_session_to_dict_serializes_enums_as_strings() -> None:
    s = _bare_session()
    payload = s.to_dict()
    assert payload["attribution_confidence"] == "high"
    assert payload["identity_source"] == "cli_flag"
    # full JSON-serializable (regression for non-string enum values)
    json.dumps(payload, sort_keys=True)


def test_session_from_dict_does_not_use_pydantic() -> None:
    # Hard requirement: no Pydantic in session module
    import chimera_memory.session as session_mod

    src = session_mod.__file__
    assert src is not None
    text = open(src, encoding="utf-8").read()
    assert "pydantic" not in text
    assert "model_validate" not in text
    assert "BaseModel" not in text


def test_unknown_constant_is_string_unknown() -> None:
    assert UNKNOWN == "unknown"


def test_attribution_confidence_has_five_tiers() -> None:
    assert {c.value for c in AttributionConfidence} == {
        "verified",
        "high",
        "medium",
        "low",
        "unknown",
    }


def test_identity_source_includes_env_var() -> None:
    # Env-var fallback (correction 4) requires this identity source
    assert "env_var" in {c.value for c in IdentitySource}


def test_final_status_includes_interrupted() -> None:
    assert "interrupted" in {c.value for c in FinalStatus}


def test_session_from_dict_converts_strings_to_enums() -> None:
    s = _bare_session()
    payload = s.to_dict()
    # mutate payload to be all strings
    payload["attribution_confidence"] = "medium"
    payload["identity_source"] = "env_var"
    payload["final_status"] = "failed"
    restored = Session.from_dict(payload)
    assert restored.attribution_confidence is AttributionConfidence.MEDIUM
    assert restored.identity_source is IdentitySource.ENV_VAR
    assert restored.final_status is FinalStatus.FAILED


def test_session_defaults_are_safe() -> None:
    # No required fields beyond what the plan calls required
    s = Session(session_id="x")
    assert s.repo_path == ""
    assert s.branch == ""
    assert s.task_label == ""
    assert s.agent_app == UNKNOWN
    assert s.model == UNKNOWN
    assert s.attribution_confidence is AttributionConfidence.UNKNOWN
    assert s.identity_source is IdentitySource.UNKNOWN
    assert s.ended_at is None
    assert s.end_commit is None
    assert s.start_dirty_state is False
    assert s.end_dirty_state is False
    assert s.start_files_changed == []
    assert s.end_files_changed == []
    assert s.files_changed_during == 0
    assert s.commands_observed == []
    assert s.claims_created == []
    assert s.outcomes_settled == []
    assert s.final_status is None


def test_session_frozen_rejects_mutation() -> None:
    s = _bare_session()
    try:
        s.session_id = "mutated"  # type: ignore[misc]
    except Exception as exc:  # FrozenInstanceError or AttributeError
        assert "frozen" in str(exc).lower() or "cannot" in str(exc).lower()
    else:
        raise AssertionError("Session should be frozen")
