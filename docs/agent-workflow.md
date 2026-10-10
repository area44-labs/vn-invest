# Coding Agent Workflow Guidelines

This document specifies the operational guidelines, execution rules, and workflow expectations for coding agents working on **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Core Directives & Guiding Principles

1. **Read & Inspect Before Modifying Code**: Always inspect existing canonical subsystem code and tests in `scripts/` before altering functionality. Do not guess internal interfaces.
2. **Preserve Canonical Boundaries**: Respect package responsibilities (`scripts/domain`, `scripts/data`, `scripts/quant`, `scripts/pipeline`, `scripts/backtest`, `scripts/monitoring`, `scripts/artifacts`).
3. **Focused Changes**: Work in small, focused increments addressing a single task or feature scope. Do not mix unrelated refactorings or formatting changes into a single PR.
4. **No Financial Math in Frontend**: Do not add quantitative calculations to `src/`. The frontend is strictly a read-only viewer for pre-rendered artifacts in `generated/`.
5. **Fail-Closed & Anti-Lookahead Safety**: Maintain point-in-time isolation ($\le T$) for all historical data and signal logic. Do not fabricate missing values or create silent fallbacks.

---

## 2. Standard Iterative Execution Workflow

```text
1. Inspect Scope & Relevant Docs (docs/*)
               │
               ▼
2. Locate Affected Canonical Package & Tests (scripts/)
               │
               ▼
3. Make Minimal, Focused Edits & Update Documentation (docs/*)
               │
               ▼
4. Verify via Targeted Unit Test & Ruff Format/Lint (When modifying Python code; repeat as needed)
               │
               ▼ (Once ALL relevant code and documentation changes are completed)
5. Run Full Test Suite (uv run --frozen pytest; skipped for doc-only changes)
               │
               ▼
6. Execute Verification Script (uv run --frozen python scripts/generate_report.py --update)
               │
               ▼
7. Complete Pre-Commit Validation & Submit
```

_Note: Run pytest tests only when necessary (e.g. when modifying Python backend code or tests). Do **not** execute the full test suite (`uv run --frozen pytest`) after every single file modification. Keep development iteration fast by executing targeted unit tests during code edits, and run the full test suite specifically after all task modifications are completed. Pytest execution may be skipped entirely for documentation-only changes that do not alter executable behavior._

---

## 3. Targeted Test Execution Guide

To keep feedback loops fast during development, run the smallest relevant unit test file while editing files, deferring the full test suite until all edits are complete:

- Domain Models & Universe:
  ```bash
  uv run --frozen pytest scripts/tests/test_domain.py
  ```
- Quantitative Signals & Recommendations:
  ```bash
  uv run --frozen pytest scripts/tests/test_recommendation.py scripts/tests/test_engines.py
  ```
- T+2.5 Risk & Trade Plans:
  ```bash
  uv run --frozen pytest scripts/tests/test_risk.py
  ```
- Backtest Subsystem & Cost Deductions:
  ```bash
  uv run --frozen pytest scripts/tests/test_portfolio_backtest.py scripts/tests/test_backtest.py
  ```
- Monitoring & Operational Drift:
  ```bash
  uv run --frozen pytest scripts/tests/test_monitoring.py scripts/tests/test_drift_monitoring.py
  ```
- Artifact Publishing & Transactions:
  ```bash
  uv run --frozen pytest scripts/tests/test_artifact_publisher.py scripts/tests/test_artifact_transaction.py
  ```

---

## 4. Documentation Maintenance Rule

Whenever a code change alters subsystem boundaries, data contracts, pipeline stages, CLI parameters, or testing mechanics:

- Update the single authoritative document in `docs/` governing that topic.
- Verify that internal Markdown links across `docs/` and `AGENTS.md` remain valid.
- Ensure relevant documentation files under `docs/` are updated in the same change whenever system architecture, contracts, or behavior change.
