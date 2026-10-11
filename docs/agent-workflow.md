# Coding Agent Workflow Guidelines

This document specifies the operational guidelines, execution rules, and workflow expectations for coding agents working on **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Core Directives & Guiding Principles

1. **Read & Inspect Before Modifying Code**: Always inspect existing canonical subsystem code and tests in `scripts/` or `src/` before altering functionality. Do not guess internal interfaces.
2. **Preserve Canonical Boundaries**: Respect package responsibilities (`scripts/`) and frontend layer separation (`src/`).
3. **Focused Changes**: Work in small, focused increments addressing a single task or feature scope. Do not mix unrelated refactorings or formatting changes into a single PR.
4. **No Financial Math in Frontend**: Do not add quantitative calculations to `src/`. The frontend is strictly a read-only viewer for pre-rendered artifacts in `generated/`.
5. **Fail-Closed & Anti-Lookahead Safety**: Maintain point-in-time isolation ($\le T$) for all historical data and signal logic. Do not fabricate missing values or create silent fallbacks.

---

## 2. Standard Iterative Execution Workflow

```text
1. Inspect Scope & Relevant Docs (docs/*)
               │
               ▼
2. Locate Affected Canonical Package & Tests (scripts/ or src/)
               │
               ▼
3. Make Minimal, Focused Edits & Update Documentation (docs/*)
               │
               ▼
4. Verify via Targeted Unit Tests & Formatting (pytest / vp check; repeat as needed)
               │
               ▼ (Once ALL relevant code and documentation changes are completed)
5. Run Backend & Frontend Test Suites (uv run --frozen pytest && vp test)
               │
               ▼
6. Execute Verification Commands (python scripts/generate_report.py --update && vp check && vp build)
               │
               ▼
7. Complete Pre-Commit Validation & Submit
```

_Note: Run tests only when necessary (e.g. when modifying backend or frontend code). Do **not** execute full test suites after every single file modification. Keep development iteration fast by executing targeted tests during code edits, and run full test suites specifically after all task modifications are completed. Pytest execution may be skipped entirely for documentation-only changes that do not alter executable behavior._

---

## 3. Targeted Test Execution Guide

To keep feedback loops fast during development, run the smallest relevant test file while editing files:

- Frontend Tests:
  ```bash
  vp test
  ```
- Backend Tests:
  ```bash
  uv run --frozen pytest scripts/tests/test_*.py
  ```

---

## 4. Documentation Maintenance Rule

Whenever a code change alters subsystem boundaries, data contracts, pipeline stages, CLI parameters, file naming rules, or testing mechanics:

- Update the single authoritative document in `docs/` governing that topic.
- Verify that internal Markdown links across `docs/` and `AGENTS.md` remain valid.
- Ensure relevant documentation files under `docs/` are updated in the same change whenever system architecture, contracts, or behavior change.
