# ADR: Canonical Chimera Memory base is v0.27.0; do not build on the court fork

## Status

Accepted — Stage 0 base lock. No public release, tag, or publish was performed.

## Context

A `chimera-memory` package appears on two lines: the canonical OSS memory branch
(`oss/memory-bigrel4a-cli-policy`) and an engine/harness fork
(`court/crt-foundation`). The court fork carries a stale memory copy (v0.6.1)
whose test suite does not pass — a broken internal import breaks collection. A
prior plan audit was run against that fork and therefore mis-reported several
shipped features (claim-lock, MCP, the receipt-on-PR Action, proof-debt, and
test-weakening warnings) as "absent"; those features are in fact present and
green on the canonical line.

## Decision

- The canonical Chimera Memory base is **v0.27.0** at commit **`7d2b993e5`**.
- **`court/crt-foundation` is not the Chimera Memory product base.** Its memory
  copy is stale (v0.6.1) and must not receive Chimera Memory product work.
- All future Chimera Memory work (the EvidenceEvent foundation and later slices)
  branches from the canonical base; any plan or audit must be re-based onto the
  canonical line rather than the fork.

## Stage 0 outcome

- Canonical verified green at lock time: the full test suite, lint, and type
  checks pass.
- Added hygiene coverage: an anti-overclaim membrane test and a version-coherence
  test, and fixed one behavior-preserving source SyntaxWarning.
- The canonical version remains an unpublished release candidate — no tag,
  release, or publish happened.

## Notes

Detailed reconciliation bookkeeping (remote-durability status and local worktree
layout) and the court-fork module port/drop triage are tracked internally and are
intentionally omitted from this public record.
