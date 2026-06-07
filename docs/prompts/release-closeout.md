# Release Closeout — Chimera Memory Prompt

Use this prompt for any chimera-memory release closeout session.

---

## Prompt

You are running a chimera-memory release closeout.

**Do not publish. Do not tag. Do not bump version in this task unless explicitly instructed.**

### Sequence

```bash
# 1. Confirm branch and HEAD
git branch --show-current
git rev-parse --short HEAD
git status --short --untracked-files=no

# 2. Confirm version
grep '^version' packages/chimera-memory/pyproject.toml
grep '^version' packages/chimera-memory-types/pyproject.toml
chimera-memory --version

# 3. Full test suite
uv run pytest packages/chimera-memory/tests -m "not slow" --tb=short -q

# 4. Type checks
uv run mypy packages/chimera-memory/src
uv run mypy packages/chimera-memory-types/src

# 5. Lint
uv run ruff check packages/chimera-memory/src packages/chimera-memory/tests \
  packages/chimera-memory-types/src

# 6. Preflight
chimera-memory preflight --scope-path packages/chimera-memory
chimera-memory preflight --scope-path packages/chimera-memory --json

# 7. Verify integrity
chimera-memory verify

# 8. DQ-wrapped session (wrap all checks above in a session)
chimera-memory session start \
  --branch <release-branch> \
  --task-label "vX.Y.Z release closeout" \
  --agent <agent> \
  --model <model> \
  --harness-id <harness>

# Wrap: pytest, mypy×2, ruff, --version, preflight, verify, m2b-readiness
# Use: --failure-origin organic_real --scope-path packages/chimera-memory

chimera-memory session end --status PASSED

# 9. Build artifacts
uv build packages/chimera-memory-types --out-dir /tmp/cm-dist
uv build packages/chimera-memory --out-dir /tmp/cm-dist

# 10. Artifact inspection (no ledger files, no APFS sidecars, Alpha, MIT, py.typed)
python3 -c "
import zipfile, tarfile
from pathlib import Path
bad = ['.chimera-memory', 'claims.jsonl', 'sessions.jsonl', 'integrity.jsonl',
       'index.sqlite', 'append_state.json']
for p in sorted(Path('/tmp/cm-dist').iterdir()):
    if p.suffix == '.whl':
        with zipfile.ZipFile(p) as z:
            names = z.namelist()
    else:
        with tarfile.open(p) as t:
            names = t.getnames()
    found = [b for b in bad if any(b in n for n in names)]
    print(p.name, 'bad=' + str(found))
"

# 11. Fresh venv smoke from built wheels
python3 -m venv /tmp/cm-smoke && source /tmp/cm-smoke/bin/activate
pip install /tmp/cm-dist/chimera_memory_types-*.whl /tmp/cm-dist/chimera_memory-*.whl --quiet
chimera-memory --version
chimera-memory init && chimera-memory preflight --scope-path . --json
deactivate

# 12. Receipt bundle
chimera-memory receipt bundle \
  --output-dir ./receipts \
  --include-preflight \
  --scope-path packages/chimera-memory

# 13. M2B readiness (BLOCKED is expected and not a blocker)
chimera-memory m2b-readiness
```

### Completion criteria

- [ ] All tests pass
- [ ] mypy 0 errors (both packages)
- [ ] ruff clean
- [ ] Artifact inspection clean
- [ ] Fresh venv smoke passes
- [ ] DQ session: all wraps VALIDATED
- [ ] `--version` returns correct version
- [ ] `preflight --json` returns `schema_version: 2`
- [ ] `verify` returns 0 broken

### After closeout (human actions only)

```bash
# Publish (requires fresh account-scoped PyPI token)
UV_PUBLISH_TOKEN="pypi-..." uv publish /tmp/cm-dist/*.whl /tmp/cm-dist/*.tar.gz

# Tag (only after public PyPI smoke passes)
git tag -a vX.Y.Z <HEAD> -m "Release chimera-memory X.Y.Z"
git push origin vX.Y.Z
```

### Non-goals

- Do not publish from agent without explicit human approval
- Do not create tags without explicit human approval
- Do not debug GitHub Actions billing
- M2B BLOCKED is not a release blocker
