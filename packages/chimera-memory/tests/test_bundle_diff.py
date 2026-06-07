"""Tests for chimera-memory bundle diff."""

import json
from pathlib import Path

import pytest

from chimera_memory.cli import main


@pytest.fixture()
def old_receipt(tmp_path: Path) -> Path:
    d = tmp_path / "old"
    d.mkdir()
    (d / "README.md").write_text("# Receipt\n")
    (d / "receipt.json").write_text('{"task": "old"}')
    (d / "receipt.md").write_text("# Old\n")
    (d / "verify.json").write_text('{"status": "OK", "broken_records": 0}')
    (d / "status.json").write_text('{"settled_unique_claims": 1, "unique_claims": 1}')
    (d / "failures.json").write_text('{"failures": []}')
    return d


@pytest.fixture()
def new_receipt(tmp_path: Path) -> Path:
    d = tmp_path / "new"
    d.mkdir()
    (d / "README.md").write_text("# Receipt\n")
    (d / "receipt.json").write_text('{"task": "new"}')
    (d / "receipt.md").write_text("# New\n")
    (d / "verify.json").write_text('{"status": "OK", "broken_records": 0}')
    (d / "status.json").write_text('{"settled_unique_claims": 3, "unique_claims": 3}')
    (d / "failures.json").write_text('{"failures": [{"claim_id": "x"}]}')
    (d / "extra.json").write_text("{}")
    return d


@pytest.fixture()
def evidence_a(tmp_path: Path) -> Path:
    d = tmp_path / "ev_a"
    d.mkdir()
    (d / "README.md").write_text("# Evidence\n")
    (d / "manifest.json").write_text('{"schema_version": 1, "claim_count": 2, "event_count": 2}')
    (d / "events.jsonl").write_text("{}\n{}\n")
    return d


@pytest.fixture()
def evidence_b(tmp_path: Path) -> Path:
    d = tmp_path / "ev_b"
    d.mkdir()
    (d / "README.md").write_text("# Evidence\n")
    (d / "manifest.json").write_text('{"schema_version": 1, "claim_count": 5, "event_count": 5}')
    (d / "events.jsonl").write_text("{}\n" * 5)
    return d


def test_diff_receipt_compatible(old_receipt: Path, new_receipt: Path, capsys) -> None:
    ret = main(["bundle", "diff", str(old_receipt), str(new_receipt), "--json"])
    assert ret == 0
    d = json.loads(capsys.readouterr().out)
    assert d["status"] == "OK"
    assert d["compatible"] is True
    assert d["old_bundle_type"] == "receipt"
    assert d["new_bundle_type"] == "receipt"


def test_diff_claim_count_delta(old_receipt: Path, new_receipt: Path, capsys) -> None:
    main(["bundle", "diff", str(old_receipt), str(new_receipt), "--json"])
    d = json.loads(capsys.readouterr().out)
    assert d["claim_count_delta"] == 2  # 3 - 1


def test_diff_failure_count_delta(old_receipt: Path, new_receipt: Path, capsys) -> None:
    main(["bundle", "diff", str(old_receipt), str(new_receipt), "--json"])
    d = json.loads(capsys.readouterr().out)
    assert d["failure_count_delta"] == 1


def test_diff_file_delta(old_receipt: Path, new_receipt: Path, capsys) -> None:
    main(["bundle", "diff", str(old_receipt), str(new_receipt), "--json"])
    d = json.loads(capsys.readouterr().out)
    assert "extra.json" in d["file_delta"]["added"]


def test_diff_evidence_compatible(evidence_a: Path, evidence_b: Path, capsys) -> None:
    ret = main(["bundle", "diff", str(evidence_a), str(evidence_b), "--json"])
    assert ret == 0
    d = json.loads(capsys.readouterr().out)
    assert d["status"] == "OK"
    assert d["compatible"] is True
    assert d["evidence_event_count_delta"] == 3  # 5 - 2


def test_diff_incompatible_types(old_receipt: Path, evidence_a: Path, capsys) -> None:
    ret = main(["bundle", "diff", str(old_receipt), str(evidence_a), "--json"])
    assert ret == 0
    d = json.loads(capsys.readouterr().out)
    assert d["status"] == "INCOMPATIBLE"
    assert d["compatible"] is False


def test_diff_unknown_bundle(tmp_path: Path, old_receipt: Path, capsys) -> None:
    unknown = tmp_path / "unk"
    unknown.mkdir()
    (unknown / "random.txt").write_text("hi")
    ret = main(["bundle", "diff", str(unknown), str(old_receipt), "--json"])
    assert ret == 0
    d = json.loads(capsys.readouterr().out)
    assert d["status"] == "UNKNOWN"


def test_diff_json_schema_version(old_receipt: Path, new_receipt: Path, capsys) -> None:
    main(["bundle", "diff", str(old_receipt), str(new_receipt), "--json"])
    d = json.loads(capsys.readouterr().out)
    assert d["schema_version"] == 1
    assert "next_actions" in d


def test_diff_no_writes(old_receipt: Path, new_receipt: Path) -> None:
    before_old = set(old_receipt.iterdir())
    before_new = set(new_receipt.iterdir())
    main(["bundle", "diff", str(old_receipt), str(new_receipt)])
    assert set(old_receipt.iterdir()) == before_old
    assert set(new_receipt.iterdir()) == before_new


def test_diff_text_output(old_receipt: Path, new_receipt: Path, capsys) -> None:
    ret = main(["bundle", "diff", str(old_receipt), str(new_receipt)])
    assert ret == 0
    out = capsys.readouterr().out
    assert "Bundle diff" in out
    assert "receipt" in out
