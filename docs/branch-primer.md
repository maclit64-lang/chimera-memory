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
- With two or more snapshots and no `--since`, it includes a **latest-two** thread delta (claims /
  unresolved / tool lessons / candidate lessons changed since the previous snapshot).
- With `--since SNAPSHOT_ID` (requires `--thread-dir`), it diffs that exact snapshot against the
  thread's latest snapshot. Unknown ids or a thread with no latest snapshot fail cleanly.

The primer never writes to or mutates the thread, and never adds a snapshot.

```bash
chimera-memory branch-primer --thread-dir review-thread --since wp_<id>
```

The delta is exposed as `thread_delta` — `{mode: "latest-two" | "since", old_snapshot_id,
new_snapshot_id, diff}` (the `diff` is the `chimera_work_packet_diff` shape), or `null` when there
is no comparable pair. Markdown labels it `## Latest thread delta` or `## Thread delta since <id>`.

## Prompt header

`--prompt-header` emits a compact, pasteable **agent kickoff header** (text only) summarizing the
work state, first inspection targets, relevant tool lessons, candidate lessons, and the thread
delta. Paste it (or the bundled `AGENT_PROMPT_HEADER.md`) into a coding-agent prompt as starting
context.

```bash
chimera-memory branch-primer --prompt-header --thread-dir review-thread --since wp_<id>
```

## Agent Kickoff Pack bundle

`branch-primer bundle --output-dir DIR` writes a portable five-file pack:

```
DIR/
  AGENT_PROMPT_HEADER.md   # pasteable prompt header (read this first)
  BRANCH_PRIMER.md         # human-readable primer
  branch-primer.json       # machine-readable primer
  manifest.json            # file list + sha256 + byte counts
  README.md
```

It accepts the same filters plus `--thread-dir` / `--since`. Writing rules match the work-packet
bundle: it writes only into the output directory (never `.chimera-memory`), requires an existing
parent, refuses a non-empty directory without `--force`, and with `--force` overwrites only the
known bundle files. The manifest carries `artifact: "chimera_agent_kickoff_pack"`, the applied
`filters` (including `since`), the `primer_summary`, and a `files` list (the manifest does not hash
itself). Verify a pack with `branch-primer inspect DIR [--json]`.

## JSON shape

`schema_version`, `artifact: "chimera_branch_primer"`, `advisory`, `generated_at`, `filters`
(claim_id / session_id / status / task_kind / tag / thread_dir / since / limit_tool_notes /
limit_candidates), `summary` (shown_claim_count / open_or_unresolved_count /
next_inspection_target_count / tool_note_count / candidate_count / thread_snapshot_count), a
compact `work_packet` reference, `thread_delta` (or null), `next_inspection_targets`, `tool_notes`,
`candidate_tool_lessons`, and `suggested_first_read` (a list of things to inspect).

## MCP (read-only)

`chimera_branch_primer` returns the JSON primer; `chimera_branch_primer_prompt_header` returns
`{schema_version, artifact, prompt_header, summary}`. Both are read-only (available without
`--allow-write`), take the same optional filters plus `thread_dir` (resolved against `root` if
relative; the prompt-header tool also takes `since`), and never write, create a store, or mutate a
thread. Bundle export is CLI-only (it writes files).

## Non-goals

The Branch Primer and Agent Kickoff Pack are advisory and local. They are **not** a correctness,
safety, approval, merge, or production-readiness signal, and not a form of verification.
`suggested_first_read` and the prompt header are inspection summaries — they never instruct that
anything be done automatically, and there is no automatic agent run or prompt injection. The primer
does not save tool notes, run tools, spawn agents, launch workflows, score, route, rank, or sync.

## Harness run observations (v0.30)

With `--work-session SESSION_ID`, the primer adds a read-only `harness_runs` array (compact,
output-free), a `## Harness run observations` markdown section, and a
`chimera-memory harness list --work-session SESSION_ID --json` entry in `suggested_first_read`.
The Agent Kickoff Pack (`branch-primer bundle --work-session SESSION_ID`) adds `HARNESS_RUNS.md`
and `harness-runs.json` (hashed in the manifest; no stdout/stderr previews). An exit code is
recorded, not interpreted as a verdict. See [harness-lite.md](harness-lite.md).
