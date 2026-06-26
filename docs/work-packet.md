# Work Packet

A **Work Packet** is one portable, local, advisory review artifact. It composes the existing
read-only projections into a single packet a human or the next agent can review:

- **Claims** — what claims exist, and which settled, contradicted, or remain unresolved.
- **Open / unresolved evidence** and **next inspection targets** — what to look at first.
- **Tool lessons** — the manual, local operational lessons that apply.
- **Candidate tool lessons** — candidates available to review before saving as Tool Notes.
- The **filters** that were applied.

It is built by reusing the handoff builder (claims / open items / inspection targets / tool
notes / counts) and the candidate-lesson selector — no projection logic is duplicated.

## Work Packet vs handoff

```
handoff     = concise daily / next-agent summary
work-packet = portable review packet combining evidence + operational memory
```

The Work Packet does not replace `handoff`; it is the larger, portable artifact. Generating a
Work Packet reads the ledger and changes nothing.

## Generating

Markdown is the default; `--json` emits the machine-readable packet:

```bash
chimera-memory work-packet            # markdown (default)
chimera-memory work-packet --markdown
chimera-memory work-packet --json
```

Write it to a file explicitly (the parent directory must already exist; the memory store is
never modified):

```bash
chimera-memory work-packet --output CHIMERA_WORK_PACKET.md
chimera-memory work-packet --json --output chimera-work-packet.json
```

## Filters

All filters are exact-match and combine with AND; limits apply after filtering; stored order, no
ranking:

```bash
chimera-memory work-packet --claim CLAIM_ID
chimera-memory work-packet --session SESSION_ID
chimera-memory work-packet --status validated
chimera-memory work-packet --task-kind large-repo-forensics
chimera-memory work-packet --tag repo-forensics
chimera-memory work-packet --limit-tool-notes 5
chimera-memory work-packet --limit-candidates 5
```

- `--claim` / `--session` / `--status` narrow the claim view.
- `--task-kind` / `--tag` narrow both **tool notes** and **candidate lessons**.
- `--limit-tool-notes` / `--limit-candidates` cap each list after filtering.

## Tool notes and candidate lessons

Tool notes are the manual lessons you have saved. Candidate lessons are projected from recorded
tool activity and shown so you can review them — saving a candidate is always a separate, manual
`tool-notes add`. The packet never saves a candidate for you.

## JSON shape

```json
{
  "schema_version": 1,
  "artifact": "chimera_work_packet",
  "advisory": "local evidence and operational memory summary only; not a correctness, safety, approval, merge, production-readiness, or speed guarantee",
  "generated_at": "…",
  "filters": {"claim_id": null, "session_id": null, "status": null, "task_kind": null, "tag": null, "limit_tool_notes": null, "limit_candidates": null},
  "summary": {"event_count": 0, "settled_claim_count": 0, "shown_claim_count": 0, "open_or_unresolved_count": 0, "next_inspection_target_count": 0, "tool_note_count": 0, "candidate_count": 0},
  "claims": [],
  "open_or_unresolved": [],
  "next_inspection_targets": [],
  "tool_notes": [],
  "candidate_tool_lessons": []
}
```

## MCP (for local agents)

`chimera_work_packet` is a read-only tool, available without `--allow-write`. It takes the same
optional filters (`claim_id` / `session_id` / `status` / `task_kind` / `tag` / `limit_tool_notes`
/ `limit_candidates`) and returns the same JSON packet. It never creates a store or mutates files.

## Non-goals

The Work Packet is advisory and local. It is **not** a correctness, safety, approval, merge, or
production-readiness signal, and not a form of verification. Building it does **not** save tool
notes, run tools, spawn agents, launch workflows, score, route, rank, fuzzy/semantic match, or
sync anywhere — everything stays in the local `.chimera-memory/` store and reads change nothing.

## Portable bundles and diff

A **bundle** is a small directory you can attach to a PR, handoff, or review thread, and a
**diff** is a read-only comparison of two bundles (or two `work-packet.json` files).

### Bundle export

```bash
chimera-memory work-packet bundle --output-dir packet-a
chimera-memory work-packet bundle --output-dir packet-a --task-kind large-repo-forensics --tag repo-forensics
chimera-memory work-packet bundle --output-dir packet-a --claim CLAIM_ID
```

The bundle directory contains four files:

- `WORK_PACKET.md` — the human-readable packet.
- `work-packet.json` — the machine-readable packet.
- `manifest.json` — the bundle manifest (see below).
- `README.md` — a short description of the bundle.

Writing rules: the export writes only into the output directory and never touches the memory
store; the parent directory must already exist (otherwise a clean error); an existing **non-empty**
output directory is refused unless `--force` is given (an existing empty directory is allowed).
With `--force`, the four bundle files are overwritten.

`manifest.json` carries `schema_version`, `artifact: "chimera_work_packet_bundle"`, `generated_at`,
the same `advisory`, the applied `filters`, the `packet_summary` counts, and a `files` list — each
entry a `path` / `sha256` / `bytes` for `WORK_PACKET.md`, `work-packet.json`, and `README.md`
(the manifest does not hash itself).

### Inspect

```bash
chimera-memory work-packet inspect packet-a
chimera-memory work-packet inspect packet-a --json
```

`inspect` reads `manifest.json` and verifies each listed file exists and its `sha256` and byte
count match. It reports per-file results and any errors, mutating nothing. The command exits
non-zero when the bundle is invalid (missing or corrupt files).

### Diff

```bash
chimera-memory work-packet diff packet-a packet-b
chimera-memory work-packet diff packet-a packet-b --json
chimera-memory work-packet diff packet-a/work-packet.json packet-b/work-packet.json
```

`OLD` and `NEW` may each be a bundle directory or a `work-packet.json` file. The diff is a local
packet comparison: `summary_delta` counts, `claims` added/removed/status_changed, `tool_notes`
added/removed (by `note_id`), and `candidate_tool_lessons` added/removed (by `candidate_id`). It
is read-only and deterministic — not a correctness, safety, approval, merge, or
production-readiness signal.


## Review threads

A **review thread** is a local directory that collects multiple packet bundles over time plus an
index, so an agent or reviewer can track how a branch changed across snapshots. Where a single
bundle is one moment, a thread is a **local packet timeline**.

```
THREAD_DIR/
  index.json
  INDEX.md
  packets/
    wp_<UTC-timestamp>_<8-char-hash>/   # a full bundle (WORK_PACKET.md/json/manifest/README)
```

Snapshot ids look like `wp_YYYYMMDDTHHMMSSZ_<hash>` — a UTC timestamp plus a short content hash of
the packet JSON (safe path characters only). Git is never required; it is not used here.

### Commands

```bash
chimera-memory work-packet thread add --thread-dir review-thread \
  --task-kind large-repo-forensics --tag repo-forensics --limit-candidates 5 --label "first pass"
chimera-memory work-packet thread list review-thread [--json]
chimera-memory work-packet thread inspect review-thread [--json]
chimera-memory work-packet thread diff-latest review-thread [--json]
chimera-memory work-packet thread diff review-thread OLD_ID NEW_ID [--json]
```

- **add** builds the current Work Packet and writes it as a new bundle under
  `packets/<snapshot_id>/`, then appends `index.json` and regenerates `INDEX.md`. It writes only
  under `THREAD_DIR`, never touches `.chimera-memory`, requires an existing parent, and refuses to
  overwrite an existing snapshot directory. `--label`/`--note` are recorded in the index only.
- **list** reads `index.json` and shows snapshot ids, timestamps, summary counts, and labels
  (read-only; does not verify hashes).
- **inspect** verifies each snapshot directory exists, runs bundle inspection, and checks the
  `manifest_sha256` / `packet_sha256` recorded in the index. It exits non-zero when invalid.
- **diff-latest** compares the latest two snapshots; **diff** compares two exact snapshot ids.
  Both reuse the existing packet diff and are read-only. Fewer than two snapshots, or an unknown
  id, produces a clean error.

### index.json fields

`schema_version`, `artifact: "chimera_work_packet_thread"`, `advisory`, `created_at`,
`updated_at`, `snapshot_count`, `latest_snapshot_id`, and `snapshots` — each entry carries
`snapshot_id`, `created_at`, `path`, `label`, `note`, `filters`, `packet_summary`,
`manifest_sha256`, and `packet_sha256`. New snapshots are appended; existing entries and bundles
are never rewritten. `INDEX.md` mirrors the index as a human-readable timeline table.

### MCP (read-only)

`chimera_work_packet_thread_list`, `chimera_work_packet_thread_inspect`, and
`chimera_work_packet_thread_diff_latest` are read-only tools (available without `--allow-write`)
that take a `thread_dir` (resolved against `root` if relative) and never write, create a store, or
mutate the thread. Thread `add` is intentionally CLI-only (it writes a file tree).

### Non-goals

A review thread is a local packet timeline and local review thread index — advisory only. It is
**not** a correctness, safety, approval, merge, or production-readiness signal, and not a form of
verification. It does not save tool notes, run tools, spawn agents, score, route, rank, or sync.

## Harness run observations (v0.30)

The packet gains a read-only `harness_runs` array (compact, output-free) plus summary counts
(`harness_run_count`, `executed_harness_run_count`, `recorded_harness_run_count`,
`truncated_harness_run_count`) and a `## Harness run observations` markdown section. `--session`
narrows runs to that work session; otherwise the most-recent runs are shown (default 20).
`--limit-harness-runs N` keeps the most-recent N in stored order. Bundles hash the updated
`work-packet.json` (inspect still validates); `diff` reports `harness_runs.added` / `.removed` by
`run_id`. An exit code is recorded, not interpreted as a verdict. See
[harness-lite.md](harness-lite.md).
