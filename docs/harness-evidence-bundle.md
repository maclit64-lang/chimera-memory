# Harness Evidence Bundle

A **Harness Evidence Bundle** is a portable, redacted, hash-manifested export of
local [Harness Lite](harness-lite.md) run observations. It packages what was
observed into a directory that external Chimera Engine / Harness / Forge tooling
can consume as a neutral observation artifact — without importing
`chimera-memory`.

It is an **evidence transport format, not a verdict engine**.

## What it answers

- What was observed (which commands / checks / tools were recorded or run)?
- Which work session / brief did the observations attach to?
- Which check labels and exit codes were recorded?
- Which outputs were redacted or truncated?
- Which artifact refs were attached?
- Which files make up the bundle, and what are their hashes?
- Was the bundle produced from read-only state?

## What it does not answer

- Whether the code was correct.
- Whether the task was complete.
- Whether anything is appropriate to merge.
- Whether a command's exit code is a verdict (an exit code is recorded, never
  interpreted; `0` is not described as an outcome label and nonzero is not
  either).
- Whether a model should be trained or an agent should receive authority.

## What it contains

`chimera-memory harness bundle --work-session SESSION_ID --output-dir DIR` writes
five files:

- `HARNESS_EVIDENCE.md` — a human-readable overview (bundle id, filters, summary,
  a neutral run list).
- `harness-evidence.json` — the machine-readable bundle: `schema_version`,
  `bundle_id`, `created_at`, `root`, `filters`, `source`, `summary`,
  `harness_runs`, `redaction_summary`.
- `harness-runs.json` — just the portable run array, for external tools that want
  the runs without the envelope.
- `manifest.json` — the bundle manifest: every other file listed with its
  `sha256` and byte count.
- `README.md` — a short description of the bundle for whoever receives it.

Each run carries compact, output-free fields: `run_id`, timestamps,
`duration_ms`, `mode`, `command`, `cwd`, `exit_code`, `status`, `check_label`,
`note`, `tags`, `work_session_id`, `brief_id`, `redaction_applied`,
`output_truncated`, `stdout_sha256`, `stderr_sha256`, `artifact_refs`, `source`.

## What it omits, and why

Full stdout/stderr is **never** included; outputs are referenced by `sha256`.
Bounded, already-redacted previews are **omitted by default** and included only
when you set `--include-previews`. A portable evidence bundle should be
attachable to a review by default, so it carries no preview text unless you
explicitly ask for it.

## Filters

```bash
chimera-memory harness bundle --work-session SESSION_ID --output-dir DIR
chimera-memory harness bundle --brief BRIEF_ID --output-dir DIR
chimera-memory harness bundle --tag v0.31 --output-dir DIR
chimera-memory harness bundle --limit 20 --output-dir DIR
chimera-memory harness bundle --work-session SESSION_ID --include-previews --output-dir DIR
```

Exact-match filters combine with AND. `--limit` keeps the most-recent N runs
(stored order).

## Manifest hashing

The bundle writer hashes every generated file with `sha256` and records the file
list, hashes, and byte counts in `manifest.json`, with deterministic file
ordering and deterministic JSON (`sort_keys`). `manifest.json` lists the other
four files (it cannot hash itself); the `bundle_id` is derived from the run
content, so the same runs produce the same id.

## Inspecting a bundle

```bash
chimera-memory harness bundle-inspect DIR
chimera-memory harness bundle-inspect DIR --json
```

Inspection recomputes each file hash against the manifest and reports neutral
counts: `file_count`, `harness_run_count`, `hash_mismatch_count`,
`missing_file_count`, `unexpected_store_file_count`, plus whether the
`schema_version` is recognized and the runs parse. A bundle that holds together
reports a `hash_mismatch_count` of 0, a `missing_file_count` of 0, and an
`unexpected_store_file_count` of 0. The check looks for mutable store files
(`*.jsonl`, a `.chimera-memory` directory) that must never be inside a portable
bundle.

## Diffing two bundles

```bash
chimera-memory harness bundle-diff bundle-a bundle-b
chimera-memory harness bundle-diff bundle-a bundle-b --json
```

The diff reports added / removed `run_id`s, summary deltas (including redaction /
truncation / artifact-ref deltas), and changed manifest files. Because the ledger
is append-only, a run's content should not change; the diff defensively reports
`content_changed` for any `run_id` present in both bundles with a different
content hash. `content_changed` is a signal to inspect — not a claim of
corruption — unless `bundle-inspect` shows a manifest hash mismatch.

## Relation to the Work Packet

A [Work Packet](work-packet.md) bundle can **reference** an evidence bundle by
relative path and manifest hash without copying it:

```bash
chimera-memory work-packet bundle --session SESSION_ID --output-dir packet \
  --harness-evidence-dir harness-evidence-bundle
```

This records a `harness_evidence_bundle` object in the packet JSON
(`path`, `schema_version`, `manifest_sha256`, `harness_run_count`) and a matching
markdown section. The packet bundle never copies the evidence bundle and never
auto-generates one.

## How external tools consume it

An external Engine / Harness / Forge tool can read `harness-runs.json` (or
`harness-evidence.json`) and verify integrity by recomputing the `manifest.json`
hashes — without importing `chimera-memory`. The bundle is a plain directory of
JSON + markdown with a hash manifest, so any language can read it. It carries
local observations only; it confers no scoring, routing, training, or execution
authority, and consuming it does not make it any of those things.

## Boundaries

- Read-only on the memory store: reads the ledger, writes nothing to it.
- Explicit write only into the chosen output directory.
- Executes nothing; creates no harness runs and no work-session events.
- Never includes unbounded stdout/stderr and never includes secrets (previews go
  through the local redaction helper, and full output is referenced by hash only).
- Bundle creation is CLI-only; the read-only MCP tools
  (`chimera_harness_bundle_inspect`, `chimera_harness_bundle_diff`) inspect and
  compare existing bundles but never create one.

Advisory only — a local observation artifact; not a correctness, safety,
approval, merge, or production-readiness signal, and not a form of verification.
