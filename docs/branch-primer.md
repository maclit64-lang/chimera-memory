# Branch Primer

A **Branch Primer** is a local, read-only starting-context artifact: it tells the next agent
what to read before starting work on a branch. It composes existing projections — the Work
Packet plus an optional review-thread delta — into one concise, pasteable summary.

It answers: what is the current local work state, what is unresolved, what to inspect first,
which Tool Notes apply, which Candidate Lessons to review, and — if a review thread is supplied —
what changed since the previous packet.

## Branch Primer vs handoff vs Work Packet

```
handoff       = concise next-agent summary of claim/evidence state
work-packet   = portable review packet (evidence + operational memory), exportable as a bundle
branch-primer = starting-context primer: "read these things before you begin", with a thread delta
```

The primer does not replace handoff or the Work Packet; it points at them. It is **local work
context and operational memory** — advisory only, and a starting-context artifact, not a verdict.

## Use it before starting an agent run

```bash
chimera-memory branch-primer --task-kind large-repo-forensics --tag repo-forensics --thread-dir review-thread
chimera-memory branch-primer --json
chimera-memory branch-primer --output BRANCH_PRIMER.md
```

Markdown is the default; `--json` emits the machine-readable primer. Paste the markdown (or the
`suggested_first_read` list) into a coding-agent prompt as starting context.

## Filters

All filters are exact-match and combine with AND; limits apply after filtering; stored order, no
ranking:

- `--claim` / `--session` / `--status` narrow the claim view.
- `--task-kind` / `--tag` narrow tool notes and candidate lessons.
- `--limit-tool-notes` / `--limit-candidates` cap each list after filtering.

## Thread integration

`--thread-dir DIR` reads a review thread's `index.json`:

- If the thread is missing or invalid, the command fails cleanly with a non-zero exit (the primer
  is meant to be reliable context).
- With one snapshot, the primer reports the snapshot count and no delta.
- With two or more snapshots, it includes a **latest thread delta** (claims / unresolved / tool
  lessons / candidate lessons changed since the previous snapshot) and points at the latest packet.

The primer never writes to or mutates the thread, and never adds a snapshot.

## JSON shape

`schema_version`, `artifact: "chimera_branch_primer"`, `advisory`, `generated_at`, `filters`
(claim_id / session_id / status / task_kind / tag / thread_dir / limit_tool_notes /
limit_candidates), `summary` (shown_claim_count / open_or_unresolved_count /
next_inspection_target_count / tool_note_count / candidate_count / thread_snapshot_count), a
compact `work_packet` reference, `latest_thread_delta` (or null), `next_inspection_targets`,
`tool_notes`, `candidate_tool_lessons`, and `suggested_first_read` (a list of things to inspect).

## MCP (read-only)

`chimera_branch_primer` is a read-only tool, available without `--allow-write`. It takes the same
optional filters plus `thread_dir` (resolved against `root` if relative) and returns the same JSON
primer. It never writes, creates a store, or mutates a thread.

## Non-goals

The Branch Primer is advisory and local. It is **not** a correctness, safety, approval, merge, or
production-readiness signal, and not a form of verification. `suggested_first_read` is an
inspection list — it never instructs that anything be done automatically. The primer does not save
tool notes, run tools, spawn agents, launch workflows, score, route, rank, or sync.
