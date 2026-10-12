# Coding Agent Workflow Guidelines

This document specifies the operational decision rules, execution sequence, and safety directives for AI coding agents working on **VN Invest** (`area44-labs/vn-invest`). Refer to [`testing.md`](testing.md) for full testing reference commands.

---

## 1. Decision Tree & Execution Sequence

```text
1. Inspect Requested Scope & Repository Status
              │
              ▼
2. Consult Relevant Documentation in docs/
              │
              ▼
3. Determine Affected Layer(s):
   ├── Backend Only (scripts/): Python quantitative logic, data, pipeline
   ├── Frontend Only (src/): React SSG UI, routes, loaders
   └── Shared / Cross-Layer (schemas/v2/ + scripts/ + src/): Payloads, models, contracts
              │
              ▼
4. Implement Minimal, Focused Change
              │
              ▼
5. Synchronize Authoritative Docs in docs/ (if contracts/behavior changed)
              │
              ▼
6. Run Proportional Validation:
   ├── Docs-only: Verify relative Markdown links point to existing files & inspect diff
   ├── Backend: Targeted unit test -> full pytest suite (uv run --frozen pytest)
   └── Frontend: Component test -> Vite+ test (vp test)
              │
              ▼
7. Submit Change with Descriptive Summary
```

---

## 2. Mandatory Safety Rules & Invariants

1. **No Routine Live Market Updates**: Never run `python scripts/generate_report.py --update` as routine validation. Running `--update` fetches external live market data and modifies generated report artifacts in `generated/`. Only execute `--update` when explicitly requested and authorized by the user.
2. **Read-Only Frontend Visualizer**: Do not add financial or quantitative business logic to `src/`. All calculations belong in `scripts/`.
3. **Fail-Closed Principle**: Never synthesize fake prices, fallback metrics, or artificial defaults to bypass missing data errors.
4. **Proportional Testing**: Skip unnecessary test executions for documentation-only changes. For code changes, run targeted tests during development and execute full test suites prior to submission.

---

## 3. Documentation & Code Validation

- **Documentation Validation**:
  - Verify all relative Markdown links in modified documents resolve to existing files or valid anchors.
  - Inspect git diffs to ensure no stale paths or broken references were introduced.
- **Backend Code Validation**: `uv run --frozen ruff check --fix scripts` & `uv run --frozen pytest`
- **Frontend Code Validation**: `vp check` & `vp test`
