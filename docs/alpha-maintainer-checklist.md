# Chimera Memory — Alpha Maintainer Checklist

Use this checklist to evaluate whether an external alpha trial counts as a valid evidence run.

---

## Per-trial checklist

### Setup

- [ ] Did install work? (`pip install chimera-memory==0.26.4`)
- [ ] Python 3.12+ used?
- [ ] Was it a real git repo (not a toy/demo)?
- [ ] Was `chimera-memory init` run successfully?
- [ ] Was `.chimera/hooks.toml` configured with real commands?
- [ ] Did `chimera-memory hooks install` succeed?

### Baseline

- [ ] Was the falsifier run before editing?
- [ ] Was `must_not_break` run before editing?
- [ ] Did both pass before the task started?
- [ ] If they failed, was the failure classified as baseline noise (not organic_real)?

### Core loop

- [ ] Was a claim locked **before** any edits? (via hooks auto-lock or `claim lock --auto`)
- [ ] Was there a real coding task (not a fake failure, not pure docs typo)?
- [ ] Was the claim settled after the work?
- [ ] Was the settlement result recorded? (VALIDATED / CONTRADICTED / SCOPE_DRIFT)

### PR_EVIDENCE

- [ ] Was `PR_EVIDENCE.md` generated?
- [ ] Does it include settled claim evidence linked to changed files?
- [ ] If wrap-only was used: does it show the "Wrap-Based Evidence" section?
- [ ] Was Reviewer Focus useful?

### Evidence quality

- [ ] Was the falsifier command credible (not `true` or a no-op)?
- [ ] Was the task genuinely uncertain (not known-good)?
- [ ] Is the settlement honest? (SCOPE_DRIFT is acceptable; baseline noise classified correctly?)

### Failure classification (if any failure occurred)

Use:
- `organic_real` — genuine code/task failure during real implementation
- `controlled_real` — intentional negative-path
- `test_first_contract` — expected red/green test-first failure
- `invocation_artifact` — wrong command, wrong runtime, missing dep, bad test path, stale baseline
- `documentation_gap` — unclear docs, product behavior fine
- `external_blocker` — PyPI lag, auth, network, OS issue

### M2B

- [ ] Did a genuine `organic_real` CONTRADICTED settlement occur?
- [ ] If yes: was the repair loop captured? Did the repaired work settle?
- [ ] M2B advancement: **No** / **Provisional** (organic failure, terminal-only) / **Clean** (organic failure + repair + ledger-settled)

### F15 monitoring

- [ ] Was the main proof command placed in `falsifiers` (not only `must_not_break`)?
- [ ] Did `must_not_break` catch a real failure that `falsifiers` did not?
- [ ] If yes: F15 repeats — log as v0.27 candidate signal

---

## Decision outcomes

| Outcome | Criteria |
|---------|----------|
| **PASS** | Claim locked before edits; settled; PR_EVIDENCE includes diff-linked claim; no P1 friction |
| **PARTIAL** | Useful feedback but missing claim lock, no settlement, or wrap-only with no diff-linked claim |
| **FAIL** | Install/setup/init blocked; no usable evidence produced |
| **PATCH CANDIDATE** | Repeated P1 friction across ≥2 independent trials; docs/copy/CLI only |
| **v0.27 CANDIDATE** | Repeated runtime/API issue not solvable by docs; F15 repeats ≥2 independent trials |

---

## Current baseline (v0.26.4)

Known resolved friction:
- F4: Python 3.12 install trap — fixed in v0.26.2
- F5: X-Ray mode confusion — fixed in v0.26.2
- F6: scope_path first-user — fixed in v0.26.2
- F7: SCOPE_DRIFT misread — fixed in v0.26.2
- F8: stale hook next-step — fixed in v0.26.2
- F10: docs URL — fixed in v0.26.3
- F11: missing .git guidance — fixed in v0.26.3
- F12: no starter hooks.toml — fixed in v0.26.3
- F13: session lifecycle — fixed in v0.26.3
- F14: baseline-check guidance — fixed in v0.26.3
- F15: build not in falsifiers — guidance added in v0.26.3; did not repeat in v0.26.4
- gbrain wrap gap: wrap evidence invisible in PR_EVIDENCE — fixed in v0.26.4

Open issues:
- None at P1 as of v0.26.4
- F15 (must_not_break-only organic failure not captured as CONTRADICTED) remains a v0.27 candidate if it repeats across ≥2 independent trials

M2B gate: BLOCKED — `organic_real_failed = 0` across all trials
