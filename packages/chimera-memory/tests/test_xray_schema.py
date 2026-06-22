"""Public X-Ray / PR_EVIDENCE JSON schema contract (BIGREL-1).

These guard the receipt's public shape so future feature work cannot silently
break consumers. The contract is additive: required fields must stay present and
typed; new fields are allowed. No behavior is changed here.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from chimera_memory.storage import MemoryStore
from chimera_memory.xray import XRAY_SCHEMA_VERSION, generate_xray

# Stable public contract — required keys. Additive growth is allowed (subset check).
REQUIRED_TOP_LEVEL = frozenset(
    {
        "schema_version",
        "verdict",
        "verdict_label",
        "counts",
        "changed_files",
        "settled_claims",
        "evidence_dark_files",
        "scope_drift_files",
        "reviewer_focus",
        "evidence_quality_warnings",
        "test_integrity_warnings",
        "evidence_coverage_warnings",
        "caveat",
    }
)
REQUIRED_COUNTS = frozenset(
    {
        "changed_files",
        "claims",
        "settled_claims",
        "contradicted",
        "unsettled",
        "scope_drift",
        "evidence_dark",
        "evidence_quality_warnings",
        "test_integrity_warnings",
        "evidence_coverage_warnings",
    }
)
_WARNING_FAMILIES = (
    "evidence_quality_warnings",
    "test_integrity_warnings",
    "evidence_coverage_warnings",
)

# Secret-shaped patterns that must never appear in generated receipt output.
_SECRET_RE = re.compile(
    r"gh[poas]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9]{20,}|"
    r"sk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}|AKIA[A-Z0-9]{16}|xox[bpas]-[A-Za-z0-9\-]{10,}|"
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----|pypi-AgE"
)


def _git(p: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=p, check=True, capture_output=True)


def _cmd(command: list[str]) -> dict:
    return {"command": command, "role": "falsifier", "outcome": "PASS", "exit_code": 0, "stdout_excerpt": ""}


@pytest.fixture
def warned_result(tmp_path: Path, monkeypatch) -> dict:
    """A representative X-Ray result containing all three warning families."""
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t.dev")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "app.py").write_text("def f():\n    return 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test_f():\n    assert 1 == 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")
    monkeypatch.chdir(tmp_path)
    # Source change (coverage + quality) and a weakened test (integrity).
    (tmp_path / "pkg" / "app.py").write_text("def f():\n    return 2\n")
    (tmp_path / "tests" / "test_app.py").write_text(
        "import pytest\n\n\n@pytest.mark.skip\ndef test_f():\n    assert 1 == 1\n"
    )
    store = MemoryStore.from_paths(root=tmp_path)
    store.initialize()
    # Settled claim with lint-only evidence that does not target the changed source.
    store.append_claim_lock(
        {
            "claim_id": "c1",
            "intent": "fix bug",
            "scope_path": ".",
            "falsifiers": [{"command": ["ruff", "check", "."]}],
            "must_not_break": [],
            "settlement": {
                "status": "VALIDATED",
                "settled_at": "2026-06-22T00:00:00+00:00",
                "commands": [_cmd(["ruff", "check", "."])],
                "changed_files": ["pkg/app.py"],
                "scope_drift_files": [],
            },
        }
    )
    return generate_xray(store, root=tmp_path)


def test_required_top_level_fields_present(warned_result: dict) -> None:
    missing = REQUIRED_TOP_LEVEL - set(warned_result)
    assert not missing, f"receipt schema dropped required fields: {sorted(missing)}"


def test_schema_version_is_stable(warned_result: dict) -> None:
    assert warned_result["schema_version"] == XRAY_SCHEMA_VERSION == 1


def test_counts_include_all_warning_families(warned_result: dict) -> None:
    counts = warned_result["counts"]
    missing = REQUIRED_COUNTS - set(counts)
    assert not missing, f"counts dropped required keys: {sorted(missing)}"


def test_warning_fields_are_arrays(warned_result: dict) -> None:
    for fam in _WARNING_FAMILIES:
        assert isinstance(warned_result[fam], list)


def test_representative_result_populates_all_three_families(warned_result: dict) -> None:
    """The snapshot scenario must exercise all three warning families and matching counts."""
    for fam in _WARNING_FAMILIES:
        assert len(warned_result[fam]) >= 1, f"{fam} not populated by representative scenario"
        assert warned_result["counts"][fam] == len(warned_result[fam])


def test_additive_fields_do_not_break_consumers(warned_result: dict) -> None:
    """Adding an unknown field must not drop or alter required fields."""
    extended = dict(warned_result)
    extended["a_future_field"] = {"anything": [1, 2, 3]}
    extended["counts"] = {**warned_result["counts"], "a_future_count": 7}
    # A consumer reading the known contract still sees everything it needs.
    assert REQUIRED_TOP_LEVEL <= set(extended)
    assert REQUIRED_COUNTS <= set(extended["counts"])
    assert extended["verdict_label"] == warned_result["verdict_label"]


def test_result_is_json_serialisable(warned_result: dict) -> None:
    json.dumps(warned_result)


def test_no_secret_looking_values_in_output(warned_result: dict) -> None:
    blob = json.dumps(warned_result)
    assert not _SECRET_RE.search(blob), "secret-shaped value found in generated receipt"
