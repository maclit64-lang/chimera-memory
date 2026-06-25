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

## Non-goals

A Work Session is advisory and local. It is **not** a correctness, safety, approval, merge, or
production-readiness signal, and not a form of verification. It does not run an agent, inject
prompts, execute tools, spawn agents, launch workflows, route, score, or sync. Statuses are
neutral lifecycle states (open/blocked/closed/unknown) — never "passed", "verified", or similar.

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
```
