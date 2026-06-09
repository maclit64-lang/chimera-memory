# Chimera Memory — Public Alpha Announcement Draft

---

**Chimera Memory** is now available for a limited public alpha.

It is a local-first CLI for developers using AI coding agents.

---

## What it does

When you use an AI coding tool like Claude Code, a lot happens before you review the diff:

- The agent interpreted your prompt
- It made changes to your files
- Your checks may or may not have run
- The review happens after the fact

Chimera Memory adds a lightweight evidence layer to that workflow:

1. Before editing, it locks a claim: what the agent intends to do and which check will verify it
2. After the work, it runs the check and settles the outcome as VALIDATED or CONTRADICTED
3. It generates `PR_EVIDENCE.md` — a structured report showing which changed files have settled claim coverage and which need manual review

The output is not proof of correctness. It is an honest trail of what was claimed, checked, and settled.

---

## Why it might be useful

Code review for AI-written changes is harder than reviewing human changes because:

- The agent's reasoning is not in the diff
- Checks may have been run but not surfaced in the PR
- "It passed CI" doesn't tell you what the agent claimed or what specifically was verified

PR_EVIDENCE.md gives reviewers a focused starting point:

- What did the agent claim before editing?
- What command verified it?
- Which changed files have settled evidence?
- Which files need extra scrutiny?

---

## What it is not

This is not an AI safety product. It does not prevent bad changes. It does not rank or score models. It does not replace your test suite or CI. It does not have a hosted dashboard.

It is a local-first, open-source CLI for developers who want more transparency in AI-assisted code review.

---

## Get started

Requires Python 3.12+, a git repo, and at least one real runnable check command.

```bash
pip install chimera-memory==0.26.4
chimera-memory demo
```

Full setup guide: https://github.com/maclit64-lang/chimera-memory/blob/main/docs/public-alpha.md

---

## What to try

Pick one small real task — a bug fix, a refactor, a missing test — and run it through Claude Code with Chimera hooks installed. Then look at the resulting `PR_EVIDENCE.md`.

If it helped you know what to review, or if it surfaced something confusing, that feedback is exactly what we want.

---

## Send feedback

After your trial:

- Your ecosystem and task description
- Your `.chimera/hooks.toml`
- Claim ID and settlement result
- `PR_EVIDENCE.md` or a paste of it
- The single most confusing part

Full feedback guide: https://github.com/maclit64-lang/chimera-memory/blob/main/docs/public-alpha.md#what-feedback-to-send

---

Source: https://github.com/maclit64-lang/chimera-memory
PyPI: https://pypi.org/project/chimera-memory/
