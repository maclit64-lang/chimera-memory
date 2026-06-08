# chimera-memory 0.26.0 — Prompt-Derived Claim Auto-Lock

## Release theme

v0.26.0 closes the last manual gap in the claim-locked evidence loop: when
falsifiers are configured, the first Claude prompt automatically becomes the
claim intent and Chimera locks a claim before any edits begin.

## Core safety rule (preserved)

```
No falsifiers configured → no auto-lock.
```

Chimera never invents test commands from prompt text. If no falsifier source
exists, the hook injects a clear explanation instead of locking a fake claim.

## New capabilities

### Prompt-derived intent

`derive_intent_from_prompt()` deterministically extracts claim intent from
the submitted prompt text — strips politeness prefixes, collapses whitespace,
truncates to a safe length. No LLM. No semantic inference.

### Auto-lock from UserPromptSubmit

The `UserPromptSubmit` hook now calls `chimera-memory hooks prompt-submit`,
which:
1. Reads the hook payload from stdin
2. Extracts prompt text (supports `prompt`, `user_prompt`, messages shapes)
3. Derives intent from prompt text
4. Checks for existing LOCKED claim (dedup guard)
5. Resolves falsifiers from env or `.chimera/hooks.toml`
6. Validates the generated claim spec
7. Locks the claim if valid, injects context; explains why not if invalid

### `.chimera/hooks.toml` project config

```toml
[claude_hooks]
auto_lock = true
scope_path = "packages/chimera-memory"
falsifiers = [["uv", "run", "pytest", "packages/chimera-memory/tests/"]]
must_not_break = [["uv", "run", "pytest", "-m", "not slow"]]
```

### `chimera-memory hooks prompt-submit`

```bash
# Called automatically by the hook script
echo '{"prompt": "fix xray reviewer focus"}' \
  | chimera-memory hooks prompt-submit

# Preview without locking
chimera-memory hooks prompt-submit --dry-run

# JSON output for testing
chimera-memory hooks prompt-submit --json
```

## Config precedence

1. `CHIMERA_INTENT` env var (explicit wins)
2. Prompt-derived intent (when CHIMERA_INTENT unset)
3. `CHIMERA_FALSIFIERS_JSON` env var (explicit wins)
4. `.chimera/hooks.toml` [claude_hooks].falsifiers
5. No falsifiers → no lock

## Full zero-friction loop (when configured)

```bash
# One-time: install hooks + configure checks
chimera-memory hooks install

cat > .chimera/hooks.toml << EOF
[claude_hooks]
scope_path = "packages/cart"
falsifiers = [["uv", "run", "pytest", "packages/cart/tests/"]]
must_not_break = [["uv", "run", "pytest", "-m", "not slow"]]
EOF

# Now start a Claude Code session and type your task.
# Chimera auto-locks a claim from your first prompt.
# Stop hook settles and generates PR_EVIDENCE.md.
```

## Escape hatches

| Env var | Effect |
|---|---|
| `CHIMERA_SKIP_AUTOLOCK=1` | Skip all auto-lock/settle |
| `CHIMERA_HOOK_DRY_RUN=1` | Validate without locking |
| `CHIMERA_HOOK_AUTOLOCK_EVERY_PROMPT=1` | Lock on every prompt (no dedup) |
| `CHIMERA_INTENT=...` | Override prompt-derived intent |

## Tests

+32 new tests: intent derivation, prompt extraction, auto-lock flow, config,
CLI, negative cases (no falsifiers), dedup guard, escape hatches.

## Honesty boundary

- Scope coverage remains path-based.
- Prompt text is used for intent only — never to infer test commands.
- No LLM inside Chimera.
- This is settled evidence, not proof of correctness.

## Dependency

```text
chimera-memory-types>=0.26.0,<1.0
```
