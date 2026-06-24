"""Claude Code hook installation for Chimera Memory (v0.25+).

Provides ``chimera-memory hooks install`` which writes two hook scripts into
``.claude/hooks/`` and patches ``.claude/settings.json``.

v0.26 adds prompt-derived claim auto-lock:

  - UserPromptSubmit hook now calls ``chimera-memory hooks prompt-submit``
    which reads the prompt text, derives a conservative intent, and attempts
    to auto-lock a claim when falsifier inputs are configured.
  - Auto-lock is refused when no falsifiers are available (no false evidence).
  - Project-local config via ``.chimera/hooks.toml`` (optional).

Config precedence (highest → lowest):
  1. Explicit env vars (CHIMERA_INTENT, CHIMERA_SCOPE_PATH, etc.)
  2. .chimera/hooks.toml
  3. Prompt-derived intent (only for intent, never for falsifiers)
  4. Fallback (. scope with BROAD_SCOPE_PATH warning)

Safety invariant:
  No falsifiers configured → no auto-lock.
  Chimera never invents test commands from prompt text.
"""
from __future__ import annotations

import json
import os
import re
import stat
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_INTENT_MAX_LEN = 300
_INTENT_TRUNCATE_SUFFIX = " [truncated]"

# ---------------------------------------------------------------------------
# Intent derivation
# ---------------------------------------------------------------------------

# Phrases that indicate the prompt is directing Claude rather than describing
# the task. We strip them to extract the actual intent.
_PLEASE_PREFIXES = re.compile(
    r"^\s*(?:please\s+|can you\s+|could you\s+|i need you to\s+|i want you to\s+)",
    re.IGNORECASE,
)


def derive_intent_from_prompt(prompt_text: str) -> str:
    """Derive a conservative, deterministic intent string from a prompt.

    Rules:
    - Strip leading whitespace.
    - Remove common imperative prefixes ("Please", "Can you", etc.).
    - Collapse excessive internal whitespace.
    - Truncate to ``_INTENT_MAX_LEN`` characters.
    - Never rewrites meaning; never queries an LLM.
    """
    text = prompt_text.strip()
    if not text:
        return ""
    # Remove politeness prefixes
    text = _PLEASE_PREFIXES.sub("", text)
    # Collapse whitespace (tabs, multiple spaces, newlines → single space)
    text = re.sub(r"\s+", " ", text).strip()
    # Truncate
    if len(text) > _INTENT_MAX_LEN:
        text = text[: _INTENT_MAX_LEN - len(_INTENT_TRUNCATE_SUFFIX)] + _INTENT_TRUNCATE_SUFFIX
    return text


def extract_prompt_from_hook_input(raw: str) -> str:
    """Extract prompt text from a Claude UserPromptSubmit hook payload.

    Supports:
      {"prompt": "..."}        — standard field
      {"user_prompt": "..."}   — alternative field name
      {"messages": [...]}      — transcript shape (last user message)
      raw text                 — plain string fallback
    """
    if not raw.strip():
        return ""
    # Try JSON parsing
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # Raw text fallback
        return raw.strip()

    if not isinstance(data, dict):
        return ""

    # Direct prompt fields
    for key in ("prompt", "user_prompt", "text"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    # Transcript / messages shape — take the last user message content
    messages = data.get("messages")
    if isinstance(messages, list):
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    return content.strip()
                if isinstance(content, list):
                    parts = [
                        p.get("text", "") for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    ]
                    joined = " ".join(p for p in parts if p.strip())
                    if joined.strip():
                        return joined.strip()

    return ""


# ---------------------------------------------------------------------------
# Project config (.chimera/hooks.toml)
# ---------------------------------------------------------------------------

_HOOKS_CONFIG_PATH = Path(".chimera") / "hooks.toml"


def load_hooks_config(root: Path) -> dict[str, Any]:
    """Load .chimera/hooks.toml [claude_hooks] if present."""
    config_path = root / _HOOKS_CONFIG_PATH
    if not config_path.exists():
        return {}
    try:
        with config_path.open("rb") as fh:
            data = tomllib.load(fh)
        return data.get("claude_hooks", {})
    except Exception:  # noqa: BLE001
        return {}


def _get_commands(cfg: dict[str, Any], key: str) -> list[list[str]] | None:
    """Extract a list of command arrays from config, validating shape."""
    raw = cfg.get(key)
    if raw is None:
        return None
    if not isinstance(raw, list):
        return None
    result: list[list[str]] = []
    for item in raw:
        if isinstance(item, list) and all(isinstance(t, str) for t in item):
            result.append(item)
    return result or None


# ---------------------------------------------------------------------------
# Prompt auto-lock
# ---------------------------------------------------------------------------

def attempt_prompt_auto_lock(
    prompt_text: str,
    env: Mapping[str, str] | None = None,
    root: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Attempt to auto-lock a claim from a prompt text and env/config inputs.

    Safety invariant: if no falsifiers are available, we return locked=False
    with a clear error message. We never invent test commands.

    Returns a result dict::

        {
          "attempted": bool,
          "locked": bool,
          "claim_id": str | None,
          "intent": str,
          "warnings": list[str],
          "errors": list[str],
          "fallback_message": str | None,
          "dry_run": bool,
        }
    """
    from chimera_memory.claim_lock import (
        ClaimError,
        build_claim_spec_from_auto_inputs,
        lock_claim,
        validate_claim_spec,
    )
    from chimera_memory.storage import MemoryStore

    resolved_env: dict[str, str] = dict(env) if env is not None else dict(os.environ)
    resolved_root = root or Path.cwd()

    result: dict[str, Any] = {
        "attempted": True,
        "locked": False,
        "claim_id": None,
        "intent": "",
        "warnings": [],
        "errors": [],
        "fallback_message": None,
        "dry_run": dry_run,
    }

    # Escape hatch
    if resolved_env.get("CHIMERA_SKIP_AUTOLOCK") == "1":
        result["attempted"] = False
        result["fallback_message"] = "CHIMERA_SKIP_AUTOLOCK=1 — skipped."
        return result

    # Derive intent: env var wins, then prompt-derived
    intent = resolved_env.get("CHIMERA_INTENT", "").strip()
    derived = derive_intent_from_prompt(prompt_text)
    if not intent:
        intent = derived
    if not intent:
        result["errors"].append(
            "No intent available (prompt was empty and CHIMERA_INTENT not set)."
        )
        result["fallback_message"] = (
            "Chimera did not auto-lock: no intent could be derived from the prompt."
        )
        return result
    result["intent"] = intent

    # Check for an already-LOCKED claim — don't create duplicate by default
    if resolved_env.get("CHIMERA_HOOK_AUTOLOCK_EVERY_PROMPT") != "1":
        try:
            store = MemoryStore.from_paths(root=resolved_root)
            if store.claim_locks_path.exists():
                locked_claims = [
                    c for c in store.latest_claim_locks()
                    if c.get("settlement", {}).get("status") == "LOCKED"
                ]
                if locked_claims:
                    existing_id = locked_claims[-1]["claim_id"]
                    result["attempted"] = False
                    result["fallback_message"] = (
                        f"Existing LOCKED claim {existing_id} found. "
                        "Chimera will settle it at Stop."
                    )
                    return result
        except Exception:  # noqa: BLE001
            pass

    # Resolve falsifiers: env > config (never invented)
    cfg = load_hooks_config(resolved_root)
    falsifiers_json = resolved_env.get("CHIMERA_FALSIFIERS_JSON", "")
    mnb_json = resolved_env.get("CHIMERA_MUST_NOT_BREAK_JSON", "")
    scope = resolved_env.get("CHIMERA_SCOPE_PATH", "").strip()
    predicted = resolved_env.get("CHIMERA_PREDICTED_OUTCOME", "").strip()

    # Fall back to config
    if not falsifiers_json:
        cfg_falsifiers = _get_commands(cfg, "falsifiers")
        if cfg_falsifiers:
            import json as _json
            falsifiers_json = _json.dumps(cfg_falsifiers)
    if not mnb_json:
        cfg_mnb = _get_commands(cfg, "must_not_break")
        if cfg_mnb:
            import json as _json
            mnb_json = _json.dumps(cfg_mnb)
    if not scope:
        scope = cfg.get("scope_path", "").strip()
    if not predicted:
        predicted = cfg.get("predicted_outcome", "").strip()

    # No falsifiers → refuse to lock
    if not falsifiers_json:
        result["errors"].append("No falsifier source provided for auto-lock.")
        result["fallback_message"] = (
            "Chimera did not auto-lock this task.\n\n"
            "Reason: No falsifier commands were configured.\n\n"
            "To enable auto-lock, set CHIMERA_FALSIFIERS_JSON or configure "
            ".chimera/hooks.toml with [[claude_hooks.falsifiers]] entries. "
            "Continue only if you understand this work will be evidence-dark "
            "until a claim is locked."
        )
        return result

    # Build and validate the spec
    try:
        monkeypatched_env: dict[str, str] = dict(resolved_env)
        monkeypatched_env["CHIMERA_INTENT"] = intent
        if scope:
            monkeypatched_env["CHIMERA_SCOPE_PATH"] = scope
        if falsifiers_json:
            monkeypatched_env["CHIMERA_FALSIFIERS_JSON"] = falsifiers_json
        if mnb_json:
            monkeypatched_env["CHIMERA_MUST_NOT_BREAK_JSON"] = mnb_json
        if predicted:
            monkeypatched_env["CHIMERA_PREDICTED_OUTCOME"] = predicted

        spec, extra_meta = build_claim_spec_from_auto_inputs(
            intent=intent,
            scope_path=scope or None,
            falsifiers_json=falsifiers_json,
            must_not_break_json=mnb_json or None,
            predicted_outcome=predicted or None,
            root=resolved_root,
        )
    except ClaimError as exc:
        result["errors"].append(str(exc))
        result["fallback_message"] = (
            f"Chimera did not auto-lock: {exc}"
        )
        return result

    validation = validate_claim_spec(spec, root=resolved_root)
    result["warnings"] = validation["warnings"]

    if not validation["valid"]:
        result["errors"].extend(validation["errors"])
        result["fallback_message"] = (
            "Chimera did not auto-lock: claim spec has validation errors."
        )
        return result

    if dry_run or resolved_env.get("CHIMERA_HOOK_DRY_RUN") == "1":
        result["dry_run"] = True
        result["fallback_message"] = (
            f"[Dry-run] Would lock claim with intent: {intent}"
        )
        return result

    # Lock the claim
    try:
        store = MemoryStore.from_paths(root=resolved_root)
        if not store.memory_dir.exists():
            store.initialize()
        record = lock_claim(store, spec, root=resolved_root)
        result["locked"] = True
        result["claim_id"] = record["claim_id"]
        result["warnings"] = record["quality"]["warnings"]
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(str(exc))
        result["fallback_message"] = f"Chimera auto-lock failed: {exc}"

    return result


def format_prompt_submit_output(result: dict[str, Any]) -> str:
    """Format the auto-lock result as Claude context injection text."""
    if not result.get("attempted") and result.get("fallback_message"):
        return f"[Chimera Memory] {result['fallback_message']}\n"

    if result.get("dry_run") and not result.get("locked"):
        return f"[Chimera Memory] {result.get('fallback_message', 'Dry-run complete.')}\n"

    if result.get("locked"):
        lines = [
            f"[Chimera Memory] Auto-locked claim {result['claim_id']} for this task.",
            "",
            f"Intent: {result['intent']}",
            "",
            "The claim will be settled against the configured falsifier and "
            "must-not-break checks when Claude finishes this turn.",
            "",
            "Keep edits within the declared scope. If the task changes, "
            "run: chimera-memory claim lock --auto --json",
        ]
        if result.get("warnings"):
            lines += ["", "Warnings:"]
            lines += [f"  - {w}" for w in result["warnings"]]
        return "\n".join(lines) + "\n"

    # Not locked
    msg = result.get("fallback_message") or "Chimera did not auto-lock this task."
    return f"[Chimera Memory] {msg}\n"

# ---------------------------------------------------------------------------
# Hook script templates (written to .claude/hooks/ by hooks install)
# ---------------------------------------------------------------------------

_PROMPT_SUBMIT_HOOK = """\
#!/usr/bin/env bash
# chimera-memory: UserPromptSubmit hook (v0.26)
# Auto-locks a claim from the submitted prompt when falsifiers are configured.
# Reads JSON from stdin. Writes Claude context to stdout. Never blocks.

set -uo pipefail

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | grep -o '"session_id": "[^"]*"' \
  | head -1 | cut -d'"' -f4 || echo "unknown")
SENTINEL="${TMPDIR:-/tmp}/.chimera-hook-prompted-${SESSION_ID}"

if [ -f "$SENTINEL" ] && [ "${CHIMERA_HOOK_AUTOLOCK_EVERY_PROMPT:-}" != "1" ]; then
  exit 0
fi
touch "$SENTINEL"

if [ "${CHIMERA_SKIP_AUTOLOCK:-}" = "1" ]; then
  exit 0
fi

if ! command -v chimera-memory &>/dev/null; then
  echo "[Chimera Memory] chimera-memory not found on PATH." >&2
  exit 0
fi

echo "$INPUT" | chimera-memory hooks prompt-submit 2>/dev/null || true

exit 0
"""

_STOP_HOOK = """\
#!/usr/bin/env bash
# chimera-memory: Stop hook
# Settles the open claim and generates PR_EVIDENCE.md when Claude finishes.
# Reads JSON from stdin. Exit 0 always.

set -uo pipefail

INPUT=$(cat)

# Guard against infinite loops
if echo "$INPUT" | grep -q '"stop_hook_active": true'; then
  exit 0
fi

if [ "${CHIMERA_SKIP_AUTOLOCK:-}" = "1" ]; then
  exit 0
fi

if ! command -v chimera-memory &>/dev/null; then
  echo "[Chimera Memory] chimera-memory not found on PATH." >&2
  exit 0
fi

# Find most recent LOCKED claim using text output
LOCKED_ID=$(chimera-memory claim list 2>/dev/null \
  | grep " LOCKED " | tail -1 | awk "{print \\$1}" || true)

if [ -z "$LOCKED_ID" ]; then
  exit 0
fi

echo "[Chimera Memory] Settling claim $LOCKED_ID..."
chimera-memory claim settle "$LOCKED_ID" 2>&1 | grep "status:" || true

BASE_BRANCH=""
if git rev-parse --verify origin/main &>/dev/null 2>&1; then
  BASE_BRANCH="origin/main"
elif git rev-parse --verify main &>/dev/null 2>&1; then
  BASE_BRANCH="main"
fi

if [ -n "$BASE_BRANCH" ]; then
  chimera-memory xray generate \
    --base "$BASE_BRANCH" --head HEAD --output PR_EVIDENCE.md 2>/dev/null || true
  echo "[Chimera Memory] PR_EVIDENCE.md generated (base: $BASE_BRANCH)."
else
  chimera-memory xray generate --output PR_EVIDENCE.md 2>/dev/null || true
  echo "[Chimera Memory] PR_EVIDENCE.md generated (working-tree mode)."
fi

echo "[Chimera Memory] Evidence written to PR_EVIDENCE.md. Review before PR."
exit 0
"""

_CLAUDE_SETTINGS_HOOKS: dict[str, list[dict[str, Any]]] = {
    "UserPromptSubmit": [
        {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/chimera-prompt-submit.sh",
                }
            ],
        }
    ],
    "Stop": [
        {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/chimera-stop.sh",
                }
            ],
        }
    ],
}


def install_hooks(
    project_root: Path,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Install Chimera hook scripts and patch .claude/settings.json.

    Creates:
      .claude/hooks/chimera-prompt-submit.sh  (UserPromptSubmit)
      .claude/hooks/chimera-stop.sh           (Stop)

    Patches or creates:
      .claude/settings.json

    Returns a result dict with {installed_files, patched_settings, warnings}.
    Does not overwrite existing scripts unless force=True.
    """
    hooks_dir = project_root / ".claude" / "hooks"
    settings_path = project_root / ".claude" / "settings.json"

    installed: list[str] = []
    warnings: list[str] = []

    scripts = {
        "chimera-prompt-submit.sh": _PROMPT_SUBMIT_HOOK,
        "chimera-stop.sh": _STOP_HOOK,
    }

    for name, content in scripts.items():
        target = hooks_dir / name
        if target.exists() and not force:
            warnings.append(
                f"{target.relative_to(project_root)} already exists — "
                "use --force to overwrite."
            )
            continue
        if not dry_run:
            hooks_dir.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
        installed.append(str(target.relative_to(project_root)))

    # Patch settings.json
    settings: dict[str, Any] = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            warnings.append(f".claude/settings.json exists but is invalid JSON: {exc}")
            settings = {}

    hooks_block = settings.setdefault("hooks", {})
    patched_events: list[str] = []

    for event, entries in _CLAUDE_SETTINGS_HOOKS.items():
        existing: list[dict[str, Any]] = hooks_block.get(event, [])
        # Check if our command is already registered
        our_cmd = entries[0]["hooks"][0]["command"]
        already_present = any(
            h.get("command") == our_cmd
            for group in existing
            for h in group.get("hooks", [])
        )
        if already_present and not force:
            warnings.append(
                f"Chimera hook for {event} already in .claude/settings.json — skipping."
            )
            continue
        if not dry_run:
            hooks_block[event] = existing + entries
        patched_events.append(event)

    if not dry_run and patched_events:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps(settings, indent=2) + "\n", encoding="utf-8"
        )

    # Ensure .claude/hooks is gitignored or at least warn if .gitignore present
    gitignore = project_root / ".gitignore"
    if gitignore.exists() and not dry_run:
        text = gitignore.read_text(encoding="utf-8")
        if ".claude/hooks/" not in text and ".claude/" not in text:
            warnings.append(
                ".claude/hooks/ is not in .gitignore. "
                "The hook scripts are safe to commit (they contain no secrets). "
                "If you prefer not to commit them, add '.claude/' to .gitignore."
            )

    return {
        "installed_files": installed,
        "patched_settings_events": patched_events,
        "settings_path": str(settings_path.relative_to(project_root)),
        "dry_run": dry_run,
        "warnings": warnings,
    }


def uninstall_hooks(project_root: Path) -> dict[str, Any]:
    """Remove Chimera hook scripts and entries from .claude/settings.json."""
    hooks_dir = project_root / ".claude" / "hooks"
    settings_path = project_root / ".claude" / "settings.json"
    removed: list[str] = []

    for name in ("chimera-prompt-submit.sh", "chimera-stop.sh"):
        target = hooks_dir / name
        if target.exists():
            target.unlink()
            removed.append(str(target.relative_to(project_root)))

    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"removed_files": removed, "patched_settings": False}

        hooks_block = settings.get("hooks", {})
        for event, entries in _CLAUDE_SETTINGS_HOOKS.items():
            our_cmd = entries[0]["hooks"][0]["command"]
            if event in hooks_block:
                hooks_block[event] = [
                    group
                    for group in hooks_block[event]
                    if not any(
                        h.get("command") == our_cmd for h in group.get("hooks", [])
                    )
                ]
                if not hooks_block[event]:
                    del hooks_block[event]
        if hooks_block:
            settings["hooks"] = hooks_block
        elif "hooks" in settings:
            del settings["hooks"]
        settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    return {"removed_files": removed, "patched_settings": True}


def show_hooks_status(project_root: Path) -> dict[str, Any]:
    """Return the current Chimera hook installation status."""
    hooks_dir = project_root / ".claude" / "hooks"
    settings_path = project_root / ".claude" / "settings.json"

    scripts_present = {
        name: (hooks_dir / name).exists()
        for name in ("chimera-prompt-submit.sh", "chimera-stop.sh")
    }

    settings_hooks: dict[str, bool] = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            for event, entries in _CLAUDE_SETTINGS_HOOKS.items():
                our_cmd = entries[0]["hooks"][0]["command"]
                existing = settings.get("hooks", {}).get(event, [])
                settings_hooks[event] = any(
                    h.get("command") == our_cmd
                    for group in existing
                    for h in group.get("hooks", [])
                )
        except json.JSONDecodeError:
            pass

    installed = all(scripts_present.values()) and all(settings_hooks.values())
    return {
        "installed": installed,
        "scripts": scripts_present,
        "settings_hooks": settings_hooks,
        "settings_path": str(settings_path) if settings_path.exists() else None,
    }
