# Coding Agent & Jules Workflow Guidelines

This document specifies the operational guidelines, execution rules, and workflow expectations for coding agents (such as Jules) working on **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Core Directives & Guiding Principles

1. **Read & Inspect Before Modifying Code**: Always inspect existing canonical subsystem code and tests in `scripts/` before altering functionality. Do not guess internal interfaces.
2. **Preserve Canonical Boundaries**: Respect package responsibilities (`scripts/domain`, `scripts/data`, `scripts/quant`, `scripts/pipeline`, `scripts/backtest`, `scripts/monitoring`, `scripts/artifacts`). Never import from or re-create deleted `scripts/lib/*` modules.
3. **Focused Changes**: Work in small, focused increments addressing a single task or feature scope. Do not mix unrelated refactorings or formatting changes into a single PR.
4. **No Financial Math in Frontend**: Do not add quantitative calculations to `src/`. The frontend is strictly a read-only viewer for pre-rendered artifacts in `generated/`.
5. **Fail-Closed & Anti-Lookahead Safety**: Maintain point-in-time isolation ($\le T$) for all historical data and signal logic. Do not fabricate missing values or create silent fallbacks.

---

## 2. Standard Iterative Execution Workflow

```text
1. Inspect Scope & Relevant Docs (docs/*)
               │
               ▼
2. Locate Affected Canonical Package & Tests (scripts/tests/)
               │
               ▼
3. Run Smallest Targeted Test First (uv run --frozen pytest ...)
               │
               ▼
4. Make Minimal, Focused Code Edits
               │
               ▼
5. Verify via Targeted Unit Test & Ruff Format/Lint
               │
               ▼
6. Run Full Test Suite (uv run --frozen pytest)
               │
               ▼
7. Update Documentation if System Architecture Changed
               │
               ▼
8. Complete Pre-Commit Validation & Submit
```

---

## 3. Targeted Test Execution Guide

To keep feedback loops fast during development, run the smallest relevant unit test file before running the full test suite:

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
