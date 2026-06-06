from __future__ import annotations

import re
import subprocess
import sys
import time
from dataclasses import dataclass, field

_EXCERPT_MAX = 2000
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\(B")


@dataclass(frozen=True)
class PytestRunResult:
    command: list[str]
    exit_code: int
    observed: bool
    duration_seconds: float
    stdout_excerpt: str = field(default="")
    stderr_excerpt: str = field(default="")


def run_pytest(command_args: list[str]) -> PytestRunResult:
    """Run pytest and capture output for witness storage while showing it live.

    Captures stdout+stderr as bounded, redacted excerpts for failure witnesses.
    Output is printed to the terminal so the developer sees it.
    """
    from chimera_memory.redaction import redact

    command = _pytest_command(command_args)
    started_at = time.monotonic()
    result = subprocess.run(
        command, shell=False, capture_output=True, text=True, errors="replace"
    )
    duration_seconds = time.monotonic() - started_at
    exit_code = int(result.returncode)

    # Print to terminal so developer sees output
    if result.stdout:
        sys.stdout.write(result.stdout)
        sys.stdout.flush()
    if result.stderr:
        sys.stderr.write(result.stderr)
        sys.stderr.flush()

    stdout_raw = _ANSI_RE.sub("", (result.stdout or "")[-_EXCERPT_MAX:])
    stderr_raw = _ANSI_RE.sub("", (result.stderr or "")[-_EXCERPT_MAX:])
    return PytestRunResult(
        command=command,
        exit_code=exit_code,
        observed=exit_code == 0,
        duration_seconds=duration_seconds,
        stdout_excerpt=redact(stdout_raw),
        stderr_excerpt=redact(stderr_raw),
    )


def run_command(command_args: list[str]) -> PytestRunResult:
    """Run an arbitrary command and return a result shaped like PytestRunResult.

    exit code 0 → observed=True (VALIDATED)
    exit code nonzero → observed=False (CONTRADICTED)
    Captures stdout/stderr as bounded excerpts (last _EXCERPT_MAX chars).
    """
    from chimera_memory.redaction import redact

    started_at = time.monotonic()
    result = subprocess.run(
        command_args, shell=False, capture_output=True, text=True, errors="replace"
    )
    duration_seconds = time.monotonic() - started_at
    exit_code = int(result.returncode)
    return PytestRunResult(
        command=command_args,
        exit_code=exit_code,
        observed=exit_code == 0,
        duration_seconds=duration_seconds,
        stdout_excerpt=redact(_ANSI_RE.sub("", (result.stdout or "")[-_EXCERPT_MAX:])),
        stderr_excerpt=redact(_ANSI_RE.sub("", (result.stderr or "")[-_EXCERPT_MAX:])),
    )


def _pytest_command(command_args: list[str]) -> list[str]:
    if not command_args or command_args[0] != "pytest":
        raise ValueError("wrap supports pytest commands only")
    return [sys.executable, "-m", "pytest", *command_args[1:]]
