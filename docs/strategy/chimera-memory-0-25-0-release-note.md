# chimera-memory 0.25.0 — Claude Code Hook Auto-Lock

## Release theme

v0.25.0 adds Claude Code hook installation so claim-locked evidence happens
automatically during a Claude coding session with minimal manual action.

## New CLI

```bash
chimera-memory hooks install
chimera-memory hooks install --dry-run
chimera-memory hooks install --force
chimera-memory hooks status
chimera-memory hooks uninstall
```

## What it installs

Two hook scripts in `.claude/hooks/` and two entries in `.claude/settings.json`:

| Hook event | Script | What it does |
|---|---|---|
| `UserPromptSubmit` | `chimera-prompt-submit.sh` | One-time context reminder about CHIMERA_INTENT |
| `Stop` | `chimera-stop.sh` | Settles open claim + generates PR_EVIDENCE.md |

## Workflow

```bash
# 1. Install hooks once per project
chimera-memory hooks install

# 2. Before a coding task: lock a claim
export CHIMERA_INTENT="fix checkout null dereference"
export CHIMERA_SCOPE_PATH="packages/cart"
export CHIMERA_FALSIFIERS_JSON='[["uv","run","pytest","packages/cart/tests/"]]'
chimera-memory claim lock --auto --json

# 3. Code with Claude — Stop hook fires automatically
# → settles the claim
# → generates PR_EVIDENCE.md

# 4. Review before PR
cat PR_EVIDENCE.md
```

## Safety

- All behavior is local. No network. No cloud. No telemetry.
- `stop_hook_active` guard prevents infinite loops.
- `CHIMERA_SKIP_AUTOLOCK=1` opts out for any individual turn.
- Settlement runs only the sealed claim commands.
- Scripts use `$CLAUDE_PROJECT_DIR` — no hardcoded paths.

## Tests

+28 tests covering install/uninstall/status, CLI, dry-run, force, idempotency,
settings merge, script content guards.

## Not automated yet

- Claim locking from `UserPromptSubmit` (still one manual env export + lock)
- Per-file change attribution
- Multi-agent coordination

## Honesty

This is settled evidence, not proof of code correctness. Scope coverage is
path-based. The Stop hook settles against sealed commands — it cannot substitute
a different check.

## Not built

- GitHub Action/App
- Remote/hosted MCP
- Model ranking/routing/M2B scoring
- Claude Code plugin (this uses the standard hooks API)

## Dependency

```text
chimera-memory-types>=0.25.0,<1.0
```
