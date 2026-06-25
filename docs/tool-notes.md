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
