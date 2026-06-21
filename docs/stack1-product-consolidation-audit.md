# STACK-1 — Product Stack Consolidation Audit

Consolidation/version-planning audit of the stacked product branch
(`L-003 → L-004 → L-005 → L-003B`). Not a release, not a merge into the frozen
`v0.26.5` RC. Factual record only.

## 1. Verdict

```
STACK1_CONSOLIDATION_PASS
```

The stack is linear on the RC, internally coherent, the three warning categories
render and gate together, default behavior stays advisory, docs are consistent,
and no affirmative overclaim (including "untested") reaches user-facing output.

## 2. Branch / head / lineage

- Audit branch/worktree: `oss/memory-stack1-consolidation` @ `/private/tmp/oss-memory-stack1`
- HEAD: `4f7738cf2` (= L-003B head)
- `git merge-base HEAD c8e6526bf` → `c8e6526bf` (the frozen RC is the base)
- `git rev-list --count c8e6526bf..HEAD` → **10** commits; **0** merges (linear)

```
4f7738cf2  docs(xray): document evidence coverage warnings        ┐ L-003B
c9252be6a  test(xray): cover targeted-evidence heuristics         │
950476f4c  feat(xray): add advisory evidence coverage warnings    ┘
b27445e6a  docs(action): document optional fail-on evidence gate  ┐ L-005
65b8d5909  test(xray): cover evidence gate behavior               │
caa5375f3  feat(xray): add opt-in evidence gate policy            ┘
0386f9efa  test(xray): cover test weakening heuristics            ┐ L-004
ea3e9656d  feat(xray): add advisory test integrity warnings       ┘
92a8fd533  test(xray): cover evidence quality warning heuristics  ┐ L-003
86ec1fc3a  feat(xray): add advisory evidence quality warnings     ┘
c8e6526bf  chore(release): chimera-memory 0.26.5 RC               ← frozen RC
```

Untouched worktrees confirmed: `oss-memory-launch` `c8e6526bf`, `oss-memory-l003`
`92a8fd533`, `oss-memory-l004` `0386f9efa`, `oss-memory-l005` `b27445e6a`,
`oss-memory-l003b` `4f7738cf2`.

## 3. Capability inventory (verified against code)

All 8 warning codes present in `xray.py` (verified by grep):

| Category | Codes |
|---|---|
| Evidence Quality (L-003) | `LINT_ONLY_EVIDENCE`, `ZERO_TESTS_COLLECTED`, `GREEN_ONLY_EVIDENCE` |
| Test Integrity (L-004) | `TEST_SKIP_ADDED`, `TEST_XFAIL_ADDED`, `ONLY_FOCUS_ADDED`, `TEST_FILE_DELETED` |
| Evidence Coverage (L-003B) | `NO_TARGETED_EVIDENCE_FOR_CHANGED_SOURCE` |

Additive result/counts keys: `evidence_quality_warnings`,
`test_integrity_warnings`, `evidence_coverage_warnings`.

Evidence gate (`EVIDENCE_GATE_POLICIES`, gate branches, and CLI `--fail-on`
choices all match — 10 policies): `never`, `review-required`, `warnings`,
`evidence-quality-warnings`, `test-integrity-warnings`,
`evidence-coverage-warnings`, `contradicted`, `unsettled`, `scope-drift`,
`evidence-dark`. `warnings` aggregates all three warning counts.

## 4. Combined-output scenario

Temp repo: source change (`pkg/app.py`) + bug-fix-intent claim settled with a
generic non-targeting falsifier (`python3 -c …`) + a test file that adds
`@pytest.mark.skip`. Result:

- `PR_EVIDENCE.md` rendered all three sections: `## Evidence Quality Warnings`,
  `## Test Integrity Warnings`, `## Evidence Coverage Warnings`.
- Honesty caveat `scores evidence quality, not code correctness` present.
- `--format pr-comment` showed compact counts: `Evidence quality warnings: 1`,
  `Test integrity warnings: 1`, `Evidence coverage warnings: 1`, plus the
  verdict and honesty line.
- `--json` counts: `{evidence_quality_warnings: 1, test_integrity_warnings: 1,
  evidence_coverage_warnings: 1}`.

## 5. Default `fail-on=never`

`xray generate --output PR_EVIDENCE.md --fail-on never` → **exit 0**; receipt
generated; stderr `Chimera Memory evidence gate disabled: fail-on=never.` No
policy failure. Default behavior remains advisory.

## 6. `fail-on=warnings`

`xray generate --output PR_EVIDENCE.md --fail-on warnings` (same scenario) →
**exit 2**; `PR_EVIDENCE.md` still present (receipt preserved). stderr:

```
Chimera Memory evidence gate failed: policy 'warnings' was not met.
This scores evidence quality, not code correctness.
See PR_EVIDENCE.md for details.
  - evidence quality warnings present (1)
  - test integrity warnings present (1)
  - evidence coverage warnings present (1)
```

## 7. Anti-overclaim scan

PASS. Generated `PR_EVIDENCE.md` + pr-comment contain no affirmative forbidden
claims and no "untested"/"not tested". Every `correct`/`approved` occurrence is a
negated honesty disclaimer (e.g. "scores evidence quality, not code
correctness", "does not prove the code is correct", "do not prove the code is
wrong or correct"). In shipping surfaces, "untested" appears only in a
planning-doc rule description and a source comment (both stating the product
*never* says it), never in user-facing output. All
`production-ready/certified/approved` doc hits are negated ("never claims …",
"Not production-ready — alpha software"). Scanned for: `code is correct`,
`code is safe`, `production-ready`, `approved`, `certified`, `guaranteed`,
`the agent lied`, `malicious`, `untested`.

## 8. Docs consistency

PASS. Warnings framed as "review prompts"; "evidence quality, not code
correctness" present across README/docs/action; default Action/gate behavior
documented as advisory (`fail-on: never`); `fail-on=warnings` explained
correctly; the execution-plan entries for L-003/L-004/L-005/L-003B each state
"Separate worktree; release RC `c8e6526bf` unchanged" (no stale "released"
claim); the v0.26.5 PyPI blocker is recorded separately.

One coherence note (not a contradiction to silently patch): both package
`pyproject.toml` files still read `0.26.5` on this stack while the stack adds
user-visible features — resolved by the version recommendation below.

## 9. Version recommendation (no bump performed)

Repo convention is semver on a `0.x` line: the `0.26.x` series are patch
releases (0.26.1–0.26.4 patches; 0.26.5 launch polish), and new minor lines
(`0.X.0`) historically introduce features.

The stack adds **new user-visible product capabilities** (three warning
categories + an opt-in CI evidence gate). That is a minor, feature-bearing
change, not a patch. **Recommendation: the stack should become `v0.27.0`**, not
`v0.26.6`. The stack currently inherits version `0.26.5` from the RC; before any
release it must be bumped (both packages, lockstep, dep bound
`chimera-memory-types>=0.27.0,<1.0`) to avoid a `0.26.5` collision with the
frozen launch-polish RC, and the Action examples updated from `@v0.26.5` to
`@v0.27.0`.

## 10. Release-path recommendation

- Keep `v0.26.5` as the frozen launch-polish RC (`c8e6526bf`). Its only blocker
  is the operator-side PyPI publish, which is independent of this product stack.
- Prepare the stack as a `v0.27.0` candidate in a later, explicitly authorized
  ticket (version bump + release note + doc/tag reference updates).
- The real bottleneck is PyPI credentials, not the product work. **Fix the PyPI
  publish first.** Then choose:
  - **A (two releases):** publish `v0.26.5` from the RC, then `v0.27.0` from the
    stack. Cleanest if `v0.26.5` was referenced externally.
  - **B (single release):** since the stack is built on top of the RC and
    contains all of v0.26.5's content, bump the stack to `v0.27.0` and publish
    that alone. Simpler; delivers everything in one release.
- Risks of skipping `v0.26.5` (path B): any external reference to a `v0.26.5`
  tag/package would be unmet, and `@v0.26.5` Action examples must move to
  `@v0.27.0`. No functional loss (0.27.0 supersets 0.26.5).
- Do not hold the product stack hostage to the v0.26.5 publish: resolving PyPI
  credentials unblocks either path.

## 11. Verification commands and results

| Command | Result |
|---|---|
| `git rev-list --count c8e6526bf..HEAD` | 10 (0 merges; linear) |
| `pytest tests/test_xray*.py test_github_action.py test_public_docs.py` | 211 passed |
| `pytest packages/chimera-memory` | **1164 passed, 0 failed** |
| `ruff check src tests` | All checks passed |
| `mypy src` | no issues, 31 source files |
| `python -m chimera_memory --version` | `chimera-memory 0.26.5` |
| `chimera-memory demo` | pass |
| `uv build packages/chimera-memory{,-types}` | both build `0.26.5` wheels+sdists |
| Combined scenario `--fail-on warnings` | exit 2, receipt preserved, 3 reasons |
| Combined scenario `--fail-on never` | exit 0, gate disabled |

No code changes were required; no version bump, push, tag, or publish performed.
The frozen RC `c8e6526bf` and the four product worktrees are untouched.
