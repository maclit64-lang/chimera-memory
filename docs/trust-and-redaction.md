# Trust and redaction

Chimera Memory is **local-first**. It generates receipts from your local git diff
and locally recorded command evidence. This page describes what it stores, what
goes into a receipt, and what it does and does not do with sensitive data.

It scores **evidence quality, not code correctness**. Nothing here proves the
code is correct or incorrect.

## 1. What Chimera Memory stores locally

A per-repository ledger under `.chimera-memory/` (which `chimera-memory init`
adds to `.gitignore`). It holds claims, settlements, sessions, and bounded
**witness excerpts** of the commands you wrap or settle — command arguments and
short stdout/stderr excerpts. There is no separate database and no remote store.

## 2. What goes into `PR_EVIDENCE.md`

The Merge X-Ray receipt (`chimera-memory xray generate`, Markdown or `--json`)
contains: the verdict and verdict label, settled claims (intent, declared scope,
the pre-committed command text), evidence-dark and scope-drift file lists, a
reviewer-focus list, the advisory warning sections (Evidence Quality, Test
Integrity, Evidence Coverage), counts, and the "what this does not prove"
caveat. The receipt does **not** print raw stdout/stderr; it only inspects stored
excerpts internally (e.g. to detect that a test command collected zero tests).

## 3. Is code sent to a cloud service?

No. Chimera Memory runs locally, requires no account or sign-in, and performs no
network calls to operate. The `chimera-memory demo` runs entirely in a temp
directory with no network.

## 4. Are secrets/tokens intentionally stored?

No — Chimera Memory does not intend to store secrets, and it applies **redaction
at capture time** to command arguments and witness excerpts before they are
written to the ledger. Redaction is **best-effort pattern matching**, not a
guarantee, and covers common shapes:

- private key blocks (`-----BEGIN … PRIVATE KEY-----`),
- `Authorization: Bearer …` headers,
- GitHub tokens (`ghp_…`, `github_pat_…`), OpenAI/Anthropic `sk-…` keys,
- AWS access key IDs (`AKIA…`) and secret-looking values, Slack `xox…` tokens,
- database URL passwords (`postgres://user:pass@…`),
- `password=` / `api_key=` / `token=` / `secret=` assignments,
- long hex strings that look like secrets.

A built-in scanner can flag possible unredacted secret patterns, and some flows
add a "review and redact token-like content before sharing" prompt. Because the
matching is pattern-based, **unusual secret formats may not be caught.**

## 5. What command output may be captured?

Bounded, redacted **excerpts** of stdout/stderr from the commands you run via
`chimera-memory wrap` / `claim settle` (and the checks the GitHub Action runs).
Output is truncated to an excerpt size and ANSI-stripped before redaction.

## 6. What you should avoid putting into commands

Avoid passing raw secrets as literal command arguments or printing them to stdout
in uncommon formats — prefer environment variables or secret managers. If a secret
reaches a witness excerpt in a shape the patterns above do not match, it could be
stored unredacted in your local ledger.

## 7. What the tool does not prove

It does not prove the code is correct, secure, or complete, and it does not
certify, approve, or guarantee anything. Warnings (evidence quality, test
integrity, evidence coverage) are **review prompts**, not verdicts on the code.

## 8. Reviewing receipts before sharing

Before publishing `PR_EVIDENCE.md` (or the JSON) outside your team, review it.
Chimera Memory avoids intentionally storing secrets and redacts common patterns,
but you should confirm a receipt contains nothing sensitive before sharing it
publicly. Treat the local `.chimera-memory/` ledger as private and keep it out of
version control.
