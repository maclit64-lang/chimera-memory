# Bundle Inspect JSON Contract

## Purpose

`chimera-memory bundle inspect <path> --json` emits a read-only safety inspection of a receipt or evidence bundle. Intended for agents and CI that need to verify bundle contents before sharing or importing.

## Schema version

`"schema_version": 1` — stable from v0.15. Integer.

## Stable fields

| Field | Type | Description |
|---|---|---|
| `schema_version` | `int` | Always `1` |
| `path` | `string` | Absolute path to inspected bundle |
| `bundle_type` | `string` | `receipt`, `evidence`, or `unknown` |
| `status` | `string` | `OK`, `WARNING`, `CRITICAL`, or `UNKNOWN` |
| `file_count` | `int` | Number of files in bundle |
| `present_files` | `array[string]` | File names present |
| `missing_expected_files` | `array[string]` | Expected files not found |
| `unexpected_sensitive_files` | `array[string]` | Raw ledger files that should not be shared |
| `raw_ledger_files_found` | `bool` | Whether raw ledger files or .chimera-memory/ exist |
| `token_like_hits` | `array[string]` | Files containing token-like strings |
| `private_path_hits` | `array[string]` | Files containing private filesystem paths |
| `readme_present` | `bool` | Whether README.md exists |
| `manifest_present` | `bool` | Whether manifest.json exists |
| `notes` | `array[string]` | Human-readable findings |
| `next_actions` | `array[string]` | Recommended actions |

## Status model

| Status | Condition |
|---|---|
| `OK` | No issues detected |
| `WARNING` | Token-like or private path content found |
| `CRITICAL` | Raw ledger files or .chimera-memory/ directory present |
| `UNKNOWN` | Bundle type cannot be determined |

## Additive-change policy

New fields may be added. Consumers must tolerate unknown keys. `schema_version` increments only on breaking removals or renames.

## Non-goals

- Not import
- Not write
- Not proof of authenticity
- Not cryptographic verification
- Not hosted/cloud
- Not M2B scoring
