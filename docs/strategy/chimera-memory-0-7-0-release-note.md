# chimera-memory 0.7.0 Release Note

**Theme:** Agent Onboarding + Dogfood Playbooks

**Release date:** 2026-06-07

---

## What changed

### New commands

**`chimera-memory agent-guide [--agent generic|kiro|codex]`**

Prints the complete session/wrap/repair-loop protocol for a named agent. Covers classification rules for all five `failure_origin` values, the exact session sequence, repair-loop discipline with correct repair status semantics, and the M2B readiness note. Designed to be run at the start of any task so agents do not need prior knowledge of the protocol.

**`chimera-memory template dogfood --scope-path <path>`**

Generates a copy-paste command sequence for a complete dogfood session against a given scope. For known scopes (`packages/chimera-memory`, `packages/chimera-memory-types`) it emits real commands. For unknown scopes it emits labelled placeholders. Output covers preflight → session start → wraps → session end → verify → receipt bundle.

### Wrap warnings (non-fatal, stderr)

Three targeted warnings fire at point-of-mistake during `chimera-memory wrap`:

- `--scope-path` not set → preflight intelligence anchoring warning
- `failure_origin` missing → DQ cohort exclusion warning
- `--repair-phase` set without `--repair-loop-id` → repair-loop lesson warning

All warnings are stderr-only and do not change exit codes or claim recording behaviour.

### Docs/prompt pack

- `docs/prompts/kiro-dogfood.md` — Kiro agent session discipline with harness flags
- `docs/prompts/generic-agent-dogfood.md` — Any agent, no harness assumptions
- `docs/prompts/release-closeout.md` — Release closeout checklist
- `docs/strategy/chimera-memory-agent-onboarding-v0-7.md` — Design rationale

### README

Added "Onboard an agent in 90 seconds" section pointing to `agent-guide`, `template dogfood`, and `docs/prompts/`.

---

## Why it matters

Chimera Memory records whether agents produce clean evidence. It did not previously teach agents what clean evidence looks like. v0.7 closes that gap.

Concretely, the three most damaging misuses were:

1. `test_first_contract` failures mislabeled as `organic_real` — corrupts M2B readiness
2. `--scope-path` omitted on wraps — preflight intelligence is unanchored
3. No `repair_loop_id` on real bugs — `fixed_same_scope` repair status never generated

`agent-guide` addresses all three inline, at the moment an agent starts work.

---

## What did not change

- No M2B scoring
- No model ranking
- No routing
- No write-import
- No hosted/cloud
- No dashboard
- No storage schema changes (`schema_version` remains 2)
- No ledger migration

---

## Verification

- pytest: 589/589 passing (18 new tests for onboarding features)
- mypy: 0 errors (chimera-memory and chimera-memory-types)
- ruff: clean
- DQ wraps: 11/11 VALIDATED in feature implementation session; 12/12 VALIDATED in release closeout session

---

## Caveats

- GitHub Actions remains blocked by external account billing lock — not a release blocker
- M2B readiness: BLOCKED (organic_real_failed 3/5) — expected in standalone ledger; not a release blocker
