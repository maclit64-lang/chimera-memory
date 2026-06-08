# Claude Code Hooks — Auto-Lock Setup

`chimera-memory hooks install` wires two Claude Code hooks into your project
so claim-locked evidence happens automatically during a Claude coding session.

## What it does

After installation, a Claude Code session will:

1. **Remind you** (once per session) to set `CHIMERA_INTENT` before editing
2. **Automatically settle** the open claim when Claude finishes a turn
3. **Generate `PR_EVIDENCE.md`** using commit-range mode when Claude stops

You still need to lock the initial claim manually — but that's one command,
and the Stop hook handles everything after that.

## Install

```bash
# Install into the current project
chimera-memory hooks install

# Preview without writing
chimera-memory hooks install --dry-run

# Reinstall / overwrite
chimera-memory hooks install --force
```

This creates:
```
.claude/hooks/chimera-prompt-submit.sh   (UserPromptSubmit hook)
.claude/hooks/chimera-stop.sh            (Stop hook)
.claude/settings.json                    (patched with hook config)
```

## Verify installation

```bash
chimera-memory hooks status
# Or in Claude Code: /hooks
```

## Full workflow with hooks installed

### 1. Lock a claim before starting work

```bash
export CHIMERA_INTENT="fix checkout null dereference"
export CHIMERA_SCOPE_PATH="packages/cart"
export CHIMERA_FALSIFIERS_JSON='[["uv","run","pytest","packages/cart/tests/test_checkout.py"]]'
export CHIMERA_MUST_NOT_BREAK_JSON='[["uv","run","pytest","packages/cart/tests/"]]'
chimera-memory claim lock --auto --json
```

Record the `claim_id` from the output.

### 2. Start Claude Code and make your edits

The `UserPromptSubmit` hook injects a one-time reminder at the start of your
session showing exactly what env vars to set.

### 3. Claude finishes — hooks fire automatically

When Claude completes a turn (`Stop` event):
- `chimera-stop.sh` finds the open LOCKED claim
- Settles it against the sealed falsifiers/must-not-break commands
- Generates `PR_EVIDENCE.md` using `--base origin/main --head HEAD`

You see output like:
```
[Chimera Memory] Settling claim clm_...
[Chimera Memory] Settlement status: VALIDATED
[Chimera Memory] PR_EVIDENCE.md generated (base: origin/main).
[Chimera Memory] Evidence written to PR_EVIDENCE.md. Review before submitting your PR.
```

### 4. Review PR_EVIDENCE.md before opening a PR

```bash
cat PR_EVIDENCE.md
```

## Skip auto-settle for a turn

```bash
export CHIMERA_SKIP_AUTOLOCK=1
```

## Settings file example

After `hooks install`, `.claude/settings.json` contains:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [{"type": "command", "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/chimera-prompt-submit.sh"}]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [{"type": "command", "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/chimera-stop.sh"}]
      }
    ]
  }
}
```

## Uninstall

```bash
chimera-memory hooks uninstall
```

Removes the scripts and their entries from `.claude/settings.json`.

## Safety

- All hook behavior is local. No network. No cloud. No telemetry.
- The Stop hook reads `stop_hook_active` from stdin to prevent infinite loops.
- Settlement runs only the sealed claim commands — never arbitrary code.
- `CHIMERA_SKIP_AUTOLOCK=1` lets you skip for any individual turn.

## What is not automated yet

- Locking the initial claim (still requires `chimera-memory claim lock --auto`)
- Per-file change attribution (scope is path-based)
- Multi-agent coordination (schema seam only)

The next step (v0.26) is automatic claim locking from the first `UserPromptSubmit`
hook based on Claude's task description.
