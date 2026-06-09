"""Tests for M2B readiness transparency, legacy unlabeled, dq-summary."""

from __future__ import annotations

import json

import pytest

from chimera_memory.cli import main


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()  # init now requires a git repo
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _init():
    main(["init"])


# ---------------------------------------------------------------------------
# m2b-readiness JSON: comparable_groups explicit in dq_cohort_summary
# ---------------------------------------------------------------------------


def test_m2b_json_comparable_groups_in_dq_cohort_summary(tmp_path, capsys):
    _init()
    capsys.readouterr()
    main(["m2b-readiness", "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    dq = d["dq_cohort_summary"]
    assert "comparable_groups" in dq, "comparable_groups must be in dq_cohort_summary"
    assert isinstance(dq["comparable_groups"], int)


def test_m2b_json_legacy_fields_in_dq_cohort_summary(tmp_path, capsys):
    _init()
    capsys.readouterr()
    main(["m2b-readiness", "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    dq = d["dq_cohort_summary"]
    assert dq.get("legacy_excluded_from_dq") is True
    assert dq.get("legacy_exclusion_reason"), "exclusion reason must be non-empty"
    assert "Legacy" in dq["legacy_exclusion_reason"]


def test_m2b_text_and_json_readiness_agree(tmp_path, capsys):
    _init()
    capsys.readouterr()
    main(["m2b-readiness"])
    text_out = capsys.readouterr().out
    capsys.readouterr()
    main(["m2b-readiness", "--json"])
    json_out = capsys.readouterr().out
    d = json.loads(json_out)
    level = d["readiness_level"]
    assert level.upper() in text_out.upper(), \
        f"readiness_level {level!r} not reflected in text output"


def test_m2b_json_repair_loop_completeness(tmp_path, capsys):
    _init()
    capsys.readouterr()
    main(["m2b-readiness", "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    rl = d.get("repair_loop_summary", {})
    assert "complete_loops" in rl
    assert "total_loops" in rl
    assert isinstance(rl["complete_loops"], int)


def test_m2b_json_no_score_field(tmp_path, capsys):
    _init()
    capsys.readouterr()
    main(["m2b-readiness", "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    # No scoring fields should appear
    for bad_key in ("score", "drift_score", "ranked", "routing"):
        assert bad_key not in d, f"unexpected scoring field: {bad_key!r}"


def test_m2b_json_uses_effective_group_summaries(tmp_path, capsys):
    """group_summaries key must be renamed to effective_group_summaries."""
    _init()
    capsys.readouterr()
    main(["m2b-readiness", "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    assert "effective_group_summaries" in d, "key must be effective_group_summaries"
    assert "group_summaries_note" in d, "note about errata-correction must be present"


def test_m2b_json_fixture_group_has_zero_organic(tmp_path, capsys):
    """On a fresh ledger, effective groups should have no test fixture organic_real."""
    _init()
    capsys.readouterr()
    main(["m2b-readiness", "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    for g in d.get("effective_group_summaries", []):
        # No group should have organic_real > 0 on a fresh ledger
        assert g["organic_real"] == 0


# ---------------------------------------------------------------------------
# dq-summary command
# ---------------------------------------------------------------------------


def test_dq_summary_exits_zero(tmp_path):
    _init()
    assert main(["dq-summary"]) == 0


def test_dq_summary_json_stable_keys(tmp_path, capsys):
    _init()
    capsys.readouterr()
    main(["dq-summary", "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    for key in ("schema_version", "total_claims", "legacy_unlabeled_claims",
                "legacy_exclusion_reason", "failure_origin_effective",
                "verification_scope", "repair_phase", "errata_applied_count"):
        assert key in d, f"missing dq-summary key: {key}"


def test_dq_summary_legacy_exclusion_reason(tmp_path, capsys):
    _init()
    capsys.readouterr()
    main(["dq-summary", "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    reason = d["legacy_exclusion_reason"]
    assert "not backfilled" in reason.lower() or "excluded" in reason.lower()


# ---------------------------------------------------------------------------
# Doctor blockers
# ---------------------------------------------------------------------------


def test_doctor_json_has_m2b_blockers(tmp_path, capsys):
    _init()
    capsys.readouterr()
    main(["doctor", "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    assert "m2b_blockers" in d["counts"]
    assert isinstance(d["counts"]["m2b_blockers"], list)


def test_doctor_text_shows_blockers_on_blocked_ledger(tmp_path, capsys):
    """On a fresh ledger, m2b is blocked; doctor text should show blockers."""
    _init()
    capsys.readouterr()
    main(["doctor"])
    out = capsys.readouterr().out
    assert "organic_real failures too few" in out or "blocked" in out.lower()


# ---------------------------------------------------------------------------
# No scoring, no migrate-labels
# ---------------------------------------------------------------------------


def test_no_score_command():
    """chimera-memory score must not exist."""
    result = main(["score"])
    # Should exit with error code (unrecognized command)
    assert result != 0


def test_no_migrate_labels_command():
    """chimera-memory migrate-labels must not exist."""
    result = main(["migrate-labels"])
    assert result != 0


def test_legacy_claims_not_treated_as_organic_real(tmp_path, capsys):
    """On a fresh empty ledger, dq-summary shows 0 organic_real."""
    _init()
    capsys.readouterr()
    main(["dq-summary", "--json"])
    out = capsys.readouterr().out
    d = json.loads(out)
    # Fresh ledger has no claims at all — organic_real must be 0
    assert d["failure_origin_effective"].get("organic_real", 0) == 0
    assert d["total_claims"] == 0
