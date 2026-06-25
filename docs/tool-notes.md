# Tool Notes

Tool Notes are **manual, local, advisory operational lessons** — reusable notes about how a
tool or workflow worked on a kind of task. They are agent skill memory: where the rest of
Chimera Memory records *what happened* (evidence), *what settled* (claims), and *what the next
agent should know* (handoff), a Tool Note records *how the next agent should work*.

Notes are stored append-only in `.chimera-memory/tool_notes.jsonl`. They are never inferred,
ranked, or executed — you (or an agent) write them deliberately, and they are read back by
exact match only.

## CLI

Record a note:

```bash
chimera-memory tool-notes add \
  --task-kind large-repo-forensics \
  --tool parallel-agents \
  --workflow unit-card-specialist-fanout \
  --lesson "Use coverage manifests and Unit Cards before cross-cutting synthesis." \
  --evidence "2189/2189 files read; 31 Unit Cards; 31 manifests; 7 agents." \
  --caveat "High cost/time; monitor MCP failures." \
  --tag repo-forensics --tag orchestration
```

List / filter / limit (exact match, AND across filters; stored order, no ranking):

```bash
chimera-memory tool-notes list --json
chimera-memory tool-notes list --task-kind large-repo-forensics --tag repo-forensics
chimera-memory tool-notes list --limit 10
```

Suggest notes for a context:

```bash
chimera-memory tool-notes suggest --task-kind large-repo-forensics
chimera-memory tool-notes suggest --json --task-kind large-repo-forensics --limit 5
```

Show one note by exact id:

```bash
chimera-memory tool-notes show tn_<id>
chimera-memory tool-notes show tn_<id> --json
# -> {"schema_version": 1, "tool_note": {…} | null, "found": true | false}
```

## Handoff and preflight integration

`handoff` includes a `## Tool lessons` section (and a `tool_notes` JSON field). The same exact
filters apply, and `--limit-tool-notes N` caps how many are shown:

```bash
chimera-memory handoff --task-kind large-repo-forensics --limit-tool-notes 5
```

`preflight` surfaces matching lessons before work — quiet by default, shown only when a
tool-note filter is supplied:

```bash
chimera-memory preflight --task-kind large-repo-forensics
```

## MCP (for local agents)

Read tools are available without extra flags:

- `chimera_tool_notes_suggest` — exact-match filters (`task_kind` / `tool_name` /
  `workflow_name` / `tag`) plus optional `limit`.
- `chimera_tool_note_show` — exact `note_id` lookup; returns `found: false` when unknown.

Writing a note is **write-gated** and requires `--allow-write`:

```bash
chimera-memory mcp serve --allow-write
```

- `chimera_tool_note_add` — records one note (required: `task_kind`, `tool_name`, `lesson`).
  Without `--allow-write` it is hidden and rejected, exactly like the other write tools.

## Non-goals

Tool Notes are advisory only. They are **not** a correctness, safety, approval, merge, or
production-readiness signal, and not a form of verification. Chimera Memory does **not**:

- detect tool use, infer notes from logs, or create notes automatically;
- rank, score, or do fuzzy / semantic matching;
- spawn agents, launch workflows, or run commands;
- sync anywhere — everything stays in the local `.chimera-memory/` store.

A note is whatever you wrote; it does not assert that the workflow is correct or the best choice.

## Tool Activity & candidate lessons

A **Tool Activity** is an append-only local record of what a tool/workflow did. From recorded
activity, Chimera projects **candidate lessons** — proposed Tool Notes you review and (if you
want) save manually. Candidates are never saved automatically, never inferred or ranked, and
make no correctness/safety/approval/merge/production-readiness claim.

Record activity, then review candidates, then manually save the ones worth keeping:

```bash
chimera-memory tool-activity add \
  --task-kind large-repo-forensics \
  --tool parallel-agents \
  --workflow unit-card-specialist-fanout \
  --phase synthesis \
  --summary "7 agents synthesized 31 Unit Cards after 100% file coverage." \
  --evidence "2189/2189 files read; 31 Unit Cards; 31 manifests." \
  --caveat "High cost/time; one MCP failure observed." \
  --status completed --duration-seconds 12094 --cost-units 55.51 \
  --tag repo-forensics --tag orchestration

chimera-memory tool-activity list --json
chimera-memory tool-notes candidates --json --task-kind large-repo-forensics
```

Review candidates by exact filters (`--task-kind` / `--tool` / `--workflow` / `--tag`, AND
across filters) with an optional `--limit` (applied after filtering; stored order, no ranking):

```bash
chimera-memory tool-notes candidates --tool parallel-agents
chimera-memory tool-notes candidates --workflow unit-card-specialist-fanout
chimera-memory tool-notes candidates --json --task-kind large-repo-forensics --tag orchestration --limit 5
```

Inspect one candidate by exact id:

```bash
chimera-memory tool-notes candidates show cand_<id>
chimera-memory tool-notes candidates show cand_<id> --json
# -> {"schema_version": 1, "candidate": {…} | null, "found": true | false}
```

The candidate lesson is the activity's `summary` verbatim — a starting point to review and
rewrite before saving via `tool-notes add` (the manual save path). Candidate JSON echoes the
applied filters:

```json
{
  "schema_version": 1,
  "advisory": "candidate local operational lessons only; review before saving",
  "filters": {"task_kind": null, "tool_name": null, "workflow_name": null, "tag": null, "limit": null},
  "candidates": [ … ]
}
```

### Handoff and preflight surfacing

`handoff` and `preflight` can surface matching candidates, **quiet by default** — a candidate
section appears only when a candidate filter is supplied and matches:

```bash
chimera-memory handoff --candidate-task-kind large-repo-forensics --candidate-limit 5
chimera-memory preflight --candidate-task-kind large-repo-forensics
```

`handoff` adds a `candidate_tool_lessons` JSON field (empty unless a candidate filter is given)
and a `## Candidate tool lessons` markdown section. `preflight` adds a
`candidate_tool_lesson_advisory` object at the CLI layer; the receipt bundle is unchanged.

### MCP

- `chimera_tool_note_candidates` — read-only; projects candidates by exact
  `task_kind` / `tool_name` / `workflow_name` / `tag` (all optional, AND) with optional `limit`.
  Available without `--allow-write`; never creates a store.
- `chimera_tool_note_candidate_show` — read-only; exact `candidate_id` lookup; returns
  `found: false` when unknown. Available without `--allow-write`; never creates a store.
- `chimera_tool_activity_add` — **write-gated** (requires `--allow-write`); appends one activity
  to `tool_activity.jsonl`.

### Non-goals

Tool Activity is observational; candidates are advisory. Chimera does **not** auto-save a
candidate as a Tool Note, infer lessons, detect tool use, rank/score, fuzzy/semantic match,
spawn agents, run commands, or sync anywhere. Saving a candidate is always a manual step.

