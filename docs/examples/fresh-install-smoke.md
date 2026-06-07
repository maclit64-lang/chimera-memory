# Fresh Install Smoke Transcript

This shows what a new user sees when installing and running chimera-memory for the first time.
All session IDs, claim IDs, and paths are replaced with placeholders.

---

## 1. Install

```bash
python -m venv /tmp/cm-demo
source /tmp/cm-demo/bin/activate
pip install --upgrade pip
pip install chimera-memory
```

```bash
chimera-memory --version
# chimera-memory 0.10.0
```

---

## 2. Initialise the local ledger

Creates `.chimera-memory/` and adds it to `.gitignore`.

```bash
chimera-memory init
# /path/to/project/.chimera-memory
# Created .gitignore with .chimera-memory/
```

---

## 3. Start a session

Every verification run lives inside a session. The session captures agent identity, branch, and task.

```bash
chimera-memory session start \
  --branch feat/my-branch \
  --task-label "fix type errors" \
  --agent kiro \
  --model claude-sonnet-4.6 \
  --harness-id kiro-cli
# sess-<session-id>
```

---

## 4. Wrap a verification command

`wrap` runs the command and records whether it passed (VALIDATED) or failed (CONTRADICTED).

```bash
chimera-memory wrap \
  --scope-path . \
  --failure-origin organic_real \
  --verification-scope package \
  -- python -c "print('hello chimera')"
# VALIDATED claim_id=<claim-id> exit_code=0 command="python -c print('hello chimera')"
```

For real work, replace `python -c "..."` with your actual checks:

```bash
chimera-memory wrap \
  --scope-path packages/my-package \
  --failure-origin organic_real \
  --verification-scope package \
  -- pytest packages/my-package/tests -q
```

---

## 5. End the session

```bash
chimera-memory session end --status PASSED
```

```
Chimera Session Receipt

Task: fix type errors
Agent: kiro
Model: claude-sonnet-4.6
...
Commands observed:
- python -c print('hello chimera') [test] → VALIDATED

Outcome:
PASSED
```

---

## 6. Verify integrity

Confirms ledger chain is intact. Zero broken records is the signal that matters.

```bash
chimera-memory verify
```

```
Chimera Memory Integrity

Status:          OK
Claims:          2
Legacy unsigned: 0
Chained records: 2
Broken records:  0
```

---

## 7. View the receipt

```bash
chimera-memory receipt latest
```

```
Chimera Session Receipt

Task: fix type errors
Agent: kiro
Model: claude-sonnet-4.6
...
```

---

## 8. Check health

`doctor` shows initialisation state, evidence hygiene, and next actions.

```bash
chimera-memory doctor
```

```
Chimera Memory Doctor
Status: warnings

Checks:
  ✓ initialized
  ✓ .gitignore contains .chimera-memory/
  ⚠ no active session
  ✓ 1 settled claims (1 unique)
  ✓ integrity: OK, broken: 0
  ✓ M2B readiness: blocked
    ↳ organic_real claims too few: 1 < 25
    ↳ organic_real failures too few: 0 < 5

Evidence Hygiene:
  ✓ scoped claims: 1/1 (100%)
  ✓ unknown failure_origin: 0 claim(s)
  ✓ open repair loops: 0

Not built: M2B scoring · model routing · hosted/cloud sync · write-import
```

"Status: warnings" is normal when no session is active. No action required.

---

## 9. Preflight advisory

Before starting a task, surface any historical failures in your scope.

```bash
chimera-memory preflight --scope-path .
```

On a fresh ledger:

```
Chimera Memory Preflight Advisory

Preflight is advisory only. No routing, autonomy, or statistical confidence implied.

Source:            explicit_scope
Matching claims:   0
M2B readiness:     blocked

Recent failures: none matching scope

No historical failures for this scope yet.
To build preflight intelligence, run a scoped dogfood session:
  chimera-memory template dogfood --scope-path <your-package>
```

---

## 10. M2B readiness explain

Shows exactly what evidence is missing before M2B scoring can be trusted.
On a fresh ledger this is expected and is not an error.

```bash
chimera-memory m2b-readiness --explain
```

```
Chimera Memory M2B Readiness Gate

This is a readiness gate, not M2B drift scoring.
No model ranking, routing, autonomy, or statistical confidence implied.

Readiness:        BLOCKED

Why readiness is blocked:

  organic_real_failed:
    current:   0
    required:  5
    remaining: 5

  comparable_groups:
    current:   0
    required:  2
    remaining: 2

How to build qualifying evidence honestly:

  - Use chimera-memory on real scoped work.
  - Wrap real validation commands with --scope-path and --failure-origin.
  - If a real command fails due to a real defect, record it as organic_real.
  - Do not manufacture failures.
  - M2B readiness is a quality gate, not a deadline.
```

---

## What to do next

Run `chimera-memory agent-guide --agent generic` for the full session/wrap/repair-loop protocol.

Run `chimera-memory template dogfood --scope-path <your-package>` to generate a copy-paste session scaffold.
