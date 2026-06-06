# Chimera Memory Agent Onboarding — v0.7

**Theme:** Agent Onboarding + Dogfood Playbooks

---

## Problem

Every new agent session started from scratch. Without explicit guidance, agents:

1. Mislabeled `test_first_contract` failures as `organic_real` — corrupting M2B readiness
2. Omitted `--scope-path` on wraps — leaving preflight intelligence unanchored
3. Forgot `repair_loop_id` on real bugs — preventing `fixed_same_scope` repair status
4. Never ran `receipt bundle` — no artifacts for human review
5. Misunderstood `M2B BLOCKED` as a failure — and tried to work around it

v0.7 makes the tool self-teaching.

---

## Solution

Three-part bundle:

### 1. `agent-guide` command

```bash
chimera-memory agent-guide [--agent generic|kiro|codex]
```

Outputs the full session/wrap/repair-loop protocol inline. Agents can run this at the start of any session to get exact, runnable instructions. Agent-specific variants add harness flags.

### 2. `template dogfood` command

```bash
chimera-memory template dogfood --scope-path <path>
```

Generates a copy-pasteable session scaffold for any scope. For known scopes (`packages/chimera-memory`, `packages/chimera-memory-types`), emits real commands. For unknown scopes, emits documented placeholders.

### 3. Targeted wrap warnings (non-fatal, stderr)

Three warnings fire at point-of-mistake:

- `--scope-path` missing → anchoring warning
- `--failure-origin` missing → DQ cohort warning  
- `--repair-phase` without `--repair-loop-id` → lesson generation warning

Warnings are stderr-only, non-fatal, and do not change exit codes.

---

## Classification rules (canonical)

| `failure_origin` | When to use |
|---|---|
| `organic_real` | Real failure encountered during actual work. The most important value. |
| `controlled_real` | Real failure in a deliberately controlled/fixture run. |
| `invocation_artifact` | Environment flake: timeout, network, disk. Not a code bug. |
| `test_first_contract` | TDD red-phase test written before implementation. **Never `organic_real`.** |
| `synthetic` | Fabricated scenario. **Never `organic_real`.** |

---

## Repair-loop anatomy

```
wrap --repair-phase baseline         → claim: CONTRADICTED, repair_status: open
[fix the code]
wrap --repair-phase same_scope_after_fix → claim: VALIDATED, repair_status: fixed_same_scope
wrap --repair-phase regression_check    → claim: VALIDATED, repair_status: later_regression_validated
```

`regression_check` does NOT produce `fixed_same_scope`. Only `same_scope_after_fix` does.

All three wraps must share the same `--repair-loop-id` (a stable slug, e.g. `fix-scope-match-2026-06`).

---

## M2B readiness

M2B BLOCKED in a fresh ledger is **expected**. The threshold is 5 `organic_real_failed` claims. A fresh project starts at 0. Do not reclassify tests or fabricate failures to unblock it. It unblocks naturally as real bugs are fixed.

---

## Data model impact

None. v0.7 adds no new persisted fields. `schema_version` stays 2. All new features are read-only CLI output or documentation.

---

## Prompt pack

| File | Purpose |
|---|---|
| `docs/prompts/kiro-dogfood.md` | Kiro-specific onboarding prompt |
| `docs/prompts/generic-agent-dogfood.md` | Generic agent onboarding prompt |
| `docs/prompts/release-closeout.md` | Release closeout checklist |
| `docs/strategy/chimera-memory-agent-onboarding-v0-7.md` | This document |

---

## Non-goals

No M2B scoring. No model ranking. No routing. No write-import. No hosted/cloud. No dashboard. No GitHub Actions debugging. No storage migration. No artificial failure generation.
