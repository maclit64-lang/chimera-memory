# chimera-memory 0.22.1 — Claim Contract Validation + Dogfood Hardening

## Release theme

v0.22.1 hardens the v0.22 Claim-Locked Evidence workflow based on organic dogfood.

## Highlights

### Claim contract validation

```bash
chimera-memory claim validate --from-file claim.toml
chimera-memory claim validate --from-file claim.toml --json
```

- Dry-run parse and validate a claim file without locking or writing anything.
- Hard errors (missing intent, non-list command, empty command, missing falsifier)
  are reported and block locking.
- Warnings (broad commands, missing must-not-break, broad scope) are informational
  and do not block locking.

### Lock-time warnings

`claim lock` now runs validation before sealing. Hard errors refuse the lock.
Warnings are stored in the claim's `quality.warnings` block.

### Broad-command detection

Commands with no explicit target/path now trigger a `BROAD_COMMAND` warning:

```text
["mypy"]                      → BROAD_COMMAND
["uv", "run", "pytest"]       → BROAD_COMMAND
["ruff", "check"]             → BROAD_COMMAND
```

The correct pattern:

```toml
[[falsifiers]]
command = ["uv", "run", "pytest", "packages/chimera-memory/tests/test_xray.py"]

[[must_not_break]]
command = ["uv", "run", "mypy", "packages/chimera-memory/src"]
```

Warnings are non-blocking by design. Some repos intentionally rely on tool
defaults. Chimera surfaces the ambiguity, not enforces a style.

### Warning codes

| Code | Meaning |
|---|---|
| `BROAD_COMMAND` | No explicit target/path for test/lint/type tool |
| `MISSING_MUST_NOT_BREAK` | No must_not_break checks declared |
| `BROAD_SCOPE_PATH` | scope_path is `.` (whole repo) |
| `DIRTY_PRE_EDIT_STATE` | Tree dirty at lock/validate time |
| `NO_GIT_PRE_EDIT_STATE` | git unavailable |

### Merge X-Ray diff-mode hardening (from dogfood)

- `PR_EVIDENCE.md` now shows a clear diff-mode header (Commit-range vs Working-tree)
- Working-tree mode shows a prominent recommendation to use `--base main --head HEAD`
- Evidence-dark files are classified as `source_files` vs `likely_cache_or_build`
- Cache/build artefacts (`__pycache__/`, `.pytest_cache/`) are visibly separated

## Tests

+39 total new tests in this release (27 claim-validate + 12 xray diff-mode).

## Honesty boundary

Settled evidence, not proof of correctness. Warnings are heuristic. Scope
coverage is path-based. Attribution is schema-only.

## Not built

- hooks/MCP/GitHub Action/App
- model ranking/routing/M2B scoring
- hosted/cloud/dashboard
- coverage.py/lcov ingestion
- multi-scope claims
- multi-terminal orchestration

## Dependency

```text
chimera-memory-types>=0.22.1,<1.0
```
