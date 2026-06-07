"""Tests for chimera-memory checks command."""

import sys
from pathlib import Path

from chimera_memory.cli import main


def test_checks_init_creates_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    ret = main(["checks", "init", "--preset", "python"])
    assert ret == 0
    assert (tmp_path / "chimera-memory.checks.toml").exists()


def test_checks_init_refuses_overwrite(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "chimera-memory.checks.toml").write_text("x")
    ret = main(["checks", "init", "--preset", "python"])
    assert ret == 1


def test_checks_run_passing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "chimera-memory.checks.toml"
    config.write_text(f'''
schema_version = 1
scope_path = "."
verification_scope = "package"
failure_origin = "organic_real"

[[checks]]
name = "hello"
command = ["{sys.executable}", "-c", "print('ok')"]
''')
    ret = main(["checks", "run", "--config", str(config)])
    assert ret == 0


def test_checks_run_failing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "chimera-memory.checks.toml"
    config.write_text(f'''
schema_version = 1
scope_path = "."

[[checks]]
name = "fail"
command = ["{sys.executable}", "-c", "import sys; sys.exit(1)"]
''')
    ret = main(["checks", "run", "--config", str(config)])
    assert ret == 1


def test_checks_run_rejects_string_command(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "chimera-memory.checks.toml"
    config.write_text('''
schema_version = 1
[[checks]]
name = "bad"
command = "echo hello"
''')
    ret = main(["checks", "run", "--config", str(config)])
    assert ret == 1


def test_checks_run_rejects_no_checks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "chimera-memory.checks.toml"
    config.write_text("schema_version = 1\n")
    ret = main(["checks", "run", "--config", str(config)])
    assert ret == 1


def test_checks_run_bundle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "chimera-memory.checks.toml"
    config.write_text(f'''
schema_version = 1
scope_path = "."

[[checks]]
name = "hello"
command = ["{sys.executable}", "-c", "print('ok')"]
''')
    out_dir = tmp_path / "run-out"
    ret = main(["checks", "run", "--config", str(config),
                "--bundle", "--output-dir", str(out_dir)])
    assert ret == 0
    assert (out_dir / "receipt" / "receipt.json").exists()


def test_checks_run_missing_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    ret = main(["checks", "run", "--config", "nonexistent.toml"])
    assert ret == 1


def test_checks_run_bundle_creates_report_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "chimera-memory.checks.toml"
    config.write_text(f'''
schema_version = 1
scope_path = "."

[[checks]]
name = "hello"
command = ["{sys.executable}", "-c", "print('ok')"]
''')
    out_dir = tmp_path / "run-out"
    main(["checks", "run", "--config", str(config),
          "--bundle", "--output-dir", str(out_dir)])
    report = out_dir / "report.json"
    assert report.exists()
    import json
    data = json.loads(report.read_text())
    assert data["schema_version"] == 1
    assert data["result"] == "PASSED"
    assert len(data["checks"]) == 1
    assert data["checks"][0]["name"] == "hello"
    assert data["checks"][0]["status"] == "VALIDATED"
    assert "receipt_path" in data
    assert "next_actions" in data


def test_checks_run_bundle_creates_report_md(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "chimera-memory.checks.toml"
    config.write_text(f'''
schema_version = 1
scope_path = "."

[[checks]]
name = "hello"
command = ["{sys.executable}", "-c", "print('ok')"]
''')
    out_dir = tmp_path / "run-out"
    main(["checks", "run", "--config", str(config),
          "--bundle", "--output-dir", str(out_dir)])
    report = out_dir / "report.md"
    assert report.exists()
    text = report.read_text()
    assert "PASSED" in text
    assert "hello" in text
    assert "VALIDATED" in text


def test_checks_run_failing_report(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "chimera-memory.checks.toml"
    config.write_text(f'''
schema_version = 1
scope_path = "."

[[checks]]
name = "fail"
command = ["{sys.executable}", "-c", "import sys; sys.exit(1)"]
''')
    out_dir = tmp_path / "run-out"
    main(["checks", "run", "--config", str(config),
          "--bundle", "--output-dir", str(out_dir)])
    import json
    data = json.loads((out_dir / "report.json").read_text())
    assert data["result"] == "FAILED"
    assert data["checks"][0]["status"] == "CONTRADICTED"


def test_checks_report_no_overclaim(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "chimera-memory.checks.toml"
    config.write_text(f'''
schema_version = 1
scope_path = "."

[[checks]]
name = "ok"
command = ["{sys.executable}", "-c", "print(1)"]
''')
    out_dir = tmp_path / "run-out"
    main(["checks", "run", "--config", str(config),
          "--bundle", "--output-dir", str(out_dir)])
    text = (out_dir / "report.md").read_text().lower()
    assert "not built" in text
    assert "m2b scoring is built" not in text
