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
