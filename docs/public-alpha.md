# Chimera Memory — Public Alpha Guide

Chimera Memory is a local-first CLI that records what an AI coding agent claimed before changing code, runs your real checks, settles the outcome, and generates `PR_EVIDENCE.md` for review.

This is an **alpha release**. Use it on real projects with realistic expectations.

---

## What it is

- A local CLI tool (`pip install chimera-memory`)
- Records a pre-edit claim (intent + falsifier command) before AI coding begins
- Runs your real test/build/typecheck commands after the work
- Settles the claim as `VALIDATED` or `CONTRADICTED`
- Generates `PR_EVIDENCE.md` showing which changed files have settled claim coverage

It works best with Claude Code hooks, but also supports manual `wrap` and `session` flows.

---

## What it is not

- Not a hosted dashboard
- Not a model scorer, ranker, or router
- Not a CI replacement
- Not a GitHub App
- Not a proof that code is correct
- Not enterprise compliance
- Not production-ready — this is alpha software

---

## Who should try it

Good fit:

- Developers who use Claude Code, Cursor, or similar AI coding tools
- Teams who want a light evidence trail for AI-written code changes
- Anyone running Python >=3.12 with a real git repo and real tests/checks

Not a good fit yet:

- Repos with no runnable test or build command
- Non-git directories
- Windows (not officially supported in alpha)

---

## Install

Requires Python 3.12 or later. macOS system `python3` is often 3.9 — use `python3.12` or `uv`:

```bash
# With Python 3.12:
python3.12 -m venv .venv && source .venv/bin/activate
pip install chimera-memory==0.26.4

# Or with uv:
uv venv --python 3.12 .venv && source .venv/bin/activate
pip install chimera-memory==0.26.4

# Verify:
chimera-memory --version
```

---

## Quickstart

```bash
chimera-memory demo
```

This runs a safe local demo — no project mutation, no network — showing the full evidence flow.

---

## Initialize in a real repo

Your project must be a git repository:

```bash
cd your-project/
git init          # skip if .git already exists
chimera-memory init
```

Then install Claude Code hooks:

```bash
chimera-memory hooks init      # creates starter .chimera/hooks.toml
chimera-memory hooks install   # installs into .claude/
chimera-memory hooks status    # confirm
```

---

## Configure `.chimera/hooks.toml`

`chimera-memory hooks init` creates a starter template. Edit it for your project.

TypeScript / Node example:

```toml
[claude_hooks]
auto_lock = true
scope_path = "."

falsifiers = [
  ["pnpm", "run", "build"]
]

must_not_break = [
  ["pnpm", "run", "build"]
]
```

Python / uv example:

```toml
[claude_hooks]
auto_lock = true
scope_path = "."

falsifiers = [
  ["uv", "run", "pytest", "tests/test_specific_area.py", "-q"]
]

must_not_break = [
  ["uv", "run", "pytest", "-q"]
]
```

**`falsifiers`** — the targeted command that proves your task worked. If build or typecheck is your main proof, put it here.

**`must_not_break`** — broader checks that must stay green throughout.

**`scope_path`** — start with `"."` so all changed files are in scope.

---

## Run baseline checks before editing

Before your task, run your falsifier and `must_not_break` commands once:

```bash
# Python example:
uv run pytest tests/test_specific_area.py -q

# TypeScript example:
pnpm run build
```

If they already fail before you start — that is baseline noise. Choose a narrower command that passes, or fix the baseline first. A pre-existing failure is not organic task evidence.

---

## Run a claim-locked coding task

With hooks installed and `.chimera/hooks.toml` configured:

1. Open Claude Code in your project
2. Submit a real coding prompt
3. Chimera auto-locks a claim before edits begin
4. Claude edits your code
5. The Stop hook settles the claim and generates `PR_EVIDENCE.md`

If the Stop hook does not settle automatically:

```bash
chimera-memory claim settle <claim_id>
```

---

## Generate PR_EVIDENCE.md

After committing your change:

```bash
# Commit-range mode (recommended — cleaner, excludes cache/untracked files):
chimera-memory xray generate --base main --head HEAD --output PR_EVIDENCE.md

# Working-tree mode (if changes are uncommitted):
chimera-memory xray generate --output PR_EVIDENCE.md
```

Commit-range mode is cleaner for PR review. Working-tree mode is useful during active development but may include cache or build artefacts as noise.

---

## How to read PR_EVIDENCE.md

**Verdict** — top-level summary: whether all changed files are covered by settled claims.

**Settled Claims** — each claim that was locked before editing, with its falsifier, scope, and which files it covers.

**Evidence-Dark Changes** — files that changed but have no settled claim coverage. Review these manually.

**Scope Drift** — files that changed outside the declared `scope_path`. Review manually.

**Reviewer Focus** — a prioritized list of what needs attention.

**Non-Claims** — disclaimer that this shows settled evidence, not proof of correctness.

---

## Wrap-based evidence vs diff-linked claim evidence

`chimera-memory wrap -- <command>` runs a command and records its outcome in the ledger. This is real settled evidence.

However, wrap-based evidence is **not automatically linked to changed files** in PR_EVIDENCE. When only wrap evidence exists, PR_EVIDENCE shows a "Wrap-Based Evidence (Not Linked to Diff)" section explaining what exists and how to get diff-linked evidence:

```
## Wrap-Based Evidence (Not Linked to Diff)

1 settled outcome(s) found in the wrap ledger.
These outcomes are real settled evidence, but cannot be mapped to changed files.

To get PR_EVIDENCE with linked claim coverage, use `claim lock` + `claim settle`...
```

For diff-linked review evidence: use Claude Code hooks (prompt-submit auto-lock + Stop hook settlement), then run X-Ray in commit-range mode.

---

## Known limitations

- **Alpha-quality** — expect rough edges
- Works best in git repos with real tests or build commands
- Claude hooks are project-local (not system-wide)
- No hosted dashboard, no cloud sync, no GitHub App
- No model scoring, routing, or ranking
- Not a CI replacement
- A passing falsifier does not prove code is correct — it proves the specified check passed
- Working-tree mode can be noisier than commit-range mode
- Wrap evidence is real but not automatically linked to changed files in PR_EVIDENCE
- M2B readiness is an internal development metric, not a public-facing feature

---

## What feedback to send

After your trial, send:

1. **Repo ecosystem** (Python/TypeScript/other)
2. **Task description** (what you asked Claude to do)
3. **Your `.chimera/hooks.toml`**
4. **Baseline check output** (before task)
5. **Claim ID** (from `chimera-memory claim list`)
6. **Settlement result** (VALIDATED / CONTRADICTED / SCOPE_DRIFT)
7. **`PR_EVIDENCE.md`** or a text paste of it
8. **Confusing parts** — exact output text if possible
9. **Whether Reviewer Focus was useful**
10. **Whether you'd use it again**

Send to: [feedback channel — to be specified by maintainer]
