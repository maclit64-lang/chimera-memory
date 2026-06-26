# Harness Lite

Harness Lite is a local **run-observation ledger**: it records what a command/check/tool
invocation was, where and when it ran, the exit code if known, bounded and redacted stdout/stderr
previews, and how the observation attaches to a Work Session. It is a local observation bridge —
not an autonomous execution platform, not a correctness engine, not a merge gate, and not a task
router.

An exit code is **recorded, not interpreted as a verdict**. Statuses are neutral: `completed`,
`interrupted`, `unknown`. Generated wording uses "exit code 0" / "nonzero exit code" /
"recorded" / "observed" rather than outcome judgments.

```bash
chimera-memory harness record --command "uv run pytest" --exit-code 0 --work-session SESSION_ID
chimera-memory harness run --command "python -c 'print(123)'" --work-session SESSION_ID
chimera-memory harness list --work-session SESSION_ID --json
chimera-memory harness show RUN_ID --markdown
```

## Record mode vs run mode

- **`record`** — register a command that ran *elsewhere*. Chimera does **not** execute anything;
  it stores what you report (command, cwd, reported exit code, note, tags). Use this for runs an
  agent or CI already performed.
- **`run`** — Chimera explicitly runs the command locally, **only because you invoked
  `harness run`**. There is no automatic, scheduled, or background execution. The command runs
  once, in the foreground; its exit code, duration, and bounded output previews are captured.

Both modes append one observation to the ledger.

### Exit policy for `harness run`

Recording the observation is the Chimera command's job. When recording the observation, the
`chimera-memory` process exits **0**; the command's own exit code is stored in `run.exit_code`
(and shown as "exit code 0" / "nonzero exit code (N)"). This keeps the observed command's outcome
from being conflated with whether Chimera recorded it. A nonzero command exit is an observation,
not a Chimera-command error.

## Storage and redaction

Runs append to `.chimera-memory/harness_runs.jsonl` (append-only). Reading never creates a store.

Harness Lite never stores unbounded output:

- stdout/stderr are stored as **bounded previews** (default 4096 bytes; override with
  `--max-output-bytes`). `output_truncated` marks when the captured output exceeded the limit.
- for `executed` runs, the **sha256 of the full captured stdout/stderr** is recorded
  (`stdout_sha256` / `stderr_sha256`) so the full output is fingerprinted without being stored.
- previews are passed through the local redaction helper; `redaction_applied` marks when a
  secret-like pattern was replaced. Do not rely on redaction as exhaustive — avoid running
  commands that emit secrets.

## Work Session integration

A run may attach to a session via `--work-session SESSION_ID`. The id is validated; if it resolves
to a session with a brief, the run's `brief_id` is populated. List a session's runs with:

```bash
chimera-memory work-session runs SESSION_ID --json
```

This is read-only and does not mutate session events. Harness runs never auto-create session
events.

## Session Closeout integration

A session closeout includes a compact, output-free `harness_runs` array (run_id, mode, command,
cwd, exit_code, status, check_label, redaction/truncation flags, artifact refs) and a
`## Harness runs` markdown section. Closeout remains read-only and executes nothing; runs are not
called checks that did or did not hold, and done-criteria are not inferred from them.

## Rollup / Context Doctor integration

The session rollup `summary` adds `harness_run_count`, `executed_run_count`, and
`recorded_run_count` (over the selected sessions) plus a `recent_harness_runs` list — counts only,
no ranking.

The Context Doctor adds three neutral finding kinds (kind only, no severity):

- `session_without_harness_runs` — a session has no attached run observations.
- `harness_run_without_session` — a run is not attached to a known session.
- `harness_run_output_truncated` — a run's output was truncated (full output is hashed, not
  stored).

Each finding suggests inspection (e.g. `chimera-memory harness list --work-session SESSION_ID`),
never a judgment.

## MCP read tools

Two read-only MCP tools are available without `--allow-write`:

- `chimera_harness_run_list` (root / work_session_id / brief_id / tag / limit) → compact runs.
- `chimera_harness_run_show` (root / run_id) → the full run record.

They never create or mutate a store and never execute commands. `harness run` and
`harness record` are **not** exposed over MCP.

## Harness Lite v1 — context + packet integration

Harness Lite v0 records explicit local run observations. **v1** surfaces those observations
wherever the next agent starts, wherever a reviewer inspects work, and wherever a packet/archive is
exported — additively, read-only, and without verdict language:

- **Branch Primer** (`branch-primer --work-session SESSION_ID`) gains a `harness_runs` array
  (compact, output-free), a `## Harness run observations` markdown section, and a
  `chimera-memory harness list --work-session SESSION_ID --json` entry in `suggested_first_read`.
- **Agent Kickoff Pack** (`branch-primer bundle --work-session SESSION_ID`) adds `HARNESS_RUNS.md`
  and `harness-runs.json` to the bundle (hashed in the manifest); no stdout/stderr previews.
- **Work Packet** gains `harness_runs` plus summary counts (`harness_run_count`,
  `executed_harness_run_count`, `recorded_harness_run_count`, `truncated_harness_run_count`) and a
  `## Harness run observations` section. `--session` narrows runs to that work session; otherwise
  the most-recent runs are shown (default 20). `--limit-harness-runs N` keeps the most-recent N
  (stored order). Bundles hash the updated `work-packet.json`; `inspect` still validates.
- **Work Packet diff** reports `harness_runs.added` / `.removed` by `run_id` (append-only, so
  status never changes), with added/removed counts in the markdown.
- **Harness candidates** (`harness candidates`) is a read-only `HarnessRun → candidate lesson`
  projection: conservative and mostly verbatim from each run's `note` / `check_label`, never
  saved automatically (review before saving a Tool Note). Fields: `candidate_id`,
  `source_run_ids`, `task_kind`, `tool_name` (`"harness"`), `workflow_name`, `lesson`, `evidence`,
  `caveat`, `tags`.
- **Context Doctor** adds `harness_run_with_redacted_preview` alongside
  `session_without_harness_runs`, `harness_run_without_session`, and
  `harness_run_output_truncated` (kind only; suggested inspection, never a judgment).
- **MCP** adds the read-only `chimera_harness_run_candidates` tool; the existing read tools that
  wrap the Work Packet now carry harness fields. All harness MCP surfaces are read-only and never
  execute commands; `harness run` / `harness record` remain CLI-only.

Every read surface reads the ledger and writes nothing; an exit code is recorded, not interpreted
as a verdict.

## Non-goals

Harness Lite does not run an agent, schedule or background-execute anything, spawn agents, launch
workflows, route work, score, rank, or emit a verdict (correctness / safety / approval / merge /
production-readiness). It records observations; an exit code is data, not a judgment.

## Example

```bash
chimera-memory work-session start --brief "$BRIEF_ID" --tag v0.30
SESSION_ID=$(chimera-memory work-session list --json | jq -r '.sessions[0].session_id')
chimera-memory harness run --command "python -c 'print(123)'" --work-session "$SESSION_ID" \
  --check-label "smoke" --tag v0.30
chimera-memory work-session runs "$SESSION_ID" --json
chimera-memory work-session closeout "$SESSION_ID" --json
```
