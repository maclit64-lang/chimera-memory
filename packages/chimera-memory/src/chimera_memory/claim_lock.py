"""Claim-locked evidence foundation for Chimera Memory.

A *claim lock* is a sealed, scope-bound prediction recorded **before** an agent
edits code. It states intent, a declared scope path, a pre-committed
*falsifier* (the check that would disprove the claim), optional *must-not-break*
checks, and a predicted outcome. After the work is done, the claim is *settled*
**only** against the pre-committed checks — settlement can never substitute a
different check.

Honesty contract
----------------
This module produces *settled evidence*, not proof of code correctness. Scope
coverage is path-based: a changed file is "covered by declared claim scope" if
it lives under ``scope_path``. That is an honest, mechanical statement — it is
not a guarantee that the file is tested or correct.

Design notes
------------
* Records are stored append-only in ``.chimera-memory/claim_locks.jsonl``. The
  initial ``LOCKED`` record and any later settlement record share one
  ``claim_id``; the latest record wins. History is never mutated.
* Commands are always ``list[str]`` and are executed with ``shell=False``.
  Shell strings are rejected to avoid injection.
* The schema carries an ``attribution`` block with multi-terminal seams
  (terminal_id, worktree_path, branch, session_id, agent/model/harness). Unknown
  values are recorded honestly as null/"unknown" — attribution is never faked.
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import tomllib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chimera_memory.adapters.git import (
    git_branch,
    git_changed_files_since,
    git_dirty_files,
    git_head_sha,
)
from chimera_memory.adapters.pytest_ci import run_command
from chimera_memory.storage import MemoryStore

CLAIM_LOCK_SCHEMA_VERSION = 1
SEAL_VERSION = 1

# Settlement statuses (required set for v0.22).
STATUS_LOCKED = "LOCKED"
STATUS_VALIDATED = "VALIDATED"
STATUS_CONTRADICTED = "CONTRADICTED"
STATUS_UNSETTLED = "UNSETTLED"
STATUS_SCOPE_DRIFT = "SCOPE_DRIFT"

# Quality bands (WEAK_FALSIFIER / POST_HOC are surfaced as warnings / mode).
QUALITY_STRONG = "strong"
QUALITY_MEDIUM = "medium"
QUALITY_WEAK = "weak"
QUALITY_UNKNOWN = "unknown"

WARNING_WEAK_FALSIFIER = "WEAK_FALSIFIER"
WARNING_DIRTY_PRE_EDIT = "DIRTY_PRE_EDIT_STATE"
WARNING_NO_GIT = "NO_GIT_PRE_EDIT_STATE"

# Characters that imply shell interpretation — disallowed in command tokens.
_SHELL_METACHARS = set(";|&$`<>(){}*?!\n")

# Commands that are too trivial to falsify a claim on their own.
_WEAK_COMMANDS = {"true", "echo", ":", "cat", "ls", "pwd"}


class ClaimError(Exception):
    """Raised for invalid claim specs or unsafe command shapes."""


# The local ledger directory must never appear in evidence/change sets.
LEDGER_DIRNAME = ".chimera-memory"


def exclude_ledger_paths(paths: list[str]) -> list[str]:
    """Drop any path inside the local ``.chimera-memory/`` ledger directory.

    The ledger is private bookkeeping; it is never part of the reviewed change
    set, regardless of whether the repo has gitignored it yet.
    """
    return [
        p
        for p in paths
        if p != LEDGER_DIRNAME and not p.replace("\\", "/").startswith(LEDGER_DIRNAME + "/")
    ]


# ---------------------------------------------------------------------------
# Command normalisation
# ---------------------------------------------------------------------------
def validate_command_list(raw: Any) -> list[str]:
    """Validate and return a ``list[str]`` command, or raise ClaimError.

    Used for TOML/flag inputs that are already in list form. A bare shell
    string is rejected (prefer-rejection policy for v0.22).

    Note: individual list elements may legitimately contain characters like
    ``;`` or ``|`` (e.g. ``python -c "import sys; sys.exit(0)"``). Because every
    command is executed with ``shell=False``, list elements are passed as
    literal argv entries and are never shell-interpreted — so there is no
    injection risk for the list form. The shell-metacharacter guard applies
    only when parsing a *string* into a list (see
    :func:`safe_command_from_string`).
    """
    if isinstance(raw, str):
        suggestion = shlex.split(raw)
        raise ClaimError(
            "command must be a list of strings, not a shell string. "
            f"Use an explicit list, e.g. {suggestion!r}."
        )
    if not isinstance(raw, list) or not raw:
        raise ClaimError("command must be a non-empty list of strings")
    out: list[str] = []
    for tok in raw:
        if not isinstance(tok, str) or tok == "":
            raise ClaimError("command tokens must be non-empty strings")
        out.append(tok)
    return out


def safe_command_from_string(raw: str) -> list[str]:
    """Parse a flag-supplied string into a safe ``list[str]`` or raise.

    Splits with :func:`shlex.split` and rejects any token containing shell
    metacharacters. The result is stored as an explicit list — the original
    shell string is never persisted as an executable contract.
    """
    if any(ch in _SHELL_METACHARS for ch in raw):
        raise ClaimError(
            f"command {raw!r} contains shell metacharacters; "
            "use --from-file with an explicit command list instead"
        )
    tokens = shlex.split(raw)
    if not tokens:
        raise ClaimError("command string is empty")
    return tokens


# ---------------------------------------------------------------------------
# Claim spec + sealing
# ---------------------------------------------------------------------------
@dataclass
class ClaimSpec:
    """The author-provided, sealable content of a claim."""

    intent: str
    scope_path: str
    predicted_outcome: str = "all pass"
    falsifiers: list[list[str]] = field(default_factory=list)
    must_not_break: list[list[str]] = field(default_factory=list)

    def sealed_payload(self) -> dict[str, Any]:
        """The canonical, hashable content of the claim (excludes id/time)."""
        return {
            "intent": self.intent,
            "scope_path": self.scope_path,
            "predicted_outcome": self.predicted_outcome,
            "falsifiers": [{"command": cmd} for cmd in self.falsifiers],
            "must_not_break": [{"command": cmd} for cmd in self.must_not_break],
        }


def load_spec_from_toml(path: Path) -> ClaimSpec:
    """Load a :class:`ClaimSpec` from a ``claim.toml`` file.

    Expected shape::

        intent = "fix checkout null dereference"
        scope_path = "packages/cart"
        predicted_outcome = "all pass"

        [[falsifiers]]
        command = ["pytest", "tests/test_checkout.py::test_empty_cart"]

        [[must_not_break]]
        command = ["pytest", "tests/test_cart.py"]
    """
    if not path.exists():
        raise ClaimError(f"claim file not found: {path}")
    with path.open("rb") as fh:
        data = tomllib.load(fh)

    intent = data.get("intent")
    scope_path = data.get("scope_path")
    if not isinstance(intent, str) or not intent.strip():
        raise ClaimError("claim file must set a non-empty 'intent'")
    if not isinstance(scope_path, str) or not scope_path.strip():
        raise ClaimError("claim file must set a non-empty 'scope_path'")
    predicted = data.get("predicted_outcome", "all pass")
    if not isinstance(predicted, str):
        raise ClaimError("'predicted_outcome' must be a string")

    falsifiers = _load_command_section(data.get("falsifiers", []), "falsifiers")
    must_not_break = _load_command_section(
        data.get("must_not_break", []), "must_not_break"
    )
    return ClaimSpec(
        intent=intent.strip(),
        scope_path=_normalize_scope(scope_path),
        predicted_outcome=predicted,
        falsifiers=falsifiers,
        must_not_break=must_not_break,
    )


def _load_command_section(section: Any, name: str) -> list[list[str]]:
    if not isinstance(section, list):
        raise ClaimError(f"'{name}' must be an array of tables with a 'command' list")
    out: list[list[str]] = []
    for entry in section:
        if not isinstance(entry, dict) or "command" not in entry:
            raise ClaimError(f"each '{name}' entry must have a 'command' field")
        out.append(validate_command_list(entry["command"]))
    return out


def _normalize_scope(scope_path: str) -> str:
    """Normalise a scope path to a forward-slash, no-trailing-slash form."""
    cleaned = scope_path.strip().replace("\\", "/")
    if cleaned in ("", "."):
        return "."
    return cleaned.rstrip("/")


def compute_payload_hash(spec: ClaimSpec) -> str:
    """Stable sha256 over the canonical sealed payload (sorted keys)."""
    canonical = json.dumps(spec.sealed_payload(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def assess_quality(spec: ClaimSpec) -> tuple[str, list[str]]:
    """Return (claim_quality, warnings) using honest, mechanical heuristics."""
    warnings: list[str] = []
    if not spec.falsifiers:
        warnings.append(WARNING_WEAK_FALSIFIER)
        return QUALITY_WEAK, warnings

    falsifier_heads = {cmd[0] for cmd in spec.falsifiers if cmd}
    if falsifier_heads and falsifier_heads <= _WEAK_COMMANDS:
        warnings.append(WARNING_WEAK_FALSIFIER)
        return QUALITY_WEAK, warnings

    if not spec.must_not_break:
        return QUALITY_MEDIUM, warnings
    return QUALITY_STRONG, warnings


# ---------------------------------------------------------------------------
# Attribution (multi-terminal readiness seam)
# ---------------------------------------------------------------------------
def build_attribution(store: MemoryStore, root: Path) -> dict[str, Any]:
    """Build the attribution block, honestly recording unknowns as null.

    Precedence for agent/model/harness: active session > environment > null.
    ``attribution_confidence`` reflects the source and is never inflated.
    """
    session = store.current_session()
    branch = git_branch(root)

    agent_name: str | None = None
    model_name: str | None = None
    harness_id: str | None = None
    session_id: str | None = None
    confidence = "unknown"

    if session:
        session_id = session.get("session_id")
        agent_name = _none_if_unknown(session.get("agent_app"))
        model_name = _none_if_unknown(session.get("model"))
        harness_id = _none_if_unknown(session.get("harness_id"))
        branch = session.get("branch") or branch
        confidence = "session" if (agent_name or model_name) else "unknown"

    # Environment fallback — only fills genuinely-empty fields. Never fabricates.
    env_agent = os.environ.get("AGENT_NAME") or os.environ.get("CHIMERA_AGENT_NAME")
    env_model = os.environ.get("MODEL_NAME") or os.environ.get("CHIMERA_MODEL_NAME")
    env_harness = os.environ.get("HARNESS_ID") or os.environ.get("CHIMERA_HARNESS_ID")
    if agent_name is None and env_agent:
        agent_name = env_agent
        confidence = "env" if confidence == "unknown" else confidence
    if model_name is None and env_model:
        model_name = env_model
        confidence = "env" if confidence == "unknown" else confidence
    if harness_id is None and env_harness:
        harness_id = env_harness

    return {
        "session_id": session_id,
        "terminal_id": os.environ.get("CHIMERA_TERMINAL_ID"),
        "worktree_path": str(root),
        "branch": branch,
        "agent_name": agent_name,
        "model_name": model_name,
        "harness_id": harness_id,
        "attribution_confidence": confidence,
    }


def _none_if_unknown(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "unknown":
        return None
    return text


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------
def lock_claim(
    store: MemoryStore,
    spec: ClaimSpec,
    *,
    root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Seal a claim before edits and append a ``LOCKED`` record. Returns it.

    Runs :func:`validate_claim_spec` before sealing. Hard errors raise
    :class:`ClaimError`. Warnings are stored in the claim's quality block.
    """
    root = root or Path.cwd()

    # Validate before sealing — hard errors prevent locking.
    validation = validate_claim_spec(spec, root=root, check_git_state=False)
    if not validation["valid"]:
        raise ClaimError(
            "claim spec has errors:\n"
            + "\n".join(f"  - {e}" for e in validation["errors"])
        )
    validation_warnings: list[str] = validation["warnings"]
    created_at = (now or datetime.now(UTC)).isoformat()
    claim_id = "clm_" + uuid.uuid4().hex[:16]

    dirty_state, tracked_dirty = git_dirty_files(root)
    git_head = git_head_sha(root)

    quality, warnings = assess_quality(spec)
    # Merge in validation_warnings (broad-command, missing-must-not-break, etc.)
    # avoiding duplicates while preserving order.
    seen: set[str] = set(warnings)
    for w in validation_warnings:
        if w not in seen:
            warnings = [*warnings, w]
            seen.add(w)
    if dirty_state == "dirty":
        dirty_warning = WARNING_DIRTY_PRE_EDIT
        if dirty_warning not in seen:
            warnings = [*warnings, dirty_warning]
    if git_head is None:
        no_git_warning = WARNING_NO_GIT
        if no_git_warning not in seen:
            warnings = [*warnings, no_git_warning]

    record: dict[str, Any] = {
        "schema_version": CLAIM_LOCK_SCHEMA_VERSION,
        "record_type": "claim_lock",
        "claim_id": claim_id,
        "created_at": created_at,
        "intent": spec.intent,
        "scope_path": spec.scope_path,
        "predicted_outcome": spec.predicted_outcome,
        "falsifiers": [{"command": cmd} for cmd in spec.falsifiers],
        "must_not_break": [{"command": cmd} for cmd in spec.must_not_break],
        "pre_edit_state": {
            "git_head": git_head,
            "tracked_dirty_files": tracked_dirty,
            "dirty_state": dirty_state,
        },
        "seal": {
            "payload_hash": compute_payload_hash(spec),
            "sealed_at": created_at,
            "seal_version": SEAL_VERSION,
        },
        "attribution": build_attribution(store, root),
        "quality": {
            "claim_quality": quality,
            "warnings": warnings,
        },
        "settlement": {
            "status": STATUS_LOCKED,
            "settled_at": None,
            "commands": [],
            "changed_files": [],
            "evidence_dark_files": [],
            "scope_drift_files": [],
        },
    }
    store.append_claim_lock(record)
    return record


# ---------------------------------------------------------------------------
# Settle
# ---------------------------------------------------------------------------
def file_under_scope(path: str, scope_path: str) -> bool:
    """Path-based coverage: is ``path`` under the declared ``scope_path``?"""
    norm = path.replace("\\", "/").strip()
    scope = _normalize_scope(scope_path)
    if scope == ".":
        return True
    return norm == scope or norm.startswith(scope + "/")


def settle_claim(
    store: MemoryStore,
    claim_id: str,
    *,
    root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Settle a locked claim against its pre-committed checks only.

    Runs each sealed falsifier and must-not-break command (never a substitute),
    captures changed files since the pre-edit git state, classifies scope drift,
    and appends an updated record. Returns the settled record.
    """
    root = root or Path.cwd()
    record = store.latest_claim_lock(claim_id)
    if record is None:
        raise ClaimError(f"no claim found with id {claim_id!r}")

    settled_at = (now or datetime.now(UTC)).isoformat()
    falsifiers = [entry["command"] for entry in record.get("falsifiers", [])]
    must_not_break = [entry["command"] for entry in record.get("must_not_break", [])]

    command_results: list[dict[str, Any]] = []
    any_failed = False
    any_unrunnable = False

    for cmd in falsifiers:
        result = _run_check(cmd, role="falsifier")
        command_results.append(result)
        any_failed = any_failed or result["outcome"] == "FAIL"
        any_unrunnable = any_unrunnable or result["outcome"] == "UNRUNNABLE"

    for cmd in must_not_break:
        result = _run_check(cmd, role="must_not_break")
        command_results.append(result)
        any_failed = any_failed or result["outcome"] == "FAIL"
        any_unrunnable = any_unrunnable or result["outcome"] == "UNRUNNABLE"

    # Changed files since the sealed pre-edit git head.
    pre_head = record.get("pre_edit_state", {}).get("git_head")
    if pre_head:
        changed_files = git_changed_files_since(pre_head, root)
    else:
        # No sealed git head: fall back to current dirty/untracked files.
        _, tracked = git_dirty_files(root)
        changed_files = sorted(set(tracked))
    changed_files = exclude_ledger_paths(changed_files)

    scope_path = record.get("scope_path", ".")
    scope_drift_files = [
        f for f in changed_files if not file_under_scope(f, scope_path)
    ]

    status = _resolve_status(
        had_falsifier=bool(falsifiers),
        any_failed=any_failed,
        any_unrunnable=any_unrunnable,
        has_scope_drift=bool(scope_drift_files),
    )

    settled = dict(record)
    settled["settlement"] = {
        "status": status,
        "settled_at": settled_at,
        "commands": command_results,
        "changed_files": changed_files,
        "evidence_dark_files": [],  # aggregate concept; populated by the X-Ray
        "scope_drift_files": scope_drift_files,
    }
    store.append_claim_lock(settled)
    return settled


def _resolve_status(
    *,
    had_falsifier: bool,
    any_failed: bool,
    any_unrunnable: bool,
    has_scope_drift: bool,
) -> str:
    """Status precedence: CONTRADICTED > UNSETTLED > SCOPE_DRIFT > VALIDATED."""
    if any_failed:
        return STATUS_CONTRADICTED
    if any_unrunnable or not had_falsifier:
        return STATUS_UNSETTLED
    if has_scope_drift:
        return STATUS_SCOPE_DRIFT
    return STATUS_VALIDATED


def _run_check(cmd: list[str], *, role: str) -> dict[str, Any]:
    """Run one pre-committed check; classify PASS / FAIL / UNRUNNABLE."""
    entry: dict[str, Any] = {
        "command": cmd,
        "role": role,
    }
    try:
        result = run_command(cmd)
    except FileNotFoundError as exc:
        entry.update(
            outcome="UNRUNNABLE",
            exit_code=None,
            error=f"command not found: {exc.filename or cmd[0]}",
        )
        return entry
    except OSError as exc:  # pragma: no cover - defensive
        entry.update(outcome="UNRUNNABLE", exit_code=None, error=str(exc))
        return entry

    entry.update(
        outcome="PASS" if result.exit_code == 0 else "FAIL",
        exit_code=result.exit_code,
        duration_seconds=round(result.duration_seconds, 4),
        stdout_excerpt=result.stdout_excerpt,
        stderr_excerpt=result.stderr_excerpt,
    )
    return entry


# ---------------------------------------------------------------------------
# Claim contract validation (dry-run)
# ---------------------------------------------------------------------------

# Tools where omitting an explicit target/path makes the command's behaviour
# repo-config-dependent. We warn (never block) because some repos intentionally
# rely on tool-level defaults.
_BROAD_TOOL_PATTERNS: list[tuple[tuple[str, ...], str]] = [
    # bare form
    (("mypy",), "mypy"),
    (("ruff",), "ruff"),
    (("ruff", "check"), "ruff check"),
    (("pytest",), "pytest"),
    # uv run <tool>
    (("uv", "run", "mypy"), "uv run mypy"),
    (("uv", "run", "ruff"), "uv run ruff"),
    (("uv", "run", "ruff", "check"), "uv run ruff check"),
    (("uv", "run", "pytest"), "uv run pytest"),
    # python -m <tool>
    (("python", "-m", "mypy"), "python -m mypy"),
    (("python", "-m", "pytest"), "python -m pytest"),
    (("python3", "-m", "mypy"), "python3 -m mypy"),
    (("python3", "-m", "pytest"), "python3 -m pytest"),
]

WARNING_BROAD_COMMAND = "BROAD_COMMAND"
WARNING_MISSING_MUST_NOT_BREAK = "MISSING_MUST_NOT_BREAK"
WARNING_BROAD_SCOPE = "BROAD_SCOPE_PATH"
WARNING_DIRTY_STATE = "DIRTY_PRE_EDIT_STATE"
WARNING_NO_GIT = "NO_GIT_PRE_EDIT_STATE"


def _check_command_breadth(cmd: list[str]) -> str | None:
    """Return a warning string if ``cmd`` matches a known broad-tool pattern."""
    for pattern, label in _BROAD_TOOL_PATTERNS:
        if tuple(cmd) == pattern:
            return (
                f"command `{' '.join(cmd)}` may be broad or config-dependent because "
                "it has no explicit target/path. This may be valid for this repo, but "
                "explicit paths make claim settlement more reviewable. "
                f"Consider: `{label} <path/to/target>`."
            )
    return None


def validate_claim_spec(
    spec: ClaimSpec,
    *,
    root: Path | None = None,
    check_git_state: bool = True,
) -> dict[str, Any]:
    """Dry-run validation of a :class:`ClaimSpec`.

    Returns a result dict with shape::

        {
          "valid": bool,         # True when no *hard* errors
          "errors": list[str],   # Hard errors — block locking
          "warnings": list[str], # Soft warnings — stored on lock, don't block
        }

    Does **not** write to ``.chimera-memory`` or create any claim record.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Hard errors
    if not spec.intent.strip():
        errors.append("intent must be a non-empty string")
    if not spec.scope_path.strip() or spec.scope_path == "":
        errors.append("scope_path must be a non-empty string")
    if not spec.falsifiers:
        errors.append("at least one [[falsifiers]] entry with a command list is required")
    for i, cmd in enumerate(spec.falsifiers):
        if not isinstance(cmd, list) or not cmd:
            errors.append(f"falsifiers[{i}].command must be a non-empty list of strings")
        elif not all(isinstance(t, str) for t in cmd):
            errors.append(f"falsifiers[{i}].command tokens must all be strings")
    for i, cmd in enumerate(spec.must_not_break):
        if not isinstance(cmd, list) or not cmd:
            errors.append(
                f"must_not_break[{i}].command must be a non-empty list of strings"
            )
        elif not all(isinstance(t, str) for t in cmd):
            errors.append(f"must_not_break[{i}].command tokens must all be strings")

    # Warnings
    if spec.scope_path in (".", ""):
        warnings.append(
            f"{WARNING_BROAD_SCOPE}: scope_path '.' covers the entire repo. "
            "Narrowing the scope makes scope-drift detection more useful."
        )
    if not spec.must_not_break:
        warnings.append(
            f"{WARNING_MISSING_MUST_NOT_BREAK}: no must_not_break checks declared. "
            "Adding regression checks strengthens the evidence record."
        )

    # Per-command breadth warnings
    for cmd in spec.falsifiers:
        msg = _check_command_breadth(cmd)
        if msg:
            warnings.append(f"{WARNING_BROAD_COMMAND}: {msg}")
    for cmd in spec.must_not_break:
        msg = _check_command_breadth(cmd)
        if msg:
            warnings.append(f"{WARNING_BROAD_COMMAND}: {msg}")

    # Git state (informational only — soft warning)
    if check_git_state and not errors:
        resolve_root = root or Path.cwd()
        dirty_state, _ = git_dirty_files(resolve_root)
        if dirty_state == "dirty":
            warnings.append(
                f"{WARNING_DIRTY_STATE}: working tree is dirty at validation time. "
                "Consider locking the claim from a clean state for the cleanest evidence."
            )
        elif dirty_state == "unknown":
            warnings.append(
                f"{WARNING_NO_GIT}: git is not available or this is not a git repo."
            )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Agent-seam auto-lock builder (v0.23)
# ---------------------------------------------------------------------------

WARNING_AUTO_FROM_CHECKS = "AUTO_FROM_CHECKS_CONFIG"
WARNING_MISSING_TARGETED_FALSIFIER = "MISSING_TARGETED_FALSIFIER"
_DEFAULT_PREDICTED_OUTCOME = "pre-committed checks pass"


def _parse_json_commands(raw: str, field: str) -> list[list[str]]:
    """Parse a JSON string into a list of command arrays.

    Expected shape: ``[["cmd", "arg1"], ["cmd2"]]``.
    Rejects shell strings, non-list shapes, and non-string tokens.
    """
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ClaimError(
            f"{field}: invalid JSON — {exc}. "
            "Expected a JSON array of string arrays, e.g. "
            '\'[["uv","run","pytest","tests/test_x.py"]]\'.'
        ) from exc
    if not isinstance(parsed, list):
        raise ClaimError(
            f"{field}: must be a JSON array of command arrays, got {type(parsed).__name__}."
        )
    result: list[list[str]] = []
    for i, item in enumerate(parsed):
        if not isinstance(item, list):
            raise ClaimError(
                f"{field}[{i}]: each element must be a list of strings, "
                f"got {type(item).__name__}. Shell strings are not accepted."
            )
        result.append(validate_command_list(item))
    return result


def build_claim_spec_from_auto_inputs(
    *,
    # CLI flags — each overrides the corresponding env var when not None/empty.
    intent: str | None = None,
    scope_path: str | None = None,
    falsifiers_json: str | None = None,
    must_not_break_json: str | None = None,
    predicted_outcome: str | None = None,
    # Store for session-aware defaults (optional; no-op if None).
    store: MemoryStore | None = None,
    root: Path | None = None,
    # Allow fallback to checks.toml when no falsifier source provided.
    from_checks: bool = False,
    checks_config_path: Path | None = None,
) -> tuple[ClaimSpec, dict[str, Any]]:
    """Build a :class:`ClaimSpec` from env vars / flags (no claim.toml needed).

    Returns ``(spec, extra_meta)`` where ``extra_meta`` carries
    ``auto_lock=True`` and any additional context for the JSON response.

    Precedence (highest → lowest):
      1. CLI flag argument
      2. ``CHIMERA_*`` environment variable
      3. Active session field (scope only)
      4. Hard-coded default ("." scope, empty must-not-break)

    Raises :class:`ClaimError` on hard validation failures.
    """
    def _env(key: str) -> str | None:
        v = os.environ.get(key, "").strip()
        return v or None

    # ── intent ──────────────────────────────────────────────────────────────
    resolved_intent = intent or _env("CHIMERA_INTENT")
    if not resolved_intent:
        raise ClaimError(
            "intent is required for --auto. "
            "Set CHIMERA_INTENT or pass --intent."
        )

    # ── scope_path ──────────────────────────────────────────────────────────
    resolved_scope = scope_path or _env("CHIMERA_SCOPE_PATH")
    if not resolved_scope and store is not None:
        session = store.current_session()
        if session:
            resolved_scope = session.get("task_label")  # best-effort; may be None
    if not resolved_scope:
        resolved_scope = "."

    # ── predicted_outcome ───────────────────────────────────────────────────
    resolved_predicted = (
        predicted_outcome
        or _env("CHIMERA_PREDICTED_OUTCOME")
        or _DEFAULT_PREDICTED_OUTCOME
    )

    # ── falsifiers ──────────────────────────────────────────────────────────
    raw_falsifiers = falsifiers_json or _env("CHIMERA_FALSIFIERS_JSON")
    resolved_falsifiers: list[list[str]] = []
    extra_warnings: list[str] = []

    if raw_falsifiers:
        resolved_falsifiers = _parse_json_commands(raw_falsifiers, "CHIMERA_FALSIFIERS_JSON")
    elif from_checks:
        # Fallback: read checks.toml and use its commands as candidates.
        checks_path = checks_config_path or Path.cwd() / "chimera-memory.checks.toml"
        if checks_path.exists():
            import tomllib as _tomllib
            with checks_path.open("rb") as fh:
                cfg = _tomllib.load(fh)
            checks = cfg.get("checks", [])
            for check in checks:
                cmd = check.get("command")
                if isinstance(cmd, list):
                    try:
                        resolved_falsifiers.append(validate_command_list(cmd))
                    except ClaimError:
                        pass
            extra_warnings.append(
                f"{WARNING_AUTO_FROM_CHECKS}: falsifiers generated from "
                f"{checks_path.name}. These are broad checks, not targeted falsifiers. "
                f"Consider providing CHIMERA_FALSIFIERS_JSON for a more specific claim."
            )
            extra_warnings.append(
                f"{WARNING_MISSING_TARGETED_FALSIFIER}: no targeted falsifier was "
                "explicitly provided. The claim is generated from check-suite commands."
            )
        else:
            raise ClaimError(
                "No falsifier source: --from-checks requested but "
                f"{checks_path} does not exist."
            )
    else:
        raise ClaimError(
            "No falsifier source provided for --auto. "
            "Set CHIMERA_FALSIFIERS_JSON or pass --falsifiers-json."
        )

    # ── must_not_break ───────────────────────────────────────────────────────
    raw_mnb = must_not_break_json or _env("CHIMERA_MUST_NOT_BREAK_JSON")
    resolved_mnb: list[list[str]] = []
    if raw_mnb:
        resolved_mnb = _parse_json_commands(raw_mnb, "CHIMERA_MUST_NOT_BREAK_JSON")

    spec = ClaimSpec(
        intent=resolved_intent.strip(),
        scope_path=_normalize_scope(resolved_scope),
        predicted_outcome=resolved_predicted,
        falsifiers=resolved_falsifiers,
        must_not_break=resolved_mnb,
    )
    extra_meta: dict[str, Any] = {
        "auto_lock": True,
        "from_checks": from_checks,
        "extra_warnings": extra_warnings,
        "generated_spec": {
            "intent": spec.intent,
            "scope_path": spec.scope_path,
            "predicted_outcome": spec.predicted_outcome,
            "falsifiers": [{"command": cmd} for cmd in spec.falsifiers],
            "must_not_break": [{"command": cmd} for cmd in spec.must_not_break],
        },
    }
    return spec, extra_meta
