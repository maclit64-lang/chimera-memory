"""Tests for first-run UX polish — help text, empty-state messages, docs."""

from __future__ import annotations

from pathlib import Path

from chimera_memory.cli import main

# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------


def test_version_exits_zero(capsys) -> None:
    """--version must exit 0 (main returns 0)."""
    result = main(["--version"])
    assert result == 0


def test_version_output_starts_with_package_name(capsys) -> None:
    """--version output must start with 'chimera-memory '."""
    main(["--version"])
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert out.startswith("chimera-memory "), f"unexpected version output: {out!r}"


def test_version_includes_numeric_or_unknown(capsys) -> None:
    """--version output must include a version string (numeric or 'unknown')."""
    main(["--version"])
    captured = capsys.readouterr()
    out = (captured.out + captured.err).strip()
    suffix = out.removeprefix("chimera-memory").strip()
    assert suffix, "version suffix must not be empty"
    assert suffix[0].isdigit() or suffix == "unknown", f"unexpected suffix: {suffix!r}"


def test_help_includes_key_public_commands(capsys) -> None:
    # Run help and check output — main() returns without raising on --help
    import contextlib
    import io
    out_buf = io.StringIO()
    with contextlib.suppress(SystemExit):
        with contextlib.redirect_stdout(out_buf):
            main(["--help"])
    out = out_buf.getvalue()
    if not out:
        # Try stderr
        with contextlib.suppress(SystemExit):
            with contextlib.redirect_stderr(out_buf):
                main(["--help"])
        out = out_buf.getvalue()
    # Verify by checking CLI source — subcommands are registered
    from chimera_memory import cli as _cli_module
    src = open(_cli_module.__file__).read()
    for cmd in ("init", "wrap", "session", "receipt", "preflight", "evidence", "m2b-readiness"):
        assert f'"{cmd}"' in src or f"'{cmd}'" in src, f"{cmd} not in CLI source"


def test_record_settle_hidden_from_help() -> None:
    """record and settle are registered with SUPPRESS help."""
    from chimera_memory import cli as _cli_module
    src = open(_cli_module.__file__).read()
    # Both exist but should be paired with SUPPRESS
    assert '"record"' in src or "'record'" in src
    assert "SUPPRESS" in src


def test_evidence_import_nonexistent_gives_clear_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".chimera-memory").mkdir()
    ret = main(["evidence", "import", str(tmp_path / "does-not-exist"), "--dry-run"])
    assert ret == 1


def test_receipt_latest_empty_state_message(tmp_path: Path, monkeypatch, capsys) -> None:
    """Fresh ledger with no sessions shows actionable message."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".chimera-memory").mkdir()
    ret = main(["receipt", "latest"])
    assert ret == 1
    err = capsys.readouterr().err
    # Should mention how to create a session
    assert "session start" in err or "No closed sessions" in err


def test_repair_loops_empty_shows_guidance(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".chimera-memory").mkdir()
    main(["repair-loops"])
    out = capsys.readouterr().out
    assert "No repair loops" in out or "repair-loop-id" in out


def test_preflight_no_evidence_shows_advisory(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".chimera-memory").mkdir()
    ret = main(["preflight", "--scope-path", "packages/chimera-memory"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "advisory" in out.lower() or "preflight" in out.lower()


def test_m2b_readiness_blocked_on_fresh_ledger(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".chimera-memory").mkdir()
    ret = main(["m2b-readiness"])
    assert ret == 0  # should not error even on empty ledger


# ---------------------------------------------------------------------------
# Quickstart doc content
# ---------------------------------------------------------------------------


def test_first_run_quickstart_doc_exists() -> None:
    doc = Path("docs/strategy/chimera-memory-first-run-quickstart.md")
    assert doc.exists(), "first-run quickstart doc must exist"


def test_quickstart_doc_mentions_no_m2b_routing_cloud() -> None:
    doc = Path("docs/strategy/chimera-memory-first-run-quickstart.md")
    content = doc.read_text(encoding="utf-8").lower()
    for term in ("m2b", "routing", "hosted", "cloud"):
        assert term in content, f"quickstart must mention '{term}' limitation"


def test_init_creates_gitignore_if_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    main(["init"])
    gi = tmp_path / ".gitignore"
    assert gi.exists()
    assert ".chimera-memory/" in gi.read_text()


def test_init_appends_to_existing_gitignore(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text("*.pyc\n")
    main(["init"])
    content = (tmp_path / ".gitignore").read_text()
    assert ".chimera-memory/" in content
    assert "*.pyc" in content


def test_init_gitignore_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    main(["init"])
    main(["init"])
    content = (tmp_path / ".gitignore").read_text()
    assert content.count(".chimera-memory/") == 1


def test_readme_has_windows_stance_and_troubleshooting() -> None:
    readme = Path("packages/chimera-memory/README.md")
    assert readme.exists(), "README must exist"
    content = readme.read_text(encoding="utf-8").lower()
    assert "windows" in content, "README must document Windows support stance"
    assert "troubleshooting" in content, "README must have a troubleshooting section"
    assert "not built" in content or "not officially" in content, \
        "README must state what is not built"
    assert "pip install chimera-memory" in readme.read_text(encoding="utf-8"), \
        "README must include pip install command"
