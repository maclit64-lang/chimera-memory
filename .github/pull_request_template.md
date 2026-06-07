---
name: Pull Request
about: Submit a change to chimera-memory
title: "[PR] "
---

## Checklist

- [ ] `pytest packages/chimera-memory/tests -m "not slow"` passes
- [ ] `mypy packages/chimera-memory/src` is clean
- [ ] `mypy packages/chimera-memory-types/src` is clean
- [ ] `ruff check packages/chimera-memory/src packages/chimera-memory/tests packages/chimera-memory-types/src` passes
- [ ] `chimera-memory verify` reports 0 broken
- [ ] No ledger files (`.chimera-memory/`) are committed
- [ ] No tokens, private keys, or absolute paths (`/Users/...`, `/home/...`) in diff
- [ ] No M2B scoring, model ranking, or routing claims added to docs
- [ ] Docs updated if behavior changed
- [ ] New tests added if new behavior added

## What does this PR change?

<!-- Brief description of the change -->

## Why?

<!-- What problem does it solve or what improvement does it make? -->

## Testing done

<!-- What did you run to verify the change works? -->
