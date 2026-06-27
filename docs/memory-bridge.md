# Memory Evidence Bridge

The **Memory Evidence Bridge** is a read-only scaffold that consumes *exported*
Chimera Memory artifacts and normalizes them into a stable, neutral input record
(`memory_bridge_evidence.v1`) that a future Engine/Harness branch can consume — by
reading the on-disk artifact contract, not Memory's in-memory classes.

It is a **read-only evidence normalization scaffold, not a decision system.**

## What the bridge consumes

- a [Harness Evidence Bundle](harness-evidence-bundle.md) directory
  (`harness-evidence.json` + `harness-runs.json` + `manifest.json` + …); and
- a [Work Packet](work-packet.md) bundle directory (`work-packet.json` +
  `manifest.json`) that may carry a `harness_evidence_bundle` reference and
  embedded [consequence observations](consequence-observations.md).

The source kind is detected from the on-disk contract: a directory with
`harness-evidence.json` is read as a Harness Evidence Bundle; a directory with
`work-packet.json` is read as a Work Packet bundle.

## What the bridge emits

A single normalized record, `memory_bridge_evidence.v1`:

```json
{
  "schema_version": "memory_bridge_evidence.v1",
  "created_at": "...",
  "source_kind": "harness_evidence_bundle",
  "source_path": "...",
  "source_manifest_sha256": "...",
  "memory_version": "0.32.0",
  "work_session_id": "...",
  "brief_id": "...",
  "harness_runs": [],
  "consequence_observations": [],
  "suggested_checks": [],
  "artifact_refs": [],
  "manifest": {
    "file_count": 0,
    "hash_mismatch_count": 0,
    "missing_file_count": 0,
    "unexpected_store_file_count": 0,
    "parse_error_count": 0,
    "recognized_record_count": 0
  },
  "notes": []
}
```

Every field is a count, an id, a path, a hash, or an observed value. Harness runs
carry observed fields only (`run_id`, `mode`, `command`, `cwd`, `exit_code`,
`status`, `check_label`, `redaction_applied`, `output_truncated`, `stdout_sha256`,
`stderr_sha256`, `artifact_refs`). Unknown input fields are ignored
deterministically (the record carries the known observed fields only).

## How to inspect a bundle

```bash
chimera-memory bridge inspect --bundle-dir DIR
chimera-memory bridge inspect --bundle-dir DIR --json
```

`inspect` reports neutral counts: the manifest check (file_count,
hash_mismatch_count, missing_file_count, unexpected_store_file_count,
parse_error_count, recognized_record_count) plus harness_run_count,
consequence_observation_count, suggested_check_count, and artifact_ref_count. It is
read-only and prints counts, never a verdict.

## How to normalize a bundle

```bash
chimera-memory bridge normalize --bundle-dir DIR --output-json normalized.json
```

`normalize` writes the full `memory_bridge_evidence.v1` record — including the
`harness_runs` and `consequence_observations` arrays — to the explicit output path
only. It does not mutate the source bundle, does not create or mutate a
`.chimera-memory` store, executes nothing, and triggers no scan.

## How Work Packet references are followed

When `--bundle-dir` points at a Work Packet bundle, the bridge reads
`work-packet.json`, normalizes its embedded `harness_runs` and
`consequence_observations`, and aggregates each observation's suggested checks.
If the packet carries a `harness_evidence_bundle` reference, the bridge resolves
its relative path deterministically — trying the packet directory, then the packet
directory's parent (the common output root for sibling bundles), then the path as
given — and uses the first base that contains a `manifest.json`. It carries the
referenced bundle's `manifest_sha256` and `harness_run_count`, and folds the
referenced bundle's manifest check into the overall counts. A missing or
unresolvable reference increments `missing_file_count` (or `parse_error_count`) and
adds a neutral note rather than raising.

## What manifest checks mean

For every file listed in a bundle's `manifest.json`, the bridge recomputes the
`sha256` and compares it to the recorded hash. A bundle whose files match reports
`hash_mismatch_count` 0 and `missing_file_count` 0; a file altered after the bundle
was written increments `hash_mismatch_count`. The bridge also counts any mutable
store file (`*.jsonl`, a `.chimera-memory` directory) that should never appear
inside a portable, exported bundle as `unexpected_store_file_count`. These are
counts, not judgments.

## What consequence observations mean

A consequence observation is a neutral inspection target recorded by an explicit
Memory-side `consequence scan` (see
[consequence-observations.md](consequence-observations.md)). The bridge carries
them through verbatim as observed records (`observation_kind`, `subject`,
`suggested_checks`, `note`, ids); it does not generate, rank, or interpret them.

## What the bridge does not decide

- The bridge does not execute commands.
- The bridge does not grade or rank evidence.
- The bridge does not approve work.
- The bridge does not interpret exit codes as outcomes (an exit code is recorded,
  not labelled).
- The bridge does not create training data.
- The bridge does not route candidates.
- The bridge does not grant authority.

It answers what was observed; it never answers whether the work was correct,
complete, appropriate to merge, or which candidate is best.

## Read-only MCP surfaces

The local MCP server exposes `chimera_memory_bridge_inspect` and
`chimera_memory_bridge_normalize_preview` without extra flags. Both are read-only:
they read the bundle, create or mutate no store, execute nothing, and trigger no
scan. `normalize_preview` returns the normalized record inline as a preview; the
normalize *writer* (`bridge normalize --output-json`) is intentionally CLI-only and
not exposed through MCP.

## How this prepares later Engine/Harness/Forge work

Memory records local agent/harness evidence; the Harness Evidence Bundle makes it
portable; consequence observations add neutral inspection targets. This bridge
defines the consumption contract: exported Memory artifacts in, one normalized
`memory_bridge_evidence.v1` record out. A future, clean Engine/Harness branch can
read that on-disk contract and the normalization behavior without importing Memory
internals — and then build inspection on top of neutral evidence, while the bridge
itself continues to decide nothing.

Read-only normalized evidence only — not a correctness, safety, approval, merge, or
production-readiness signal, and not a gate.
