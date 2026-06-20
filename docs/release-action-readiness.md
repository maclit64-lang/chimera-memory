# Release & Action Consumability Readiness

Closeout reference for the question: **can an outside repository consume the
Chimera Memory Action and package exactly as documented?**

Short answer at time of writing: the prior **package** release (0.26.4) is on
PyPI today; **this release candidate is 0.26.5** (not yet published), and the
**reusable Action** is not consumable at `@v0.26.5` yet because that tag has not
been pushed — no published Git ref yet contains `action.yml`. This file lists
what must happen to close that gap and how to smoke-test it. Nothing here has
been executed — it is a plan.

## Verified current state

| Item | State | Evidence |
|---|---|---|
| Launch branch | `oss/memory-launch`, clean | `git status` empty |
| HEAD | release-candidate top of `oss/memory-launch`, **untagged** | `git log --decorate` |
| `action.yml` first added in | `529c44483` (untagged) | `git log --diff-filter=A -- action.yml` |
| Tag `v0.26.4` points to | `3099ffc11` (parent of base `04a9b4fa5`) | `git rev-list -n1 v0.26.4` |
| `action.yml` in any tag | **No** | tag scan over `git tag --list` |
| `oss/memory-launch` on a remote | **No** (local only) | `git branch -r --contains 529c44483` empty |
| Prior release 0.26.4 on PyPI | **Yes** (`chimera-memory` + `-types`) | pypi.org |
| This RC version | **0.26.5** (both packages), not yet on PyPI | `pyproject.toml` + `uv.lock` |

Publish target for the Action: remote `chimera-memory-upstream` →
`https://github.com/maclit64-lang/chimera-memory.git` (the repo named in
`uses: maclit64-lang/chimera-memory@...`).

## The one gap

The docs now reference `uses: maclit64-lang/chimera-memory@v0.26.5` (README
Action section + `docs/examples/github-actions/pr-evidence.yml`). That tag does
not exist yet, so until it is pushed an external workflow pinning it fails with
"Can't find 'action.yml'". The PyPI install step the Action runs works once
0.26.5 is published — so this is a Git-ref/tag + publish gap, not a code gap.

The docs are annotated to say so and offer a pre-release pin
(`@oss/memory-launch`) until the `v0.26.5` tag is pushed.

## Tag decision (made)

**Decision: cut a new patch release `v0.26.5` at the launch commit; do NOT
force-move `v0.26.4`.** `v0.26.4` already exists at `3099ffc11` and maps to the
shipped PyPI build; rewriting it would break users who rely on that tag/package.
A fresh `v0.26.5` tag is the first ref to include `action.yml`, and the docs now
point at `@v0.26.5`. Both packages are bumped 0.26.4 → 0.26.5 in lockstep
(`chimera-memory-types` is a no-functional-change version-sync that keeps the
`chimera-memory-types>=0.26.5,<1.0` dependency satisfiable).

## Action-consumability checklist (release closeout)

1. [ ] Push `oss/memory-launch` to `chimera-memory-upstream`
       (`git push chimera-memory-upstream oss/memory-launch`).
2. [ ] Confirm CI is green on the pushed branch (the repo's `chimera-memory-ci`
       workflow runs pytest + mypy + ruff).
3. [ ] Publish `chimera-memory==0.26.5` and `chimera-memory-types==0.26.5` to
       PyPI (0.26.4 is already public; 0.26.5 is this release).
4. [ ] Create and push the `v0.26.5` tag at the launch commit (the first ref
       that includes `action.yml`).
5. [ ] On GitHub, confirm the repo renders the Action (the "marketplace"/Action
       metadata loads from `action.yml` at that ref).
6. [ ] In a separate test repo, exercise the Action (see smoke protocol):
       - [ ] normal PR
       - [ ] fork PR
       - [ ] re-push to the same PR (sticky comment updates, not duplicates)
7. [ ] Verify the artifact fallback (`chimera-pr-evidence`) uploads on every run,
       including when the comment is skipped.
8. [ ] Verify the PR-facing output carries the honesty line
       ("This scores evidence quality, not code correctness.").
9. [ ] Verify no correctness/safety/approval overclaim appears anywhere in the
       PR comment, step summary, or `PR_EVIDENCE.md`.
10. [ ] Post-publish: clean-install from PyPI into a fresh venv and run
        `chimera-memory xray generate --format pr-comment` to confirm parity.
11. [ ] Update the two doc references (README + example workflow) to the FINAL
        ref chosen in step 4, and remove the pre-release "availability" caveat
        once the ref resolves.

## Manual GitHub PR smoke protocol

A real GitHub-runner smoke cannot be executed locally; run this after the Action
ref is pushed.

1. Create a tiny public test repo with one source file.
2. Add `.github/workflows/chimera-pr-evidence.yml` (copy from
   `docs/examples/github-actions/pr-evidence.yml`); set `uses:` to the pushed
   Action ref.
3. Open a PR that changes a few lines.
4. Confirm the `evidence` job runs to completion.
5. Confirm the `chimera-pr-evidence` artifact contains `PR_EVIDENCE.md`.
6. Confirm a sticky PR comment titled "Chimera Memory Evidence Receipt" appears.
7. Push another commit to the same PR branch.
8. Confirm the existing comment is **updated in place** (marker
   `<!-- chimera-memory-pr-evidence -->`), not duplicated.
9. From a fork of the test repo, open a PR (restricted token path).
10. Confirm no hard token failure: the comment step is skipped/warns, while the
    step summary and artifact are still produced.
11. Confirm the job conclusion is success (advisory only; `fail-on: never`).
12. Confirm the comment/summary wording includes:
    "This scores evidence quality, not code correctness."

## Honesty invariants (must stay true through release)

- Scores evidence quality, not code correctness.
- Never claims code is correct, safe, production-ready, certified, or approved
  to merge; never claims an agent lied.
- Fork PRs degrade gracefully; a missing comment token never fails the job.
