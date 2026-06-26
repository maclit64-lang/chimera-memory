# chimera-memory

Local-first reliability ledger for AI coding-agent work.

Records what an agent tried, which command verified it, what happened, and what receipt proves it. Everything stays on your machine — no cloud, no sync, no account required.

**Your AI agent says it's done. Chimera Memory makes it prove it.** It produces
**`PR_EVIDENCE.md`** — a local proof-carrying receipt for AI-written code that shows
which changed files have settled claim coverage, which evidence is weak, missing,
contradicted, or scope-drifted, and what the evidence does *not* prove. It scores
evidence quality, not code correctness.

Generate it on your branch:

```bash
chimera-memory xray generate --base main --head HEAD --output PR_EVIDENCE.md
```

## What you get

- **`PR_EVIDENCE.md`** — a local, proof-carrying receipt for the PR diff.
- A verdict banner (`REVIEW REQUIRED` / `COVERED — review still advised`).
- **Evidence Quality**, **Test Integrity**, and **Evidence Coverage** warnings.
- An **optional CI evidence gate** (`fail-on`) — off by default.

## Choose your mode

**1. Local receipt (CLI).**

```bash
chimera-memory xray generate --base main --head HEAD --output PR_EVIDENCE.md
```

**2. GitHub Action — advisory (default).** Posts the receipt on every PR; never fails CI.

```yaml
- uses: maclit64-lang/chimera-memory@v0.27.0
  with:
    fail-on: never
```

**3. GitHub Action — gated (opt-in).** Fails the PR only when the evidence policy is not met.

```yaml
- uses: maclit64-lang/chimera-memory@v0.27.0
  with:
    fail-on: warnings
```

> Until `v0.27.0` is tagged and published, pin the release branch or a commit SHA
> for testing (e.g. `maclit64-lang/chimera-memory@oss/memory-v0270-rc`). The gate
> enforces evidence policy — it does not prove code is correct or incorrect.

## Warning types

| Warning family | Meaning |
|---|---|
| Evidence Quality | The recorded commands may be weak — lint-only, zero tests collected, or green-only with no regression test. |
| Test Integrity | The diff may weaken tests — added skips/xfails, focus-only tests, or a deleted test file. |
| Evidence Coverage | Changed source exists, but no settled command obviously targets it or nearby tests. |
| Local Relapse | A current claim resembles a previously contradicted local claim in the same ledger (overlapping scope plus matching intent or command fingerprint). |

Warnings are review prompts. They do not prove the code is wrong or correct.

## What this does not prove

Chimera Memory scores **evidence quality, not code correctness**. It shows which
claims settled against which checks at which declared scope. It does **not** prove
the code is correct, secure, or complete, and it does not rank or route models.

## FAQ

**Does Chimera Memory prove my code is correct?** No. It scores evidence quality,
not code correctness.

**What do I do when the verdict says review required?** Add targeted evidence (a
test that names the changed file or module), resolve contradicted claims, or
review the changed files manually.

**Should I fail CI by default?** No — start in advisory mode (`fail-on: never`).
Enable a stricter `fail-on` once your team agrees on a policy.

**What's the best first command?** Generate `PR_EVIDENCE.md` for a PR diff:
`chimera-memory xray generate --base main --head HEAD --output PR_EVIDENCE.md`.

**Does it send my code to a cloud service?** No. Everything stays on your machine
— no cloud, no sync, no account.

## Trust and redaction

Chimera Memory is local-first and generates receipts from local git/command
evidence. Witness excerpts are redacted for common secret patterns at capture
time (best-effort, not exhaustive). See
[docs/trust-and-redaction.md](../../docs/trust-and-redaction.md) for what is
captured, what is not, and what the tool does not prove — and review receipts
before sharing them publicly.

## Proof debt

`chimera-memory proof-debt` lists local claims and receipts that still need
stronger evidence — unsettled/contradicted claims, review-required receipts, and
evidence quality / test-integrity / evidence-coverage warnings. Advisory and
local-only; it does not prove code is correct or incorrect. See
[docs/proof-debt.md](../../docs/proof-debt.md).

```bash
chimera-memory proof-debt          # text summary
chimera-memory proof-debt --json   # machine-readable
```

## Public alpha

Chimera Memory is in public alpha for developers using AI coding agents.

It is a local-first CLI that records what an AI coding agent claimed before editing, runs your real checks, settles the result, and generates `PR_EVIDENCE.md` for review.

```bash
pip install chimera-memory==0.30.0
chimera-memory demo
```

Start here: [docs/public-alpha.md](../../docs/public-alpha.md)

## Operational memory and Work Packets

Beyond evidence receipts, Chimera Memory records **local operational memory** — how
agents worked — and packages it for review. Everything here is local and advisory;
none of it is a correctness, safety, approval, merge, or production-readiness signal.

- **Tool Notes** — manual, local, reusable lessons about how a tool or workflow
  worked on a kind of task (`tool-notes add/list/suggest/show`). Exact-match recall;
  never inferred or ranked.
- **Tool Activity** — append-only records of local tool/workflow activity
  (`tool-activity add/list`).
- **Candidate Lessons** — review-before-save lessons projected from recorded
  activity (`tool-notes candidates`); saving one is always a manual `tool-notes add`.
- **Work Packets** — one portable advisory artifact (Markdown or JSON) that gathers
  claims, open items, tool lessons, and candidate lessons (`work-packet`), with
  exportable, hash-manifested **bundles** (`work-packet bundle` / `inspect` / `diff`).
- **Review Threads** — a local timeline that collects packet snapshots over time
  (`work-packet thread add/list/inspect/diff-latest/diff`).

See [docs/tool-notes.md](../../docs/tool-notes.md) and
[docs/work-packet.md](../../docs/work-packet.md).

## Agent work lifecycle (v0.29)

Chimera Memory also records an agent's **work lifecycle** — the task it was asked to do, the
context it starts with, and the review it leaves behind. Like the rest, these surfaces are local
and advisory; none is a correctness, safety, approval, merge, or production-readiness signal, and
none runs an agent, executes checks, scores, ranks, or routes.

- **Work Brief** — the requested task as a local input contract (objective, scope, constraints,
  checks to report, done criteria): `work-brief add/list/show`.
- **Branch Primer** — local starting context ("read these things before you begin"), optionally
  written as a portable **Agent Kickoff Pack**: `branch-primer` / `branch-primer bundle`.
- **Work Session** — an event-sourced lifecycle envelope tying a brief, review thread, snapshots,
  and artifacts to one task, with neutral statuses: `work-session start/attach/close`.
- **Session Closeout Pack** — an end-of-session summary (state, brief, snapshot delta, reported
  checks, done observations, carryover): `work-session closeout` / `closeout-bundle`.
- **Session Rollup / Carryover Inbox** — a read-only review board across sessions:
  `work-session rollup` / `rollup-bundle`.
- **Context Doctor** — advisory findings about missing, stale, or incomplete context before
  another agent continues: `context-doctor` / `context-doctor bundle`.
- **Harness Lite** — a local run-observation ledger: record a command that ran elsewhere, or
  explicitly run one locally, and attach the observation to a session. An exit code is recorded,
  not interpreted as a verdict: `harness record` / `harness run` / `harness list` / `harness show`.
  Run observations can be exported as a portable, redacted, hash-manifested **Harness Evidence
  Bundle** (`harness bundle` / `bundle-inspect` / `bundle-diff`) for external tooling.

The read views are also exposed as read-only MCP tools; every write, lifecycle, and bundle
operation stays CLI-only. See the overview in
[docs/v0.29-agent-lifecycle.md](../../docs/v0.29-agent-lifecycle.md), and
[docs/work-brief.md](../../docs/work-brief.md),
[docs/branch-primer.md](../../docs/branch-primer.md),
[docs/work-session.md](../../docs/work-session.md),
[docs/context-doctor.md](../../docs/context-doctor.md),
[docs/harness-lite.md](../../docs/harness-lite.md), and
[docs/harness-evidence-bundle.md](../../docs/harness-evidence-bundle.md).

## Install

```bash
pip install chimera-memory
```

Requires Python 3.12+. Installs `chimera-memory-types`, `pydantic`, and `filelock` automatically.

> **macOS note:** System `python3` may be 3.9. Use `python3.12` or `uv` explicitly:
>
> ```bash
> # With a system Python 3.12:
> python3.12 -m venv .venv && source .venv/bin/activate
> pip install chimera-memory
>
> # Or with uv:
> uv venv --python 3.12 .venv && source .venv/bin/activate
> pip install chimera-memory
> ```

## Try it in 60 seconds

```bash
chimera-memory demo
```

This runs a safe local demo in a temp directory — no project mutation, no network. It shows the full flow: init → wrap → verify → receipt bundle → inspect.

## Project check suites

Define your verification commands once, run them repeatedly:

```bash
chimera-memory init
chimera-memory checks init --preset python
chimera-memory checks run --bundle --output-dir ./run-output
```

This creates `report.md`, `report.json`, and a `receipt/` bundle. Inspect the result:

```bash
chimera-memory bundle inspect ./run-output/receipt
```

Compare two runs:

```bash
chimera-memory bundle diff ./old-run/receipt ./new-run/receipt
```

## Claude Code hooks (automatic evidence)

Install Chimera hooks for automatic claim-locked evidence in Claude Code sessions:

```bash
chimera-memory hooks install
```

Then create `.chimera/hooks.toml` in your project root:

```toml
[claude_hooks]
auto_lock = true
scope_path = "."          # use "." to start; narrow only when confident

falsifiers = [
  ["python3", "-m", "pytest", "tests/test_my_area.py", "-q"]
]

must_not_break = [
  ["python3", "-m", "pytest", "-q"]
]
```

When you submit a prompt in Claude Code, the UserPromptSubmit hook derives the
intent and auto-locks a claim. When Claude finishes a turn, the Stop hook
settles the claim and generates `PR_EVIDENCE.md`. See
[docs/examples/claude-hooks-setup.md](../../docs/examples/claude-hooks-setup.md).

**scope_path tip:** Start with `scope_path = "."` so that co-changed tests,
docs, and config files are included in scope. Use a narrower path only when
your task is strictly limited to one package or directory.

**SCOPE_DRIFT:** If settlement reports `SCOPE_DRIFT`, it means your checks
passed but some changed files were outside the declared `scope_path`. This is
honest review signal, not a test failure. Common first-run cause: `.gitignore`
or `.chimera/hooks.toml` changed alongside your code.

## Local MCP tools for coding agents

`chimera-memory mcp serve` starts a local stdio MCP server. MCP-capable agents
(Claude, Codex, Cursor, etc.) can call Chimera's claim and X-Ray tools directly:

```json
{
  "mcpServers": {
    "chimera-memory": {
      "command": "chimera-memory",
      "args": ["mcp", "serve", "--allow-write"]
    }
  }
}
```

Tools: `chimera_claim_validate`, `chimera_claim_lock_auto`, `chimera_claim_show`,
`chimera_claim_list`, `chimera_claim_settle` (requires `--allow-execute`),
`chimera_xray_generate`.

See [docs/examples/mcp-local-tools.md](../../docs/examples/mcp-local-tools.md).

## AI PR Evidence / Merge X-Ray

### Agent-seam auto-lock (v0.23)

Agents and hooks can create sealed claims without writing a `claim.toml` file:

```bash
CHIMERA_INTENT="fix checkout null dereference" \
CHIMERA_SCOPE_PATH="packages/cart" \
CHIMERA_FALSIFIERS_JSON='[["uv","run","pytest","tests/test_checkout.py::test_empty_cart"]]' \
CHIMERA_MUST_NOT_BREAK_JSON='[["uv","run","pytest","tests/test_cart.py"]]' \
chimera-memory claim lock --auto --json
```

This is the stable primitive that future MCP/hooks integrations will call.
Preview without locking: `chimera-memory claim lock --auto --dry-run --json`.
See [docs/examples/agent-seam-auto-lock.md](../../docs/examples/agent-seam-auto-lock.md).

Chimera can now produce local PR evidence reports for AI-assisted coding work.

A claim can be locked before edits with an intent, scope, falsifier, and
must-not-break checks. After the work, Chimera settles that claim against the
pre-committed checks and generates a Merge X-Ray showing which changed files
have settled evidence and which remain evidence-dark.

```bash
# 1. Lock a claim BEFORE editing (sealed, scope-bound)
chimera-memory claim lock --from-file claim.toml

# 2. Do the work, then settle against the pre-committed checks only
chimera-memory claim settle <claim_id>

# 3. Generate the PR evidence report
#    If your changes are committed on a branch:
chimera-memory xray generate --base main --head HEAD --output PR_EVIDENCE.md

#    If your changes are still uncommitted (working-tree mode):
chimera-memory xray generate --output PR_EVIDENCE.md
```

> **Committed vs uncommitted:** `--base`/`--head` uses `git diff` between two
> refs and excludes untracked files — recommended for PR review. Without
> `--base`, Chimera reads the current working tree including unstaged changes.

Example `claim.toml`:

```toml
intent = "fix checkout null dereference"
scope_path = "packages/cart"
predicted_outcome = "all pass"

[[falsifiers]]
command = ["pytest", "tests/test_checkout.py::test_empty_cart"]

[[must_not_break]]
command = ["pytest", "tests/test_cart.py"]
```

The Merge X-Ray (`PR_EVIDENCE.md`) shows the verdict, settled claims,
evidence-dark changes, scope drift, and a reviewer-focus list. It reports
**settled evidence, not proof of correctness** — coverage is path-based
("covered by declared claim scope"), never a guarantee that code is tested or
correct. See [docs/examples/claim-locked-coding.md](../../docs/examples/claim-locked-coding.md)
and [docs/examples/pr-evidence-example.md](../../docs/examples/pr-evidence-example.md).

**Evidence Quality Warnings.** When the settled evidence looks weak, the receipt
adds an advisory `## Evidence Quality Warnings` section — for example lint-only
evidence, zero tests collected, or a bug-fix claim with no regression test. These
are review prompts: they flag weak or missing evidence and never prove the code
is wrong or correct.

**Test Integrity Warnings.** When a diff appears to weaken the tests — an added
skip/xfail, a focus-only marker (`it.only`, `fdescribe`), or a deleted test file
— the receipt adds an advisory `## Test Integrity Warnings` section. These are
review prompts too: they do not prove the code is wrong or correct.

**Evidence Coverage Warnings.** When source files change but the settled commands
don't obviously target them or nearby tests, the receipt adds an advisory
`## Evidence Coverage Warnings` section ("no obvious targeted evidence for changed
source"). Like the others, these are review prompts — they do not prove the code
is wrong or correct.

**Local Relapse Warnings.** When a current claim resembles a previously
contradicted local claim in the same Chimera Memory ledger — overlapping scope
plus the same intent or a shared specific command fingerprint — the receipt adds
an advisory `## Local Relapse Warnings` section naming the prior claim. Local
Relapse Warnings compare the current receipt against previously contradicted
claims in the same local Chimera Memory ledger. They are review prompts, not
proof that a bug returned, and never claim recurrence, correctness, or safety.

### Run it on every pull request (GitHub Action)

Add Chimera Memory to a repository's pull-request workflow to post the receipt
automatically. The reusable Action generates `PR_EVIDENCE.md` for the PR diff and
surfaces it three ways: a sticky PR comment, a job step summary, and an uploaded
artifact. On fork PRs — where the comment token is restricted — it falls back to
the step summary and artifact without failing the job. Like the local receipt, it
reports evidence quality, not code correctness.

```yaml
name: Chimera Memory Evidence

on:
  pull_request:

permissions:
  contents: read
  pull-requests: write

jobs:
  evidence:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: maclit64-lang/chimera-memory@v0.27.0
        with:
          base: ${{ github.event.pull_request.base.sha }}
          head: ${{ github.sha }}
          output: PR_EVIDENCE.md
```

Full workflow with fork notes: [docs/examples/github-actions/pr-evidence.yml](../../docs/examples/github-actions/pr-evidence.yml).

> **Action availability:** `@v0.27.0` resolves once the `v0.27.0` release tag —
> the stacked product RC — is pushed to `maclit64-lang/chimera-memory`. Until
> then, pin the RC branch or a commit SHA for testing — e.g.
> `maclit64-lang/chimera-memory@oss/memory-v0270-rc`. (v0.26.5 remains the
> separate frozen launch-polish RC; an external release still depends on
> resolving the PyPI publish.)

**Optional: fail the PR on weak evidence.** The Action is advisory by default
(`fail-on: never`). Set a stricter policy to fail CI when evidence is weak:

```yaml
with:
  fail-on: warnings   # also: review-required, contradicted,
                      # evidence-quality-warnings, test-integrity-warnings, …
```

The gate enforces evidence policy — it does not prove the code is correct or
incorrect — and the receipt is still produced when the gate fails.

## Quickstart (5 commands)

```bash
# 1. Initialise the local ledger (also adds .chimera-memory/ to .gitignore)
chimera-memory init

# 2. Start a session
chimera-memory session start \
  --branch feat/my-branch \
  --task-label "fix type errors" \
  --agent kiro \
  --model claude-sonnet-4.6 \
  --harness-id kiro-cli

# 3. Wrap a verification command (test, lint, typecheck, …)
chimera-memory wrap \
  --failure-origin organic_real \
  --scope-path . \
  --verification-scope package \
  -- pytest tests/ -q

# 4. End the session
chimera-memory session end --status PASSED

# 5. View the receipt
chimera-memory receipt latest
```

## Onboard an agent in 90 seconds

Get the full session/wrap/repair-loop protocol for your agent:

```bash
chimera-memory agent-guide --agent generic   # or: kiro, codex
```

Generate a copy-paste session scaffold for your package:

```bash
chimera-memory template dogfood --scope-path packages/chimera-memory
```

Prompt templates for sustained use are in `docs/prompts/` in the [source repo](https://github.com/maclit64-lang/chimera-memory):

- `kiro-dogfood.md` — Kiro agent session discipline
- `generic-agent-dogfood.md` — Any agent
- `release-closeout.md` — Release closeout checklist

## Health check

```bash
chimera-memory doctor
chimera-memory doctor --json
```

`doctor` is read-only. It checks:
- Is `.chimera-memory/` initialized?
- Is `.chimera-memory/` in `.gitignore`?
- Is there an active session?
- Claim count and integrity status
- M2B readiness level

Exit code: `0` = healthy, `1` = warnings (e.g. no active session), `2` = critical (e.g. not initialized).

## Is my ledger healthy?

`doctor` also audits whether the ledger is being used correctly:

```bash
chimera-memory doctor        # shows Evidence Hygiene section
chimera-memory doctor --json # machine-readable, includes evidence_hygiene + next_actions
```

Evidence hygiene checks:
- Scoped claim ratio (claims with `--scope-path` set)
- Unknown `failure_origin` count (claims missing classification)
- Repair-loop completeness (loops with `same_scope_after_fix`)
- Orphaned repair phases (`--repair-phase` without `--repair-loop-id`)
- Test/synthetic and invocation-artifact claim counts

If issues are found, `doctor` prints actionable next steps.

## Preflight Intelligence (v0.6)

Before starting work, surface historical failures, repair-loop lessons, and hygiene warnings:

```bash
chimera-memory preflight --from-git
chimera-memory preflight --scope-path packages/chimera-memory
```

Shows:
- Historical failures in the relevant scope (organic_real + controlled_real)
- Repair-loop lessons (what failed, was it fixed?)
- Hygiene warnings (invocation_artifact issues — not product defects)
- Recommended verification commands

Not M2B scoring or model ranking. Advisory only.

## CI receipt bundle

Produce a full CI-ready artifact bundle (receipt, failures, reliability, preflight, GitHub summary):

```bash
chimera-memory receipt bundle \
  --output-dir ./ci-bundle \
  --include-preflight \
  --from-git
```

Upload `ci-bundle/` as a CI artifact to preserve receipts across runs.

## Evidence dry-run

Export claims as a portable evidence bundle and inspect what a merge would do:

```bash
chimera-memory evidence bundle --output-dir ./evidence
chimera-memory evidence import ./evidence --dry-run --json
```

Write-import is not available. Dry-run only.

## M2B readiness

```bash
chimera-memory m2b-readiness
```

Shows whether the local ledger has accumulated sufficient repair-loop evidence to consider M2B (model-to-baseline) comparison. This is a local readiness gate, not a scoring system.

Run `chimera-memory m2b-readiness --explain` to see what evidence is missing before scoring can be trusted.

## What is not built

| Capability | Status |
|---|---|
| M2B drift scoring | Not built |
| Model ranking / routing | Not built |
| Hosted / cloud sync | Not built |
| Remote team ledger | Not built |
| Evidence write-import | Not built (dry-run only) |
| Dashboard or UI | Not built |

## Platform support

| Platform | Status |
|---|---|
| macOS | ✅ Tested |
| Linux | ✅ Tested (CI and Docker) |
| Windows | ⚠️ Not officially tested in 0.1.x |

No intentional Windows lockout is known. If you encounter a Windows-specific issue, please open an issue.

## Troubleshooting

**`preflight --from-git` shows `source: none`**

This is expected when the working tree is clean (no modified files). Use `--scope-path <dir>` to specify a target directory explicitly:

```bash
chimera-memory preflight --scope-path src/
```

**`receipt latest` shows "No closed sessions"**

You need to complete a session first:

```bash
chimera-memory session start --branch <branch> --task-label <label> --agent <agent> --model <model> --harness-id <id>
# ... run chimera-memory wrap commands ...
chimera-memory session end --status PASSED
```

**`m2b-readiness` shows BLOCKED**

The ledger needs at least 5 genuine `organic_real` failures followed by fixes to clear the gate. Run real verification cycles — do not manufacture failures.

**`verify` shows `LEGACY_UNSIGNED`**

Claims recorded before the integrity chain was introduced show as `LEGACY_UNSIGNED`. This is informational. Zero `Broken records` is the signal that matters.

## Security note

`chimera-memory wrap` records the command string and bounded stdout/stderr. Built-in redaction removes tokens matching common secret patterns. However:

- Do not pass secrets, passwords, or API keys as literal command arguments.
- The `.chimera-memory/` directory contains your local ledger. Do not commit it to version control.

Add to `.gitignore` (done automatically by `chimera-memory init`):

```
.chimera-memory/
```

## Test fixture isolation

When writing tests that call `chimera-memory wrap` as a fixture, set `CHIMERA_DQ_NO_WRITE=1` to prevent test runs from writing to the real local ledger:

```bash
CHIMERA_DQ_NO_WRITE=1 chimera-memory wrap --failure-origin organic_real -- pytest tests/
```

The wrapped command runs normally and the exit code is preserved. No claims are written. A notice is printed.

**Do not set `CHIMERA_DQ_NO_WRITE=1` for real dogfood verification sessions.** It is for test fixtures only.

## License

MIT — see [LICENSE](LICENSE)
