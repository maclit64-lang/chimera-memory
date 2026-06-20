from __future__ import annotations

import subprocess
import sys


def test_python_m_chimera_memory_help_runs() -> None:
    """`python -m chimera_memory --help` behaves like the console script."""
    result = subprocess.run(
        [sys.executable, "-m", "chimera_memory", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "chimera-memory" in result.stdout


def test_python_m_chimera_memory_version_runs() -> None:
    """`python -m chimera_memory --version` exits 0 and prints the version."""
    result = subprocess.run(
        [sys.executable, "-m", "chimera_memory", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "chimera-memory" in result.stdout
