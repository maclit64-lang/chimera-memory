"""Tests for the Claude Code hook installer (v0.25)."""
from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from chimera_memory.cli import main
from chimera_memory.hooks import install_hooks, show_hooks_status, uninstall_hooks


@pytest.fixture
def project(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ── install ───────────────────────────────────────────────────────────────────
def test_install_creates_hook_scripts(project: Path) -> None:
    result = install_hooks(project)
    assert (project / ".claude" / "hooks" / "chimera-prompt-submit.sh").exists()
    assert (project / ".claude" / "hooks" / "chimera-stop.sh").exists()
    assert len(result["installed_files"]) == 2


def test_install_scripts_are_executable(project: Path) -> None:
    install_hooks(project)
    for name in ("chimera-prompt-submit.sh", "chimera-stop.sh"):
        s = (project / ".claude" / "hooks" / name).stat()
        assert s.st_mode & stat.S_IXUSR


def test_install_patches_settings_json(project: Path) -> None:
    install_hooks(project)
    settings = json.loads((project / ".claude" / "settings.json").read_text())
    assert "UserPromptSubmit" in settings["hooks"]
    assert "Stop" in settings["hooks"]


def test_install_merges_with_existing_settings(project: Path) -> None:
    settings_path = project / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"someOtherKey": True}))
    install_hooks(project)
    settings = json.loads(settings_path.read_text())
    assert settings["someOtherKey"] is True
    assert "hooks" in settings


def test_install_preserves_existing_hooks(project: Path) -> None:
    settings_path = project / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    existing_hook = {"matcher": "", "hooks": [{"type": "command", "command": "echo test"}]}
    settings_path.write_text(json.dumps({"hooks": {"Stop": [existing_hook]}}))
    install_hooks(project)
    settings = json.loads(settings_path.read_text())
    stop_hooks = settings["hooks"]["Stop"]
    # Our hook added, existing hook preserved
    commands = [h["command"] for group in stop_hooks for h in group.get("hooks", [])]
    assert any("chimera-stop.sh" in c for c in commands)
    assert any("echo test" in c for c in commands)


def test_install_dry_run_writes_nothing(project: Path) -> None:
    result = install_hooks(project, dry_run=True)
    assert result["dry_run"] is True
    assert result["installed_files"]  # reported as would-be-installed
    assert not (project / ".claude").exists()


def test_install_idempotent_without_force(project: Path) -> None:
    install_hooks(project)
    result2 = install_hooks(project)
    # Second install warns but does not duplicate
    assert result2["installed_files"] == []  # scripts already exist
    assert result2["patched_settings_events"] == []  # entries already present
    assert result2["warnings"]


def test_install_force_overwrites(project: Path) -> None:
    install_hooks(project)
    result2 = install_hooks(project, force=True)
    assert len(result2["installed_files"]) == 2
    assert len(result2["patched_settings_events"]) == 2


def test_install_json_result_shape(project: Path) -> None:
    result = install_hooks(project)
    for key in ("installed_files", "patched_settings_events", "settings_path",
                "dry_run", "warnings"):
        assert key in result
    json.dumps(result)


# ── uninstall ─────────────────────────────────────────────────────────────────
def test_uninstall_removes_scripts(project: Path) -> None:
    install_hooks(project)
    uninstall_hooks(project)
    assert not (project / ".claude" / "hooks" / "chimera-prompt-submit.sh").exists()
    assert not (project / ".claude" / "hooks" / "chimera-stop.sh").exists()


def test_uninstall_removes_settings_entries(project: Path) -> None:
    install_hooks(project)
    uninstall_hooks(project)
    settings = json.loads((project / ".claude" / "settings.json").read_text())
    assert "hooks" not in settings or not settings.get("hooks")


def test_uninstall_preserves_other_settings(project: Path) -> None:
    settings_path = project / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"myKey": 42}))
    install_hooks(project)
    uninstall_hooks(project)
    settings = json.loads(settings_path.read_text())
    assert settings.get("myKey") == 42


# ── status ────────────────────────────────────────────────────────────────────
def test_status_not_installed_on_fresh_project(project: Path) -> None:
    result = show_hooks_status(project)
    assert result["installed"] is False


def test_status_installed_after_install(project: Path) -> None:
    install_hooks(project)
    result = show_hooks_status(project)
    assert result["installed"] is True
    assert all(result["scripts"].values())
    assert all(result["settings_hooks"].values())


def test_status_result_is_json_serializable(project: Path) -> None:
    result = show_hooks_status(project)
    json.dumps(result)


# ── CLI ───────────────────────────────────────────────────────────────────────
def test_cli_hooks_in_help(capsys) -> None:
    try:
        main(["--help"])
    except SystemExit:
        pass
    assert "hooks" in capsys.readouterr().out


def test_cli_hooks_install_help(capsys) -> None:
    try:
        main(["hooks", "install", "--help"])
    except SystemExit:
        pass
    out = capsys.readouterr().out
    assert "UserPromptSubmit" in out or "Stop" in out or "Claude" in out


def test_cli_hooks_install(project: Path) -> None:
    assert main(["hooks", "install"]) == 0
    assert (project / ".claude" / "hooks" / "chimera-stop.sh").exists()


def test_cli_hooks_install_json(project: Path, capsys) -> None:
    assert main(["hooks", "install", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert "installed_files" in data


def test_cli_hooks_install_dry_run(project: Path) -> None:
    assert main(["hooks", "install", "--dry-run"]) == 0
    assert not (project / ".claude").exists()


def test_cli_hooks_status(project: Path, capsys) -> None:
    main(["hooks", "install"])
    assert main(["hooks", "status"]) == 0


def test_cli_hooks_status_json(project: Path, capsys) -> None:
    main(["hooks", "install"])
    capsys.readouterr()  # clear prior output
    assert main(["hooks", "status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["installed"] is True


def test_cli_hooks_uninstall(project: Path) -> None:
    main(["hooks", "install"])
    assert main(["hooks", "uninstall"]) == 0
    assert not (project / ".claude" / "hooks" / "chimera-stop.sh").exists()


# ── hook script content ───────────────────────────────────────────────────────
def test_stop_script_guards_stop_hook_active(project: Path) -> None:
    install_hooks(project)
    script = (project / ".claude" / "hooks" / "chimera-stop.sh").read_text()
    assert "stop_hook_active" in script


def test_stop_script_checks_chimera_skip(project: Path) -> None:
    install_hooks(project)
    script = (project / ".claude" / "hooks" / "chimera-stop.sh").read_text()
    assert "CHIMERA_SKIP_AUTOLOCK" in script


def test_stop_script_uses_commit_range_mode(project: Path) -> None:
    install_hooks(project)
    script = (project / ".claude" / "hooks" / "chimera-stop.sh").read_text()
    assert "--base" in script


def test_prompt_submit_script_has_reminder(project: Path) -> None:
    install_hooks(project)
    script = (project / ".claude" / "hooks" / "chimera-prompt-submit.sh").read_text()
    assert "CHIMERA_INTENT" in script


def test_settings_json_references_correct_script_paths(project: Path) -> None:
    install_hooks(project)
    settings = json.loads((project / ".claude" / "settings.json").read_text())
    stop_cmd = settings["hooks"]["Stop"][0]["hooks"][0]["command"]
    assert "chimera-stop.sh" in stop_cmd
    assert "CLAUDE_PROJECT_DIR" in stop_cmd  # uses project-relative path
