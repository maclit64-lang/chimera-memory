# Work Packet

A **Work Packet** is one portable, local, advisory review artifact. It composes the existing
read-only projections into a single packet a human or the next agent can review:

- **Claims** — what claims exist, and which settled, contradicted, or remain unresolved.
- **Open / unresolved evidence** and **next inspection targets** — what to look at first.
- **Tool lessons** — the manual, local operational lessons that apply.
- **Candidate tool lessons** — candidates available to review before saving as Tool Notes.
- The **filters** that were applied.

It is built by reusing the handoff builder (claims / open items / inspection targets / tool
notes / counts) and the candidate-lesson selector — no projection logic is duplicated.

## Work Packet vs handoff

```
handoff     = concise daily / next-agent summary
work-packet = portable review packet combining evidence + operational memory
```

The Work Packet does not replace `handoff`; it is the larger, portable artifact. Generating a
Work Packet reads the ledger and changes nothing.

## Generating

Markdown is the default; `--json` emits the machine-readable packet:

```bash
chimera-memory work-packet            # markdown (default)
chimera-memory work-packet --markdown
chimera-memory work-packet --json
```

Write it to a file explicitly (the parent directory must already exist; the memory store is
never modified):

```bash
chimera-memory work-packet --output CHIMERA_WORK_PACKET.md
chimera-memory work-packet --json --output chimera-work-packet.json
```

## Filters

All filters are exact-match and combine with AND; limits apply after filtering; stored order, no
ranking:

```bash
chimera-memory work-packet --claim CLAIM_ID
chimera-memory work-packet --session SESSION_ID
chimera-memory work-packet --status validated
chimera-memory work-packet --task-kind large-repo-forensics
chimera-memory work-packet --tag repo-forensics
chimera-memory work-packet --limit-tool-notes 5
chimera-memory work-packet --limit-candidates 5
```

- `--claim` / `--session` / `--status` narrow the claim view.
- `--task-kind` / `--tag` narrow both **tool notes** and **candidate lessons**.
- `--limit-tool-notes` / `--limit-candidates` cap each list after filtering.

## Tool notes and candidate lessons

Tool notes are the manual lessons you have saved. Candidate lessons are projected from recorded
tool activity and shown so you can review them — saving a candidate is always a separate, manual
`tool-notes add`. The packet never saves a candidate for you.

## JSON shape

```json
{
  "schema_version": 1,
  "artifact": "chimera_work_packet",
  "advisory": "local evidence and operational memory summary only; not a correctness, safety, approval, merge, production-readiness, or speed guarantee",
  "generated_at": "…",
  "filters": {"claim_id": null, "session_id": null, "status": null, "task_kind": null, "tag": null, "limit_tool_notes": null, "limit_candidates": null},
  "summary": {"event_count": 0, "settled_claim_count": 0, "shown_claim_count": 0, "open_or_unresolved_count": 0, "next_inspection_target_count": 0, "tool_note_count": 0, "candidate_count": 0},
  "claims": [],
  "open_or_unresolved": [],
  "next_inspection_targets": [],
  "tool_notes": [],
  "candidate_tool_lessons": []
}
```

## MCP (for local agents)

`chimera_work_packet` is a read-only tool, available without `--allow-write`. It takes the same
optional filters (`claim_id` / `session_id` / `status` / `task_kind` / `tag` / `limit_tool_notes`
/ `limit_candidates`) and returns the same JSON packet. It never creates a store or mutates files.

## Non-goals

The Work Packet is advisory and local. It is **not** a correctness, safety, approval, merge, or
production-readiness signal, and not a form of verification. Building it does **not** save tool
notes, run tools, spawn agents, launch workflows, score, route, rank, fuzzy/semantic match, or
sync anywhere — everything stays in the local `.chimera-memory/` store and reads change nothing.
