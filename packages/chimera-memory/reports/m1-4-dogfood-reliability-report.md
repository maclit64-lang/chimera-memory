# Chimera Memory M1-4 Dogfood Reliability Report

## Repo/path

`/Users/agbodaniel/Code/chimera`

## Branch/base HEAD

- Branch: `feat/sealed-claim-wave-ab-c1`
- Base HEAD: `0d448bbc43c2450a6a8b9da21e7567b912ffeab0`
- Base subject: `feat: add advisory drift and report cli`

## Data provenance

REPLAYED TEST OUTCOMES — not original CI history

Original per-commit CI/test outcome history was not available as local result artifacts in this checkout. Local discovery found `.github/workflows` and pytest cache, but no per-commit CI/job output that could be treated as original CI truth.

I therefore used an honest local replay:

- Created a temporary detached local git worktree at `/tmp/chimera-memory-m1-4-replay`.
- Did not check out old commits in the current working tree.
- Did not fetch, pull, push, clone from network, or contact remotes.
- Replayed the package test suite present at each M0/M1 commit.
- Command shape: `PYTHONPATH=<temp worktree package srcs> /Users/agbodaniel/Code/chimera/.venv/bin/python -m pytest packages/chimera-memory/tests -q`.

## Included commits/slices

| Slice | Commit | Subject | Replay result |
|---|---:|---|---|
| M0-1 skeleton | `da7015d8e9` | `feat: add chimera memory skeleton` | pass — `3 passed in 0.01s` |
| M0-2 record/seal | `ef7d7e5174` | `feat: record and seal chimera memory claims` | pass — `7 passed in 0.09s` |
| M0-3 settle/score | `f6c813dc1d` | `feat: settle and score chimera memory claims` | pass — `14 passed in 0.12s` |
| M0-4 query/report storage | `9899f0018c` | `feat: query and report chimera memory ledger` | pass — `19 passed in 0.16s` |
| M1-1 pytest wrapper | `95e7e0ef1b62` | `feat: wrap pytest with chimera memory ledger` | pass — `28 passed in 1.27s` |
| M1-2 git evidence | `b4fea5957b62` | `feat: capture git evidence for chimera memory claims` | pass — `33 passed in 1.87s` |
| M1-3 advisory drift/report CLI | `0d448bbc43c2` | `feat: add advisory drift and report cli` | pass — `42 passed in 2.04s` |

## Reliability summary

Overall replayed reliability:

- Commits replayed: 7
- Passed: 7
- Failed: 0
- Replayed pass rate: 100%

### By agent

| Agent | Commits | Passed | Failed | Pass rate | Metadata quality |
|---|---:|---:|---:|---:|---|
| Agent 4 implementer, as reported in the handoff transcript | 7 | 7 | 0 | 100% | External transcript label only; not machine-readable commit metadata |

### By model

| Model version | Commits | Passed | Failed | Pass rate | Metadata quality |
|---|---:|---:|---:|---:|---|
| `UNKNOWN_NOT_RECORDED_IN_COMMITS` | 7 | 7 | 0 | 100% | Insufficient model metadata for model comparison |

### By task_type

| task_type | Commits | Passed | Failed | Pass rate |
|---|---:|---:|---:|---:|
| skeleton | 1 | 1 | 0 | 100% |
| record/seal | 1 | 1 | 0 | 100% |
| settle/score | 1 | 1 | 0 | 100% |
| query/report | 1 | 1 | 0 | 100% |
| pytest wrapper | 1 | 1 | 0 | 100% |
| git evidence | 1 | 1 | 0 | 100% |
| drift/report CLI | 1 | 1 | 0 | 100% |

## INSUFFICIENT_DATA

The dogfood report is useful as a smoke/history replay, but it is not a sufficient reliability dataset.

Reason:

- Only 7 commits were replayed.
- Chimera Memory drift defaults to `min_claims=30`.
- Each task_type has only one commit.
- Model version was not recorded as machine-readable metadata in the commits.
- The agent label comes from the handoff transcript, not from persisted claim metadata.

Therefore this dataset is `INSUFFICIENT_DATA` for meaningful drift or degradation claims by agent/model/task_type.

## Limitations

- These are replayed local outcomes, not original CI outcomes.
- The replay proves the M0/M1 commit chain is internally test-clean under local package tests, not that every original development moment was green before Agent 3 review.
- There is no machine-readable per-commit `agent_id`, `model_version`, or `task_type` metadata in git itself.
- Seven commits are too sparse for a credible comparison across agents or models.
- The current implementation can produce the ledger/report mechanics, but it has not yet accumulated enough real settled claims to prove the product wedge.

## Decision gate

Question: Did the reliability-by-task-type report reveal something true and useful about our own agents?

Answer: No — not enough to justify M2 yet.

It revealed two true things:

1. The Chimera Memory M0/M1 chain replays cleanly across every reviewed slice.
2. The current dogfood history lacks enough structured agent/model/task_type metadata to make a genuinely useful reliability-by-task-type judgment.

The important product signal is negative but valuable: before expanding to M2, Chimera Memory needs more real `wrap pytest` usage on active agent work, with explicit `agent_id`, `model_version`, and `task_type` metadata captured at claim time.

## Recommendation

Reassess the wedge before M2 product expansion.

Next disciplined move is not hosted/product expansion. It is to keep using `chimera-memory wrap pytest` on real Agent 4/Agent 3 work until there are at least 30 settled claims with explicit agent/model/task_type metadata, then rerun this decision gate.

## Hard stop

Stopped before M2: yes
