# Chimera Memory — Alpha Trial Guide

This guide walks an external alpha tester through a first real trial of Chimera Memory on their own project.

---

## What this is

Chimera Memory is a local-first reliability ledger for AI coding-agent work.

It records what an agent tried to do, what command verified it, and what happened — keeping a settled evidence trail directly on your machine.

No cloud. No account. No sync.

---

## Requirements

- **Python 3.12 or later** (macOS system `python3` is often 3.9 — use `python3.12` or `uv`)
- Claude Code (for automatic hook-based evidence)
- A real project with at least one runnable test or check command

---

## Install

```bash
# With system Python 3.12:
python3.12 -m venv .venv && source .venv/bin/activate
pip install chimera-memory

# Or with uv:
uv venv --python 3.12 .venv && source .venv/bin/activate
pip install chimera-memory

# Verify:
chimera-memory --version
```

---

## Choose a repo

Pick a project you are actively working on. Good choices:

- A Python or TypeScript project with real tests
- A project where you will run at least one coding task during the trial
- A repo where you are not concerned about a few new files in `.chimera-memory/` and `.chimera/`

Avoid: toy projects with no tests, or repos where you cannot run any verification command.

---

## Initialize

```bash
cd your-project/
chimera-memory init
```

This creates `.chimera-memory/` (the local ledger) and adds it to `.gitignore`.

---

## Install hooks (Claude Code only)

```bash
chimera-memory hooks install
chimera-memory hooks status
```

This writes two hook scripts into `.claude/hooks/` and registers them in `.claude/settings.json`.

The hooks fire automatically when you use Claude Code — no manual claim locking required.

---

## Configure `.chimera/hooks.toml`

Create this file in your project root:

```toml
[claude_hooks]
auto_lock = true
scope_path = "."          # start with "." — covers your whole repo

falsifiers = [
  # The targeted check for the specific task you are about to do.
  # Replace with a real command that fails if your task broke something.
  ["python3", "-m", "pytest", "tests/test_my_area.py", "-q"]
]

must_not_break = [
  # Broader check that must stay green throughout.
  ["python3", "-m", "pytest", "-q"]
]
```

**scope_path guidance:**

Start with `scope_path = "."` so that any file changed during the task (tests,
docs, config) is included in scope. Use a narrower path only once you are
confident the task will not touch files outside it.

If your task edits both implementation and tests, your `scope_path` must cover both.

---

## Run one real task

Open Claude Code in your project. Submit a normal coding prompt.

Chimera will automatically:
1. Derive the intent from your prompt
2. Lock a claim before work begins
3. Settle the claim when Claude finishes a turn

You do not need to do anything manually.

---

## Generate PR evidence

After your task is committed on a branch:

```bash
# Committed changes (recommended for PR review):
chimera-memory xray generate --base main --head HEAD --output PR_EVIDENCE.md

# Uncommitted changes (working-tree mode):
chimera-memory xray generate --output PR_EVIDENCE.md
```

**Committed vs uncommitted:**
- `--base`/`--head` diffs two git refs and excludes untracked files. Use this for PR review.
- Without `--base`, Chimera reads the current working tree including unstaged changes.

---

## Understanding settlement statuses

| Status | Meaning |
|--------|---------|
| `VALIDATED` | All falsifiers and must-not-break checks passed; all changed files within scope |
| `SCOPE_DRIFT` | Checks passed, but some changed files were outside the declared `scope_path` |
| `CONTRADICTED` | At least one check failed |
| `UNSETTLED` | Settlement not yet run |

**SCOPE_DRIFT does not mean your tests failed.**

It means the configured checks passed, but some changed files were outside the
declared claim scope.

Common first-run causes:
- `.gitignore` changed because `chimera-memory init` added `.chimera-memory/`
- `.chimera/hooks.toml` was created alongside code
- tests or docs changed while `scope_path` was set to a narrow implementation directory

SCOPE_DRIFT is honest review signal. Fix it by widening `scope_path` or splitting the task into separate claims.

---

## Files not to commit

Do not commit Chimera evidence artifacts:

```
.chimera-memory/
PR_EVIDENCE.md
xray.json
claim.toml
```

`.chimera/hooks.toml` may be committed if it is useful shared project config.
`.gitignore` changes from `chimera-memory init` should be committed.

---

## Feedback

Send one of these back after your trial:

1. An organic `CONTRADICTED` settlement — a real check caught a real mistake during implementation
2. Repeated `SCOPE_DRIFT` that was materially annoying (not just first-run housekeeping)
3. `PR_EVIDENCE.md` that did not help your review
4. A hook that failed or did not fire when expected
5. Any confusing output or error message with the exact text

If the trial produced only clean `SCOPE_DRIFT` settlements and no real failures — that is also valid feedback: the tasks were low-risk and implementation was correct first try.
