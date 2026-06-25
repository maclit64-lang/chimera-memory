# Work Brief

A **Work Brief** is a local task brief — a kickoff contract that captures the *requested task*
before an agent starts work: its objective, in-scope and out-of-scope paths, constraints, checks
to report, done criteria, and links to starting context. It is an **input contract**, not an
output verdict.

Briefs are stored append-only in `.chimera-memory/work_briefs.jsonl`. Adding one is an explicit
write; listing and showing are read-only and never create a store.

## Work Brief vs Branch Primer vs Work Packet

```
work-brief    = the requested task (objective / scope / constraints / checks / done) — an INPUT
branch-primer = what to read before starting (work state + operational memory) — starting CONTEXT
work-packet   = a portable review packet of evidence + operational memory — a SNAPSHOT
```

A Work Brief states what you were asked to do; the Branch Primer and Work Packet describe the
local state you are working against. None of them is a correctness or approval signal.

## add / list / show

```bash
chimera-memory work-brief add \
  --title "Implement candidate lesson surfacing" \
  --objective "Add exact candidate filters, lookup, and quiet surfacing." \
  --task-kind memory-feature \
  --scope-path packages/chimera-memory/src/chimera_memory \
  --out-of-scope-path packages/chimera-engine \
  --constraint "No automatic ToolNote save." \
  --check "uv run pytest packages/chimera-memory/tests" \
  --done "Full suite passes." \
  --context-ref "branch-primer" \
  --tag v0.29

chimera-memory work-brief list [--json] [--task-kind K] [--tag T] [--limit N]
chimera-memory work-brief show BRIEF_ID [--json | --markdown]
```

`--title` and `--objective` are required (missing → exit 2). `add` prints the new `brief_id` and
writes only `work_briefs.jsonl`. `list` filters are exact-match and combine with AND; the limit
applies after filtering. `show` defaults to markdown; `--json` returns
`{schema_version, work_brief | null, found}`.

## Using `--brief` with the Branch Primer and kickoff bundles

```bash
chimera-memory branch-primer --brief BRIEF_ID
chimera-memory branch-primer --prompt-header --brief BRIEF_ID
chimera-memory branch-primer bundle --output-dir kickoff-pack --brief BRIEF_ID
```

With `--brief`, the primer JSON gains a compact `work_brief` object, the markdown gains a
`## Work brief` section, and the prompt header gains a `Task brief:` summary. The Agent Kickoff
Pack additionally writes `WORK_BRIEF.md` and `work-brief.json` (hashed in the manifest); the
pack README notes whether a work brief is included. A missing brief id exits cleanly (code 2).
Without `--brief`, all of these are unchanged.

## MCP (read-only)

`chimera_work_brief_list` (exact `task_kind` / `tag` + optional `limit`) and
`chimera_work_brief_show` (exact `brief_id`) are read-only tools, available without
`--allow-write`. They never write or create a store. Creating a brief stays CLI-only.

## Non-goals

A Work Brief is advisory and local. It is **not** a correctness, safety, approval, merge, or
production-readiness signal, and not a form of verification. It does not run an agent, inject
prompts, execute tools, spawn agents, launch workflows, route, score, or sync. It records the
task you were asked to do — nothing is executed or acted on automatically on its basis.
