# chimera-memory 0.26.1 — Claude Hook Warning Patch

## Fix

- Corrects misleading Claude hooks install warning around `.claude/hooks/` and `.gitignore`.
  The old text mentioned "sentinel files in /tmp are ephemeral" which was confusing because
  sentinel files are always written to /tmp, not to `.claude/`. The warning is about committing
  hook scripts, not sentinels. Reworded to be accurate and actionable.

## No feature changes

- no X-Ray filtering
- no claim history filtering
- no GitHub Action/App
- no hosted/cloud
- no model ranking/routing/M2B scoring

## Known follow-up

Post-v0.26 dogfood found that long-running worktrees can make PR_EVIDENCE.md noisy because
historical settled claims appear in X-Ray output. This is intentionally not fixed in v0.26.1.
More dogfood is needed before choosing the right API (candidate: `xray --since <ref>`).

## Dependency

chimera-memory-types>=0.26.1,<1.0
