# Claim-Locked Coding

Claim-locked coding records a sealed prediction **before** an agent edits code,
then settles it against the exact checks that were pre-committed. The point is a
falsifiable, scope-bound evidence primitive — not a correctness proof.

> This produces **settled evidence, not proof of correctness**.

## 0. Validate before locking (optional but recommended)

Before sealing a claim, run a dry-run validation:

```bash
chimera-memory claim validate --from-file claim.toml
```

This checks schema, command shape, and reports warnings without writing anything
to `.chimera-memory/`. Hard errors (missing intent, non-list command, empty
command) must be fixed before locking. Warnings (broad commands, missing
must-not-break) are informational and do not block locking.

```bash
# also available as JSON
chimera-memory claim validate --from-file claim.toml --json
```

## 1. Lock a claim before editing

Write a `claim.toml`:

```toml
intent = "fix checkout null dereference"
scope_path = "packages/cart"
predicted_outcome = "all pass"

[[falsifiers]]
command = ["uv", "run", "pytest", "tests/test_checkout.py::test_empty_cart"]

[[must_not_break]]
command = ["uv", "run", "pytest", "tests/test_cart.py"]

[[must_not_break]]
command = ["uv", "run", "ruff", "check", "packages/cart"]
```

> Use explicit target paths in commands. `["mypy"]` or `["ruff", "check"]`
> without targets are valid but trigger a `BROAD_COMMAND` warning because their
> behaviour is config-dependent. Explicit paths make the evidence clearer.

Lock it:

```bash
chimera-memory claim lock --from-file claim.toml
# Locked claim clm_…
#   intent:  fix checkout null dereference
#   scope:   packages/cart
#   quality: strong
```

The claim is sealed: a `payload_hash` covers the intent, scope, falsifier, and
must-not-break commands. The pre-edit git HEAD and dirty state are recorded.

### Flag-based mode

For quick claims you can skip the file:

```bash
chimera-memory claim lock \
  --intent "fix checkout null dereference" \
  --scope-path packages/cart \
  --falsifier "pytest tests/test_checkout.py::test_empty_cart"
```

A `--falsifier` string is parsed into an explicit `list[str]` and **rejected**
if it contains shell metacharacters. The internal command contract is always a
list executed with `shell=False`.

## 2. Do the work

Edit code as usual. Settlement compares the working tree against the sealed
pre-edit git HEAD.

## 3. Settle against the sealed checks only

```bash
chimera-memory claim settle clm_…
```

Settlement runs **only** the sealed falsifier and must-not-break commands — it
can never substitute a different check. Possible statuses:

| Status | Meaning |
|---|---|
| `VALIDATED` | All sealed checks passed, no scope drift |
| `CONTRADICTED` | A sealed check failed |
| `UNSETTLED` | A sealed command could not be run (or no falsifier declared) |
| `SCOPE_DRIFT` | Checks passed, but files outside `scope_path` changed |

## 4. Inspect

```bash
chimera-memory claim list
chimera-memory claim show clm_…
chimera-memory claim report clm_…
```

## Multi-terminal readiness

Each claim records an `attribution` block (`session_id`, `terminal_id`,
`worktree_path`, `branch`, `agent_name`, `model_name`, `harness_id`,
`attribution_confidence`). Unknown values are recorded honestly as `null` /
`"unknown"` — attribution is never fabricated. This is the seam for future
multi-agent / multi-terminal attribution; v0.22 ships the schema and basic
reporting only.

## Honesty

- Scope coverage is path-based ("covered by declared claim scope").
- A settled claim is **not** a guarantee that the code is tested, correct, or
  secure.
- See [claim-lock-json.md](../contracts/claim-lock-json.md) for the full schema.
