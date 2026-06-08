"""Claude Code hook installation for Chimera Memory (v0.25).

Provides ``chimera-memory hooks install`` which writes three hook scripts
into ``.claude/hooks/`` and patches ``.claude/settings.json`` with the hook
configuration needed for automatic claim-locked evidence:

  PreToolUse (UserPromptSubmit) → lock a claim before editing
  Stop                          → settle + generate PR_EVIDENCE.md

Hook lifecycle (matching Claude Code events):
  - UserPromptSubmit: fires when user submits a prompt. We use it to
    optionally remind Claude to set CHIMERA_INTENT before coding begins.
  - Stop: fires when Claude finishes a turn. We use it to settle the open
    claim and generate PR_EVIDENCE.md.

Design notes
------------
The hook scripts are pure shell (no Chimera import). They call
``chimera-memory`` via the CLI so they work even when the project does not
have Chimera in its local venv — as long as ``chimera-memory`` is on PATH.

All claims are created via ``claim lock --auto`` using environment variables
that Claude can set in its workspace (CHIMERA_INTENT, CHIMERA_SCOPE_PATH, etc.).

Nothing is run with shell=True inside the scripts themselves — every invocation
is a direct subprocess exec. The scripts only *describe* command strings in
shell because they *are* shell scripts.

Safety
------
- The Stop hook reads ``stop_hook_active`` from stdin to avoid infinite loops.
- The Stop hook only settles/generates if a LOCKED claim exists.
- All paths use ``$CLAUDE_PROJECT_DIR`` / ``$PWD`` — no hardcoded paths.
- No network, no tokens, no uploaded data.
"""
from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Hook script templates
# ---------------------------------------------------------------------------

# This hook fires on UserPromptSubmit. It injects a reminder into Claude's
# context (written to stdout) telling it how to use auto-lock. The hook
# never blocks (exit 0 always) and only injects once per session via a
# sentinel file. Using UserPromptSubmit (fires on every prompt) means Claude
# sees the reminder at the start of a fresh task.
_PROMPT_SUBMIT_HOOK = '''\
#!/usr/bin/env bash
# chimera-memory: UserPromptSubmit hook
# Injects a one-time reminder about claim auto-lock into Claude's context.
# Reads JSON from stdin (Claude hook protocol). Writes reminder to stdout.
# Never blocks (exit 0 always).

set -euo pipefail

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | python3 -c \
  "import sys,json;print(json.load(sys.stdin).get('session_id','unknown'))" \
  2>/dev/null || echo "unknown")
SENTINEL="${TMPDIR:-/tmp}/.chimera-hook-reminded-${SESSION_ID}"

# Only inject the reminder once per session
if [ -f "$SENTINEL" ]; then
  exit 0
fi
touch "$SENTINEL"

# Inject reminder text into Claude's context (stdout = context injection)
cat <<'REMINDER'
[Chimera Memory] Claim-Locked Evidence is active for this session.

Before making code changes, set these environment variables and lock a claim:
  export CHIMERA_INTENT="<what you plan to do>"
  export CHIMERA_SCOPE_PATH="<path/to/package>"
  export CHIMERA_FALSIFIERS_JSON='[["<test-command>","<test-file>"]]'
  chimera-memory claim lock --auto --json

After your changes, chimera-memory will automatically settle the claim and
generate PR_EVIDENCE.md when you complete this turn.

To skip auto-lock for this turn, set: export CHIMERA_SKIP_AUTOLOCK=1
REMINDER

exit 0
'''

# This hook fires on Stop (when Claude finishes a turn). It:
# 1. Guards against the stop_hook_active infinite-loop.
# 2. Skips if CHIMERA_SKIP_AUTOLOCK=1.
# 3. Looks for any LOCKED claim in the local ledger.
# 4. If found: settles it, then generates PR_EVIDENCE.md.
# 5. Reports results via stdout (added to Claude's context).
_STOP_HOOK = '''\
#!/usr/bin/env bash
# chimera-memory: Stop hook
# Settles the open claim and generates PR_EVIDENCE.md when Claude finishes.
# Reads JSON from stdin (Claude hook protocol).
# Exit 0 always (never block Claude from stopping).

set -uo pipefail

INPUT=$(cat)

# Guard: stop_hook_active prevents infinite loops
STOP_ACTIVE=$(echo "$INPUT" | python3 -c \
  "import sys,json;print(json.load(sys.stdin).get('stop_hook_active','false'))" \
  2>/dev/null || echo "false")
if [ "$STOP_ACTIVE" = "true" ]; then
  exit 0
fi

# Allow opt-out
if [ "${CHIMERA_SKIP_AUTOLOCK:-}" = "1" ]; then
  exit 0
fi

# Check chimera-memory is on PATH
if ! command -v chimera-memory &>/dev/null; then
  echo "[Chimera Memory] chimera-memory not found on PATH — skipping auto-settle." >&2
  exit 0
fi

# Find the most recent LOCKED claim in the local ledger
LOCKED_ID=$(chimera-memory claim list --json 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    locked = [c for c in data.get('claims', []) if c.get('status') == 'LOCKED']
    print(locked[-1]['claim_id'] if locked else '')
except Exception:
    print('')
" 2>/dev/null || true)

if [ -z "$LOCKED_ID" ]; then
  exit 0
fi

echo "[Chimera Memory] Settling claim $LOCKED_ID..."

# Settle the claim (runs sealed falsifier/must-not-break commands)
SETTLE_OUTPUT=$(chimera-memory claim settle "$LOCKED_ID" --json 2>/dev/null || true)
SETTLE_STATUS=$(echo "$SETTLE_OUTPUT" | python3 -c "
import sys, json
try:
    print(json.load(sys.stdin).get('settlement', {}).get('status', 'UNKNOWN'))
except Exception:
    print('UNKNOWN')
" 2>/dev/null || echo "UNKNOWN")

echo "[Chimera Memory] Settlement status: $SETTLE_STATUS"

# Generate PR_EVIDENCE.md using commit-range mode if we can detect a base branch
BASE_BRANCH=""
if git rev-parse --verify origin/main &>/dev/null; then
  BASE_BRANCH="origin/main"
elif git rev-parse --verify main &>/dev/null; then
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

echo "[Chimera Memory] Evidence written to PR_EVIDENCE.md. Review before submitting your PR."

exit 0
'''

# ---------------------------------------------------------------------------
# Claude settings helpers
# ---------------------------------------------------------------------------

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
                "The hook scripts are safe to commit, but the sentinel files "
                "in /tmp are ephemeral. Consider adding .claude/ to .gitignore "
                "if you don't want hook config committed."
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
