# chimera-memory 0.22.0 — Claim-Locked Evidence Foundation + Manual Merge X-Ray

## Release theme

v0.22.0 introduces the first usable AI PR evidence layer for Chimera Memory.

An agent can now lock a scope-bound claim before editing, settle it against
pre-committed checks, and generate a local `PR_EVIDENCE.md` that shows which
changed files carry settled evidence and which are evidence-dark.

This is the first implementation of:

```
Claim-Locked Coding → Manual Merge X-Ray → PR_EVIDENCE.md
```

## New CLI surface

```bash
chimera-memory claim lock --from-file claim.toml
chimera-memory claim list
chimera-memory claim show <claim_id>
chimera-memory claim settle <claim_id>
chimera-memory claim report <claim_id>
chimera-memory xray generate --output PR_EVIDENCE.md
chimera-memory xray generate --base main --head HEAD --output PR_EVIDENCE.md
chimera-memory xray generate --json
```

## Highlights

- **Sealed claim lifecycle.** A claim is locked with intent, a declared
  `scope_path`, a pre-committed `falsifier`, and optional `must-not-break`
  commands — all before any edit. The seal records a stable `payload_hash`
  and the pre-edit git HEAD + dirty state.

- **Settlement against sealed checks only.** `claim settle` runs exactly the
  pre-committed commands. It can never substitute a different check.
  Statuses: `LOCKED`, `VALIDATED`, `CONTRADICTED`, `UNSETTLED`, `SCOPE_DRIFT`.

- **Scope drift detection.** Changed files outside the declared `scope_path`
  are flagged as scope drift.

- **Evidence-dark changed-file detection.** Changed files not covered by any
  settled claim are listed as evidence-dark.

- **Merge X-Ray / PR_EVIDENCE.md.** The X-Ray aggregates settled claims + git
  diff and produces a Markdown report with: Verdict, Settled Claims,
  Evidence-Dark Changes, Scope Drift, Weak/Unsettled Evidence, Reviewer Focus,
  Non-Claims.

- **Multi-terminal attribution seam.** Each claim record carries `terminal_id`,
  `worktree_path`, `branch`, `session_id`, `agent_name`, `model_name`,
  `harness_id`, and `attribution_confidence`. Unknown values are recorded
  honestly as null/"unknown" — attribution is never fabricated.

- **Command safety.** All commands are `list[str]` executed with `shell=False`.
  Shell strings are rejected; explicit lists are required.

- **Append-only ledger.** Claim-lock records live in
  `.chimera-memory/claim_locks.jsonl`. The latest record per `claim_id` is
  authoritative. History is never mutated.

## New docs

- `docs/contracts/claim-lock-json.md` — claim-lock JSON schema (v1)
- `docs/contracts/xray-json.md` — Merge X-Ray JSON schema (v1)
- `docs/examples/claim-locked-coding.md` — how to use claim-locked coding
- `docs/examples/pr-evidence-example.md` — example PR_EVIDENCE.md and usage

## Tests

+68 tests covering: command-shape safety, payload-hash stability, git
state capture, all settlement statuses, scope-drift detection, unrunnable→UNSETTLED,
no-falsifier-substitution, attribution presence/unknown/env, X-Ray Markdown
sections, evidence-dark, post-hoc mode, JSON schema stability, docs guards,
regression (receipt/bundle/checks/M2B behavior unchanged).

## Honesty boundary

This release shows **settled evidence, not proof of correctness**. Scope
coverage is path-based ("covered by declared claim scope"), never a semantic
guarantee. Every generated report carries the non-claims caveat.

Not built in this release:
- M2B scoring, model ranking, model routing
- Hosted/cloud sync, team dashboard
- Claude Code hooks, MCP server, Codex/Cursor integration
- GitHub Action, GitHub App
- Full multi-terminal orchestration (schema seam only)
- Write-import

## Dependency

```text
chimera-memory-types>=0.22.0,<1.0
```
