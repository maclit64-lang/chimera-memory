# Chimera Memory — Short Post Draft

---

Chimera Memory is in public alpha.

It is a local-first CLI for AI-assisted coding workflows.

When you ask an AI agent to change your code, Chimera records the claim before the edit, runs your real checks after, and settles the outcome as VALIDATED or CONTRADICTED.

The result is `PR_EVIDENCE.md` — a report that tells reviewers which changed files have settled evidence and which need manual inspection.

It is not a safety product. It does not score models or run in the cloud. It is a focused, local evidence trail for one workflow: AI agent edits your code, you review the diff.

Try it on one real coding task:

```bash
pip install chimera-memory==0.26.4
chimera-memory demo
```

Full guide: https://github.com/maclit64-lang/chimera-memory/blob/main/docs/public-alpha.md

Works with Claude Code hooks. Requires Python 3.12+, a git repo, and a real test/build command. Alpha-quality — feedback welcome.
