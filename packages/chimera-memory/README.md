# chimera-memory

Local-first reliability ledger for AI coding-agent work.

Records what an agent tried, which command verified it, what happened, and what receipt proves it. Everything stays on your machine — no cloud, no sync, no account required.

## Install

```bash
pip install chimera-memory
```

Requires Python 3.10+. Installs `chimera-memory-types`, `pydantic`, and `filelock` automatically.

## Quickstart (5 commands)

```bash
# 1. Initialise the local ledger (also adds .chimera-memory/ to .gitignore)
chimera-memory init

# 2. Start a session
chimera-memory session start \
  --branch feat/my-branch \
  --task-label "fix type errors" \
  --agent kiro \
  --model claude-sonnet-4.6 \
  --harness-id kiro-cli

# 3. Wrap a verification command (test, lint, typecheck, …)
chimera-memory wrap \
  --failure-origin organic_real \
  --verification-scope package \
  -- pytest tests/ -q

# 4. End the session
chimera-memory session end --status PASSED

# 5. View the receipt
chimera-memory receipt latest
```

## Onboard an agent in 90 seconds

Get the full session/wrap/repair-loop protocol for your agent:

```bash
chimera-memory agent-guide --agent generic   # or: kiro, codex
```

Generate a copy-paste session scaffold for your package:

```bash
chimera-memory template dogfood --scope-path packages/chimera-memory
```

Prompt templates for sustained use are in [`docs/prompts/`](../../docs/prompts/):

- `kiro-dogfood.md` — Kiro agent session discipline
- `generic-agent-dogfood.md` — Any agent
- `release-closeout.md` — Release closeout checklist

## Health check

```bash
chimera-memory doctor
chimera-memory doctor --json
```

`doctor` is read-only. It checks:
- Is `.chimera-memory/` initialized?
- Is `.chimera-memory/` in `.gitignore`?
- Is there an active session?
- Claim count and integrity status
- M2B readiness level

Exit code: `0` = healthy, `1` = warnings (e.g. no active session), `2` = critical (e.g. not initialized).

## Is my ledger healthy?

`doctor` also audits whether the ledger is being used correctly:

```bash
chimera-memory doctor        # shows Evidence Hygiene section
chimera-memory doctor --json # machine-readable, includes evidence_hygiene + next_actions
```

Evidence hygiene checks:
- Scoped claim ratio (claims with `--scope-path` set)
- Unknown `failure_origin` count (claims missing classification)
- Repair-loop completeness (loops with `same_scope_after_fix`)
- Orphaned repair phases (`--repair-phase` without `--repair-loop-id`)
- Test/synthetic and invocation-artifact claim counts

If issues are found, `doctor` prints actionable next steps.

## Preflight Intelligence (v0.6)

Before starting work, surface historical failures, repair-loop lessons, and hygiene warnings:

```bash
chimera-memory preflight --from-git
chimera-memory preflight --scope-path packages/chimera-memory
```

Shows:
- Historical failures in the relevant scope (organic_real + controlled_real)
- Repair-loop lessons (what failed, was it fixed?)
- Hygiene warnings (invocation_artifact issues — not product defects)
- Recommended verification commands

Not M2B scoring or model ranking. Advisory only.

## Preflight check

Before starting work, run a preflight advisory:

```bash
chimera-memory preflight --from-git
```

Shows M2B readiness level, scope summary, and any advisory warnings. Output is advisory only — no routing, no gating.

## CI receipt bundle

Produce a full CI-ready artifact bundle (receipt, failures, reliability, preflight, GitHub summary):

```bash
chimera-memory receipt bundle \
  --output-dir ./ci-bundle \
  --include-preflight \
  --from-git
```

Upload `ci-bundle/` as a CI artifact to preserve receipts across runs.

## Evidence dry-run

Export claims as a portable evidence bundle and inspect what a merge would do:

```bash
chimera-memory evidence bundle --output-dir ./evidence
chimera-memory evidence import ./evidence --dry-run --json
```

Write-import is not available in 0.1.x. Dry-run only.

## M2B readiness

```bash
chimera-memory m2b-readiness
```

Shows whether the local ledger has accumulated sufficient repair-loop evidence to consider M2B (model-to-baseline) comparison. This is a local readiness gate, not a scoring system.

Run `chimera-memory m2b-readiness --explain` to see what evidence is missing before scoring can be trusted.

## What is not built

| Capability | Status |
|---|---|
| M2B drift scoring | Not built |
| Model ranking / routing | Not built |
| Hosted / cloud sync | Not built |
| Remote team ledger | Not built |
| Evidence write-import | Not built (dry-run only) |
| Dashboard or UI | Not built |

## Platform support

| Platform | Status |
|---|---|
| macOS | ✅ Tested |
| Linux | ✅ Tested (CI and Docker) |
| Windows | ⚠️ Not officially tested in 0.1.x |

No intentional Windows lockout is known. If you encounter a Windows-specific issue, please open an issue.

## Troubleshooting

**`preflight --from-git` shows `source: none`**

This is expected when the working tree is clean (no modified files). Use `--scope-path <dir>` to specify a target directory explicitly:

```bash
chimera-memory preflight --scope-path src/
```

**`receipt latest` shows "No closed sessions"**

You need to complete a session first:

```bash
chimera-memory session start --branch <branch> --task-label <label> --agent <agent> --model <model> --harness-id <id>
# ... run chimera-memory wrap commands ...
chimera-memory session end --status PASSED
```

**`m2b-readiness` shows BLOCKED**

The ledger needs at least 5 genuine `organic_real` failures followed by fixes to clear the gate. Run real verification cycles — do not manufacture failures.

**`verify` shows `LEGACY_UNSIGNED`**

Claims recorded before the integrity chain was introduced show as `LEGACY_UNSIGNED`. This is informational. Zero `Broken records` is the signal that matters.

## Security note

`chimera-memory wrap` records the command string and bounded stdout/stderr. Built-in redaction removes tokens matching common secret patterns. However:

- Do not pass secrets, passwords, or API keys as literal command arguments.
- The `.chimera-memory/` directory contains your local ledger. Do not commit it to version control.

Add to `.gitignore` (done automatically by `chimera-memory init`):

```
.chimera-memory/
```

## Test fixture isolation

When writing tests that call `chimera-memory wrap` as a fixture, set `CHIMERA_DQ_NO_WRITE=1` to prevent test runs from writing to the real local ledger:

```bash
CHIMERA_DQ_NO_WRITE=1 chimera-memory wrap --failure-origin organic_real -- pytest tests/
```

The wrapped command runs normally and the exit code is preserved. No claims are written. A notice is printed.

**Do not set `CHIMERA_DQ_NO_WRITE=1` for real dogfood verification sessions.** It is for test fixtures only.

## License

MIT — see [LICENSE](LICENSE)
