"""Tests for chimera-memory bundle inspect."""

import json
from pathlib import Path

import pytest

from chimera_memory.cli import main


@pytest.fixture()
def receipt_bundle(tmp_path: Path) -> Path:
    """Create a minimal receipt bundle fixture."""
    d = tmp_path / "receipt"
    d.mkdir()
    (d / "README.md").write_text("# Chimera Memory Receipt Bundle\n")
    (d / "receipt.json").write_text('{"task": "test"}')
    (d / "receipt.md").write_text("# Receipt\n")
    (d / "verify.json").write_text('{"status": "OK"}')
    return d


@pytest.fixture()
def evidence_bundle(tmp_path: Path) -> Path:
    """Create a minimal evidence bundle fixture."""
    d = tmp_path / "evidence"
    d.mkdir()
    (d / "README.md").write_text("# Evidence Bundle\n")
    (d / "manifest.json").write_text('{"schema_version": 1}')
    (d / "events.jsonl").write_text('{"claim_id": "abc"}\n')
    return d


def test_inspect_receipt_bundle_type(receipt_bundle: Path, capsys) -> None:
    ret = main(["bundle", "inspect", str(receipt_bundle), "--json"])
    assert ret == 0
    d = json.loads(capsys.readouterr().out)
    assert d["bundle_type"] == "receipt"
    assert d["status"] == "OK"


def test_inspect_evidence_bundle_type(evidence_bundle: Path, capsys) -> None:
    ret = main(["bundle", "inspect", str(evidence_bundle), "--json"])
    assert ret == 0
    d = json.loads(capsys.readouterr().out)
    assert d["bundle_type"] == "evidence"
    assert d["status"] == "OK"


def test_inspect_unknown_directory(tmp_path: Path, capsys) -> None:
    d = tmp_path / "empty"
    d.mkdir()
    (d / "random.txt").write_text("hello")
    ret = main(["bundle", "inspect", str(d), "--json"])
    assert ret == 0
    data = json.loads(capsys.readouterr().out)
    assert data["bundle_type"] == "unknown"
    assert data["status"] == "UNKNOWN"


def test_inspect_critical_on_raw_ledger(receipt_bundle: Path, capsys) -> None:
    (receipt_bundle / "claims.jsonl").write_text("{}")
    ret = main(["bundle", "inspect", str(receipt_bundle), "--json"])
    assert ret == 0
    d = json.loads(capsys.readouterr().out)
    assert d["status"] == "CRITICAL"
    assert "claims.jsonl" in d["unexpected_sensitive_files"]
    assert d["raw_ledger_files_found"] is True


def test_inspect_warning_on_private_path(receipt_bundle: Path, capsys) -> None:
    (receipt_bundle / "receipt.md").write_text("path: /Users/someone/code\n")
    ret = main(["bundle", "inspect", str(receipt_bundle), "--json"])
    assert ret == 0
    d = json.loads(capsys.readouterr().out)
    assert d["status"] == "WARNING"
    assert "receipt.md" in d["private_path_hits"]


def test_inspect_warning_on_token(receipt_bundle: Path, capsys) -> None:
    (receipt_bundle / "receipt.md").write_text("token=ghp_ABCDEFGHIJKLMNOPabcdefgh\n")
    ret = main(["bundle", "inspect", str(receipt_bundle), "--json"])
    assert ret == 0
    d = json.loads(capsys.readouterr().out)
    assert d["status"] == "WARNING"
    assert "receipt.md" in d["token_like_hits"]


def test_inspect_json_schema_version(receipt_bundle: Path, capsys) -> None:
    main(["bundle", "inspect", str(receipt_bundle), "--json"])
    d = json.loads(capsys.readouterr().out)
    assert d["schema_version"] == 1
    assert "present_files" in d
    assert "next_actions" in d


def test_inspect_does_not_write(receipt_bundle: Path, tmp_path: Path) -> None:
    before = set(receipt_bundle.iterdir())
    main(["bundle", "inspect", str(receipt_bundle)])
    after = set(receipt_bundle.iterdir())
    assert before == after


def test_inspect_text_output(receipt_bundle: Path, capsys) -> None:
    ret = main(["bundle", "inspect", str(receipt_bundle)])
    assert ret == 0
    out = capsys.readouterr().out
    assert "receipt" in out.lower()
    assert "OK" in out
    assert "Safe to review" in out
