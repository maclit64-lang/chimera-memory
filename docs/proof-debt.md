# Proof Debt

`chimera-memory proof-debt` lists the local claims and receipts that still need
stronger evidence. It is **advisory and local-only**, computed from your existing
ledger and the current Merge X-Ray — it adds no new analysis.

> Proof Debt lists local claims and receipts that still need stronger evidence.
> It does not prove code is correct or incorrect.

## Usage

```bash
chimera-memory proof-debt
```

Machine-readable output:

```bash
chimera-memory proof-debt --json
```

## What it reports

Debt is summarized from already-recorded signals only:

| Category | Meaning |
|---|---|
| `CONTRADICTED_CLAIM` | A claim whose latest settlement contradicted it. |
| `UNSETTLED_CLAIM` | A claim with no settled falsifier outcome. |
| `REVIEW_REQUIRED_RECEIPT` | The current receipt verdict is `REVIEW REQUIRED`. |
| `LOCAL_RELAPSE_WARNING` | A current claim resembles a previously contradicted local claim (overlapping scope + matching intent or command fingerprint). |
| `TEST_INTEGRITY_WARNING` | The diff may have weakened tests (skip/xfail/focus-only/deleted). |
| `EVIDENCE_COVERAGE_WARNING` | Changed source has no obviously targeted evidence. |
| `EVIDENCE_QUALITY_WARNING` | Evidence is lint-only, zero-test, or green-only. |
| `EVIDENCE_DARK_SOURCE` | Changed source files carry no settled claim coverage. |
| `SCOPE_DRIFT` | Settled changes fell outside the declared scope. |

Items are ordered deterministically by severity (contradicted → unsettled →
review-required → local-relapse → test-integrity → evidence-coverage →
evidence-quality → evidence-dark → scope-drift), then by reference.

## Honesty

Every item is a **review prompt**, not a verdict on the code. Proof Debt never
says a claim is false, the code is wrong, or the change is unsafe — it reports
where evidence is missing, weak, unsettled, contradicted, or drifted, and what
to add next. It scores evidence quality, not code correctness.

When there is nothing to report:

```text
No proof debt found in the current ledger.

This does not prove code is correct. It means no known evidence-debt signals were found.
```
