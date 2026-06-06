# chimera-memory CI-Native Guide (v0.2.0)

Local-first reliability ledger for CI pipelines. No cloud, no account, no secrets required.

---

## Quick start

```yaml
- name: Install chimera-memory
  run: pip install chimera-memory
```

See the full example: [`docs/examples/github-actions/chimera-memory-ci.yml`](../examples/github-actions/chimera-memory-ci.yml)

---

## Exit-code contract

`chimera-memory wrap` exits with the **same exit code as the wrapped command**.

```bash
# Exits 1 if pytest fails — CI step fails normally
chimera-memory wrap --failure-origin organic_real -- pytest tests/

# Exits 0 if ruff passes
chimera-memory wrap --failure-origin organic_real -- ruff check src/
```

A `CONTRADICTED` claim does **not** suppress the exit code. The underlying command failure is what fails the CI step.

Receipt generation runs with `if: always()` so you have evidence regardless of whether checks passed or failed.

**Pattern for collecting receipts even on failure:**

```yaml
- name: Wrap pytest
  run: chimera-memory wrap -- pytest tests/        # exits nonzero on failure

- name: End session
  if: always()                                      # always runs
  run: |
    chimera-memory session end --status PASSED || \
    chimera-memory session end --status FAILED || true

- name: Generate receipt bundle
  if: always()                                      # always runs
  run: chimera-memory receipt bundle --output-dir ci-bundle --include-preflight

- name: Upload
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: chimera-memory-bundle-${{ github.run_id }}
    path: ci-bundle/
```

---

## CI artifact bundle

The `receipt bundle` command produces these files in `--output-dir`:

| File | Format | Human-readable | Machine-readable | Safe to upload |
|---|---|---|---|---|
| `receipt.md` | Markdown | ✅ | — | ✅ |
| `receipt.json` | JSON | — | ✅ | ✅ |
| `github-summary.md` | Markdown | ✅ | — | ✅ |
| `preflight.md` | Markdown | ✅ | — | ✅ |
| `preflight.json` | JSON | — | ✅ | ✅ |
| `status.json` | JSON | — | ✅ | ✅ |
| `reliability.json` | JSON | — | ✅ | ✅ |
| `failures.json` | JSON | — | ✅ | ✅ |
| `verify.json` | JSON | — | ✅ | ✅ |

**Evidence bundle** (from `evidence bundle --output-dir`):

| File | Notes |
|---|---|
| `events.jsonl` | Portable claim events — safe to upload |
| `errata.jsonl` | DQ corrections — safe to upload |
| `manifest.json` | Bundle metadata |
| `README.md` | Human-readable bundle summary |

**Local-only files** (never upload):

| Path | Why |
|---|---|
| `.chimera-memory/claims.jsonl` | Raw ledger — may contain unredacted command fragments |
| `.chimera-memory/sessions.jsonl` | Session records |
| `.chimera-memory/integrity.jsonl` | Chain integrity — local only |
| `.chimera-memory/append_state.json` | Internal state |

### What is redacted

`chimera-memory wrap` applies built-in redaction to `stdout_excerpt` and `stderr_excerpt` before recording:

- Tokens matching `[A-Za-z0-9_-]{20,}` common secret patterns
- Bearer headers
- PyPI/GitHub token formats

**Do not pass API keys or passwords as literal command arguments.** The command string itself is recorded and redaction covers only common patterns.

### What is not guaranteed

- Redaction is best-effort, not exhaustive.
- `preflight --from-git` returns `source: none` on a clean tree (see below).
- JSON schema fields may be added in patch releases; do not assert exact key sets.

---

## `preflight --from-git` and `source: none`

When the working tree is clean (no modified files), `preflight --from-git` returns:

```json
{"source": "none", "m2b_readiness_level": "blocked", "scope_paths": []}
```

This is **expected behavior**, not an error. It means there is no git diff to infer scope from.

**In CI** this is normal when the workflow runs after a merge or on a tag. The preflight step uses `continue-on-error: true` because it is advisory only.

To get an explicit scope in CI, use `--scope-path`:

```bash
chimera-memory preflight --scope-path src/ --json
```

---

## Stable JSON contracts (v0.2.0)

These outputs are stable enough for scripting in v0.2.0 examples. They are not frozen forever — additive changes (new fields) are expected in future releases.

### `chimera-memory status --json`

Key fields: `raw_records`, `unique_claims`, `settled_unique_claims`, `m2b_readiness_level`

### `chimera-memory m2b-readiness --json`

Key fields: `readiness_level`, `m2b_ready`, `dq_cohort_summary.organic_real`, `dq_cohort_summary.organic_real_failed`, `dq_cohort_summary.comparable_groups`

### `chimera-memory preflight --json`

Key fields: `source`, `m2b_readiness_level`, `scope_paths`, `warnings`

### `chimera-memory evidence import --dry-run --json`

Key fields: `writes_performed` (always `false` in dry-run), `new_claim_count`, `provenance_summary`, `m2b_preview`

### `chimera-memory receipt bundle`

Produces files in `--output-dir`. File names are stable. Internal JSON structure within files may gain new fields.

---

## What is not built

| Capability | Status |
|---|---|
| Hosted/cloud sync | Not built |
| GitHub App / PR bot | Not built |
| PR diff detection in preflight | Not built (manual `--scope-path` only) |
| M2B scoring | Not built |
| Model routing | Not built |
| Evidence write-import | Not built (dry-run only) |
| Dashboard | Not built |

---

## M2B readiness in CI

`chimera-memory m2b-readiness --json` returns the local ledger's readiness state. In a fresh CI environment the ledger starts empty, so readiness will always be `blocked`.

This is expected. M2B readiness is meaningful only in a **persistent** local developer ledger, not in ephemeral CI runners. Do not gate CI jobs on M2B readiness.
