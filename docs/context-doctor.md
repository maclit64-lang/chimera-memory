# Context Doctor

`chimera-memory context-doctor` is a local, read-only **context-hygiene report** over the v0.29
session stack (Agent Work Sessions and Work Briefs). It surfaces missing, stale, or incomplete
context *before* another agent continues work — for example an open session that recorded no
closeout events, or a session whose referenced review-thread directory is gone.

Everything it emits is a **finding**: an advisory observation with a suggested inspection command.
Findings are not verdicts.

```bash
chimera-memory context-doctor                 # markdown (default)
chimera-memory context-doctor --json
chimera-memory context-doctor --status open
chimera-memory context-doctor --tag v0.29
chimera-memory context-doctor --limit-findings 20
chimera-memory context-doctor --output CONTEXT_DOCTOR.md
chimera-memory context-doctor bundle --output-dir DIR [--force]
```

## What it is

The report (`artifact: "chimera_context_doctor"`) carries `filters`, a `summary` (session /
brief / finding / open-session / blocked-session / carryover counts), a deterministic `findings`
list, and `suggested_review_targets` (a deduplicated list of explicit pointers — open / blocked
session ids, missing referenced paths, unlinked brief ids). It is built entirely from existing
read-only readers (work-session events + projections, work briefs) plus simple filesystem
existence checks on the paths a session explicitly references.

## Finding kinds (v0)

| kind | meaning |
|---|---|
| `open_session_without_closeout` | An open session has no closeout-family events recorded. |
| `blocked_session_with_carryover` | A blocked session left carryover items to review. |
| `session_without_snapshots` | A session has no attached review-thread snapshots. |
| `session_without_reported_checks` | A session recorded no reported checks. |
| `brief_without_session` | A Work Brief is not linked to any Work Session. |
| `missing_thread_dir` | A session's referenced review-thread directory is missing on disk. |
| `missing_kickoff_pack_dir` | A session's referenced kickoff-pack directory is missing on disk. |
| `closeout_without_carryover_review` | A session recorded closeout activity but left no carryover. |
| `consequence_observation_without_session` | A recorded [consequence observation](consequence-observations.md) is not attached to a known work session. |

Each finding has a `kind`, a neutral `message`, the related `session_id` / `brief_id`, any
referenced `refs`, a `suggested_inspection` command list, and `tags`. Findings use `kind` only —
there is no severity, priority, or score.

## What findings do not mean

A finding is a prompt to look, nothing more. The Context Doctor does **not** judge whether work is
correct, safe, approvable, or mergeable; it does not rank or score findings, assign severity, run
any check, execute commands, start sessions, or create briefs. An empty report means "no findings"
for the current filters — not a judgment about the work.

## Filters

`--status` and `--tag` are exact-match (no fuzzy / semantic matching) and select which sessions
are examined. `brief_without_session` findings are reported only when no `--status` filter is set
(briefs have no status); a `--tag` filter still applies to them. `--limit-findings` truncates the
listed `findings` only — `summary.finding_count` always reflects the full total. Finding order is
deterministic.

## Storage & output

`context-doctor` and `context-doctor bundle` read the ledger and write nothing to
`.chimera-memory`; on an absent store the report is simply empty and no store is created.
`--output` writes only the file you name. The bundle writes `CONTEXT_DOCTOR.md`,
`context-doctor.json`, `manifest.json`, and `README.md` into the output directory (sha256 + bytes
manifest), and refuses a non-empty directory without `--force`.

## MCP

The read-only MCP tool `chimera_context_doctor` (input: `root` / `status` / `tag` /
`limit_findings`) returns the same report JSON. It is available without `--allow-write`, never
creates or mutates a store, and never executes checks. The bundle writer is CLI-only.

## Non-goals

The Context Doctor is an advisory hygiene report, not a gate. It does not approve, score, rank,
certify, route, execute, or run an agent, and it emits no verdict. Wording stays neutral:
"finding", "suggested inspection", "review target", "missing referenced path".

## Example

```bash
chimera-memory work-brief add --title "…" --objective "…" --tag v0.29
BRIEF_ID=$(chimera-memory work-brief list --json | jq -r '.work_briefs[0].brief_id')
chimera-memory work-session start --brief "$BRIEF_ID" --thread-dir review-thread --tag v0.29
chimera-memory context-doctor --tag v0.29
chimera-memory context-doctor --json --output CONTEXT_DOCTOR.md
```
