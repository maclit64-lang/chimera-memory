# Chimera Memory — Public Launch Walkthrough

A complete path from install to shareable evidence in under 10 minutes.

## 1. Install

```bash
pip install chimera-memory
```

## 2. See a demo

```bash
chimera-memory demo --output-dir ./chimera-demo
chimera-memory bundle inspect ./chimera-demo/receipt
```

## 3. Set up project checks

```bash
cd your-project
chimera-memory init
chimera-memory checks init --preset python
```

Edit `chimera-memory.checks.toml` to add your real commands:

```toml
[[checks]]
name = "pytest"
command = ["pytest", "tests/", "-q"]

[[checks]]
name = "mypy"
command = ["mypy", "src/"]
```

## 4. Run checks with a report

```bash
chimera-memory checks run --bundle --output-dir ./run-output
```

Output:

```text
run-output/
  report.md      — human-readable summary
  report.json    — machine-readable summary
  receipt/       — full receipt bundle
```

## 5. Inspect and compare

```bash
chimera-memory bundle inspect ./run-output/receipt
chimera-memory bundle diff ./old-run/receipt ./new-run/receipt
```

## 6. Health check

```bash
chimera-memory doctor
chimera-memory verify
```

## What Chimera Memory is

A local-first reliability memory for AI-assisted work. It records what was tried, what command verified it, what happened, and what receipt proves it.

## What it is NOT

- Not M2B scoring or model ranking
- Not routing or autonomous evaluation
- Not hosted/cloud (all data stays local)
- Not a dashboard or marketplace
- Not a security guarantee or proof of authenticity
