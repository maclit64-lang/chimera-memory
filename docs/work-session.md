# Work Session

A **Work Session** is a local task lifecycle envelope. It links one agent task to the Work Brief
that started it, the kickoff context / review thread used, and the packet snapshots and artifacts
attached for review. It is a session envelope, not a verdict.

It is **event-sourced**: events are appended to `.chimera-memory/work_session_events.jsonl` and
folded into a read-only session projection. Statuses are neutral: `open`, `blocked`, `closed`,
`unknown`.

## How it relates to the other artifacts

```
work-brief    = the requested task (an INPUT contract)
branch-primer = what to read before starting (starting CONTEXT)
work-packet   = a portable review snapshot (evidence + operational memory)
review-thread = a timeline of packet snapshots
work-session  = the LIFECYCLE envelope tying a brief, thread, snapshots, and artifacts together
```

A session does not duplicate those artifacts; it references them and records what happened across
one task: which brief started it, which thread/kickoff context was used, which snapshots and
artifacts were attached, and whether it is open/blocked/closed.

## start / list / show / attach / close

```bash
chimera-memory work-session start --brief BRIEF_ID \
  [--thread-dir review-thread] [--kickoff-pack-dir kickoff-pack] [--tag T] [--note "…"]
chimera-memory work-session list [--json] [--status S] [--tag T] [--limit N]
chimera-memory work-session show SESSION_ID [--json | --markdown]
chimera-memory work-session attach-snapshot SESSION_ID --thread-dir review-thread --snapshot-id wp_…
chimera-memory work-session attach-artifact SESSION_ID --artifact-ref PATH_OR_LABEL
chimera-memory work-session close SESSION_ID --status closed --note "…"   # or --status blocked
```

`start` requires an existing `--brief` (missing → exit 2) and writes one `started` event; with
`--kickoff-pack-dir` it also writes an Agent Kickoff Pack from that brief (the pack is
brief-centric and does not require the review thread to exist yet). `attach-snapshot` validates
that the snapshot id exists in the thread (unknown → exit 2). `close` accepts only neutral
statuses. `start`/`attach`/`close` are explicit writes (only `work_session_events.jsonl`, plus the
optional kickoff pack directory); `list`/`show` are read-only and never create a store.

## Session projection

`show --json` returns `{schema_version, session, events}`, where `session` folds the events into:
`session_id`, `status`, `brief_id`, `thread_dir`, `kickoff_pack_dir`, `snapshot_ids`,
`artifact_refs`, `tags`, `event_count`, `created_at`, `updated_at`. The fold is deterministic.
`--markdown` renders the same projection with Session / Attached snapshots / Attached artifacts /
Events sections.

## Branch Primer integration

```bash
chimera-memory branch-primer --work-session SESSION_ID
chimera-memory branch-primer --prompt-header --work-session SESSION_ID
chimera-memory branch-primer bundle --output-dir kickoff-pack --work-session SESSION_ID
```

`--work-session` resolves the session and uses its `brief_id` (included as the Work Brief) and
`thread_dir` (thread context), and lists each attached snapshot under "Suggested first read". A
missing session id exits cleanly (code 2). (The flag is `--work-session` because `--session`
already means the claim-session filter.)

## MCP (read-only)

`chimera_work_session_list` (exact `status`/`tag` + `limit`) and `chimera_work_session_show`
(exact `session_id` → `{schema_version, session, events}`) are read-only tools, available without
`--allow-write`; they never write or create a store. Session start/attach/close stay CLI-only.

## Session closeout

After a task ends, a **closeout** summarizes what happened in the session. First record what the
agent *reported* (all advisory, neutral):

```bash
chimera-memory work-session report-check SESSION_ID --check "uv run pytest …" --note "Reported by agent."
chimera-memory work-session report-done SESSION_ID --done "Full tests pass." --status reported --note "…"
chimera-memory work-session note-carryover SESSION_ID --carryover "PyPI publish still blocked." --tag release-blocker
```

These append `check_reported` / `done_observed` / `carryover_noted` events. `report-done`'s
`--status` is a neutral observation (`reported` / `not_reported` / `not_applicable` / `unknown`,
default `reported`) — there is no pass/fail. Then build the closeout artifact:

```bash
chimera-memory work-session closeout SESSION_ID            # markdown (default)
chimera-memory work-session closeout SESSION_ID --json
chimera-memory work-session closeout SESSION_ID --output SESSION_CLOSEOUT.md
chimera-memory work-session closeout-bundle SESSION_ID --output-dir DIR [--force]
```

The closeout JSON (`artifact: "chimera_agent_session_closeout"`) carries the session projection,
the original `work_brief`, a `snapshot_delta`, `reported_checks`, `done_observations`, `carryover`,
`attached_artifacts`, and `suggested_review_targets`. **Snapshot delta** is a *local packet
comparison*: with two or more attached snapshots it diffs the first attached snapshot against the
latest (`mode: "first-vs-latest"`); with one it reports the single snapshot id; with none it is
`null`. **Reported checks** are checks the agent *said* it ran — they are not executed here.
**Done observations** are the agent's neutral notes about done-criteria — not a pass/fail judgment.

`closeout`/`closeout-bundle` read the ledger and write nothing to `.chimera-memory`; `--output`
and the bundle write only the files/directory you name. The bundle contains `SESSION_CLOSEOUT.md`,
`session-closeout.json`, `SESSION.md`, `session.json`, `WORK_BRIEF.md`, `work-brief.json`,
`manifest.json`, `README.md`, plus `snapshot-diff.json` (when a first-vs-latest delta exists) and
`kickoff-pack-ref.txt` (when a kickoff pack is associated); it refuses a non-empty output directory
without `--force`. `branch-primer --work-session` adds a compact "session closeout context
recorded" hint to its suggested first reads when closeout events exist (the primer does not depend
on closeout). The read-only MCP tool `chimera_work_session_closeout` returns the same closeout JSON
(available without `--allow-write`; never writes or creates a store); the reporting/bundle commands
stay CLI-only.
## Session review rollup

A **rollup** is a read-only board across *all* sessions — a local way to ask "what is open, what
is blocked, what recently closed, and what did agents leave behind?". It is a review view, not a
task queue or router.

```bash
chimera-memory work-session rollup                 # markdown (default)
chimera-memory work-session rollup --json
chimera-memory work-session rollup --status open
chimera-memory work-session rollup --status blocked
chimera-memory work-session rollup --tag v0.29
chimera-memory work-session rollup --carryover-tag release-blocker
chimera-memory work-session rollup --limit-sessions 10 --limit-carryover 20
chimera-memory work-session rollup --output SESSION_ROLLUP.md
chimera-memory work-session rollup-bundle --output-dir DIR [--force]
```

The rollup JSON (`artifact: "chimera_work_session_rollup"`) carries `filters`, a `summary`
(session / open / blocked / closed / reported-check / done-observation / carryover / attached-
snapshot / attached-artifact counts), the `sessions` list, `open_sessions`, `blocked_sessions`,
`recent_closeouts` (closed sessions, most-recently-updated first), `reported_checks`,
`done_observations`, the `carryover` inbox, and `suggested_review_targets`.

Filters are **exact** (no fuzzy / semantic matching); `--status` and `--tag` match a session's
status / tags, `--carryover-tag` matches a carryover item's tags. Limits apply **after** filters;
`--limit-carryover` truncates the listed carryover items only — `summary.carryover_count` still
reflects the full selected total. Session and event order is deterministic.

The **carryover inbox** is derived from `carryover_noted` events; each item keeps its
`session_id`, `created_at`, verbatim `carryover` text, `note`, `tags`, `source`, `brief_id`, and
`session_status`. The inbox is a *view*, not an automatic task queue: it does not create briefs or
sessions, rank, prioritize, or deduplicate, and user-authored text is preserved verbatim.
**Reported checks** are checks an agent *said* it ran; **done observations** are an agent's
neutral done-criteria notes — neither is executed or judged here. **Suggested review targets** are
a deterministic, unranked list of explicit pointers (open / blocked session ids, attached snapshot
ids, artifact refs, work-brief ids, review threads).

`rollup` / `rollup-bundle` read the ledger and write nothing to `.chimera-memory` — on an absent
store the rollup is simply empty (no store is created); `--output` and the bundle write only the
files/directory you name. The bundle contains `SESSION_ROLLUP.md`, `session-rollup.json`,
`manifest.json`, and `README.md`, and refuses a non-empty output directory without `--force`. The
read-only MCP tool `chimera_work_session_rollup` (root / status / tag / carryover_tag /
limit_sessions / limit_carryover) returns the same rollup JSON (available without `--allow-write`;
never writes or creates a store); the bundle command stays CLI-only.

## Non-goals

A Work Session is advisory and local. It is **not** a correctness, safety, approval, merge, or
production-readiness signal, and not a form of verification. It does not run an agent, inject
prompts, execute tools, spawn agents, launch workflows, route, score, rank, prioritize, or sync.
The rollup and carryover inbox are review views, never task queues or approval boards. Statuses
are neutral lifecycle states (open/blocked/closed/unknown) — never "passed", "verified", or
similar.

## Example sequence

```bash
chimera-memory work-brief add --title "…" --objective "…" --tag v0.29
BRIEF_ID=$(chimera-memory work-brief list --json | jq -r '.work_briefs[0].brief_id')
SESSION_ID=$(chimera-memory work-session start --brief "$BRIEF_ID" --thread-dir review-thread --tag v0.29)
chimera-memory work-packet thread add --thread-dir review-thread --label first
SNAP=$(jq -r '.snapshots[0].snapshot_id' review-thread/index.json)
chimera-memory work-session attach-snapshot "$SESSION_ID" --thread-dir review-thread --snapshot-id "$SNAP"
chimera-memory branch-primer --prompt-header --work-session "$SESSION_ID"
chimera-memory work-session close "$SESSION_ID" --status closed --note "Branch pushed."
chimera-memory work-session rollup
chimera-memory work-session rollup --status blocked --carryover-tag release-blocker --json
```
