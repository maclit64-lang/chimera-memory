from __future__ import annotations

import ast
from pathlib import Path


def test_package_imports_public_api() -> None:
    import chimera_memory

    expected_api = {
        "AttributionConfidence",
        "FinalStatus",
        "IdentitySource",
        "MemoryStore",
        "Session",
        "build_dogfood_status",
        "build_reliability_summary",
        "build_receipt",
        "detect_drift",
        "end_session",
        "export_report",
        "format_receipt_json",
        "format_receipt_markdown",
        "format_receipt_text",
        "get_current_session",
        "get_session",
        "list_sessions",
        "new_session_id",
        "query_memory",
        "record_claim",
        "settle_claim",
        "start_session",
    }

    assert set(chimera_memory.__all__) == expected_api
    assert "all" not in vars(chimera_memory)
    for name in expected_api:
        assert callable(getattr(chimera_memory, name))


def test_cli_help_lists_m0_m1_commands(capsys) -> None:
    from chimera_memory.cli import main

    assert main(["--help"]) == 0
    output = capsys.readouterr().out

    for command in ("init", "record", "settle", "report", "drift", "wrap"):
        assert command in output


def test_cli_help_lists_session_receipt_commands(capsys) -> None:
    """M1-4: session start/end/list/current and receipt show are wired."""
    from chimera_memory.cli import main

    assert main(["--help"]) == 0
    output = capsys.readouterr().out
    for command in ("session", "receipt"):
        assert command in output

    # session subcommands
    assert main(["session", "--help"]) == 0
    output = capsys.readouterr().out
    for sub in ("start", "end", "list", "current"):
        assert sub in output

    # receipt subcommand
    assert main(["receipt", "--help"]) == 0
    output = capsys.readouterr().out
    assert "show" in output


def test_no_runtime_or_apps_api_imports_in_package_source() -> None:
    source_root = Path(__file__).parents[1] / "src" / "chimera_memory"
    forbidden_roots = {
        "api",
        "apps",
        "asyncpg",
        "chimera_core_runtime",
        "sqlalchemy",
    }

    assert source_root.exists()

    for source_file in source_root.rglob("*.py"):
        tree = ast.parse(source_file.read_text(), filename=str(source_file))
        for node in ast.walk(tree):
            imported_roots: list[str] = []
            if isinstance(node, ast.Import):
                imported_roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_roots = [node.module.split(".")[0]]

            forbidden = forbidden_roots.intersection(imported_roots)
            assert not forbidden, f"{source_file} imports forbidden modules: {sorted(forbidden)}"


def test_public_api_exports_build_dogfood_status() -> None:
    from chimera_memory import build_dogfood_status
    assert callable(build_dogfood_status)


def test_public_api_exports_format_receipt_markdown() -> None:
    from chimera_memory import format_receipt_markdown
    assert callable(format_receipt_markdown)


def test_public_api_all_includes_status_and_markdown_helpers() -> None:
    import chimera_memory
    assert "build_dogfood_status" in chimera_memory.__all__
    assert "format_receipt_markdown" in chimera_memory.__all__
