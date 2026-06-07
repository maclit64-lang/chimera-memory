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
