# Consequence Observations

A **Consequence Observation** is a local, neutral *inspection target* derived by an
explicit scan of existing [Memory](v0.29-agent-lifecycle.md) and
[Harness Lite](harness-lite.md) evidence. It records something worth looking at —
a work session with no attached harness observations, a harness run that recorded
a nonzero exit code, a run whose output preview was truncated or redacted, or a
reported check with no matching harness run — together with suggested checks to
inspect.

It is an **inspection-target ledger, not a gate.**

## What a consequence observation is

A small, append-only record that points at a subject (a work session or a harness
run) and a neutral observation kind, with suggested checks and evidence refs. It
is the next bridge from recorded Memory/Harness evidence toward a future
Engine/Harness/Forge loop: a neutral layer that says "this is worth inspecting"
without deciding anything.

## What it is not

It does not say the work is correct, complete, or appropriate to merge. It does
not rank or grade observations, and it attaches no ordering of importance. It never
interprets a nonzero exit code as a judgment — an exit code is recorded, not
labelled. It routes nothing, approves nothing, and executes nothing.

## How scan works

```bash
chimera-memory consequence scan --work-session SESSION_ID
chimera-memory consequence scan --brief BRIEF_ID
chimera-memory consequence scan --tag TAG
chimera-memory consequence scan --limit N
chimera-memory consequence scan --dry-run
chimera-memory consequence scan --json
```

A scan reads the existing local work-session, work-brief, and harness ledgers and
applies conservative v0 rules:

- **session_without_harness_runs** — a work session has no linked harness runs;
  suggested checks come from the Work Brief when available.
- **harness_run_nonzero_exit_code_observed** — a harness run recorded a nonzero
  exit code (recorded, not interpreted).
- **harness_run_output_truncated** — a run's output preview was truncated.
- **harness_run_preview_redacted** — a run's preview had redaction applied.
- **reported_check_without_matching_harness_run** — a session reported a check
  with no harness run whose check label or command matches (literal match only).

Each observation gets a deterministic `observation_id` derived from its
`schema_version`, `observation_kind`, `subject`, `evidence_refs`, and
`suggested_checks`.

## Why scan is explicit

A scan is the only write path, and it writes only when you run it without
`--dry-run`. Nothing scans automatically — not closeout, not rollup, not the work
packet. `--dry-run` previews the observations a scan would record without writing
anything. This keeps the ledger a deliberate, reviewable record rather than a
background process.

De-duplication is deterministic: a scan appends an observation only when its
`observation_id` is not already present, so re-scanning the same evidence records
nothing new.

## How list and show work

```bash
chimera-memory consequence list
chimera-memory consequence list --work-session SESSION_ID --kind KIND --tag TAG --limit N
chimera-memory consequence show OBSERVATION_ID
chimera-memory consequence show OBSERVATION_ID --json
```

`list` and `show` are read-only: they never create or mutate a store and execute
nothing. Exact-match filters combine with AND.

## How observations appear elsewhere

Already-recorded observations surface in the read-only review surfaces — **none of
these auto-scan**; they only show what an explicit scan already recorded:

- **Work Session** — `chimera-memory work-session consequences SESSION_ID` lists
  the observations attached to one session.
- **Session Closeout** — a compact `consequence_observations` array plus a
  `## Consequence observations` markdown section.
- **Session Rollup** — a `consequence_observation_count` summary field plus
  `recent_consequence_observations`.
- **Work Packet** — a compact `consequence_observations` array, a
  `consequence_observation_count` summary field, and a markdown section;
  `--session` narrows to one session.
- **Context Doctor** — an advisory `consequence_observation_without_session`
  finding when an observation is not attached to a known work session.

## MCP read-only tools

The local MCP server exposes two read-only tools without extra flags:
`chimera_consequence_observation_list` and `chimera_consequence_observation_show`.
They never create or mutate a store, execute nothing, and **do not expose scan** —
recording observations stays CLI-only.

## How this prepares the Engine/Harness/Forge bridge

Memory records what happened; Harness records local run observations; the Harness
Evidence Bundle makes those observations portable. Consequence observations add a
neutral layer on top: a deterministic, append-only ledger of inspection targets
derived from that evidence. A future Engine/Harness/Forge loop can read these
neutral targets as input without this layer making any decision — the ledger
proposes what to inspect; it never decides what to do.

Advisory only — a local inspection-target ledger; not a correctness, safety,
approval, merge, or production-readiness signal, and not a gate.
