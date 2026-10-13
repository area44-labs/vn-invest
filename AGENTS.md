# VN Invest — Technical & Operational Playbook for Coding Agents

This document is the authoritative entry point for coding agents working on **VN Invest** (`area44-labs/vn-invest`).

For the full documentation index and task-to-document mapping, see [`docs/index.md`](docs/index.md).

---

## 1. Mandatory Guardrails & Non-Negotiable Constraints

1. **Subsystem Isolation**: Backend Python logic resides under `scripts/`. Frontend React code resides under `src/`.
2. **Read-Only Frontend Visualizer**: `src/` displays pre-rendered artifacts from `generated/`. **Zero financial or quantitative calculations occur in the frontend.**
3. **Fail-Closed & Anti-Lookahead Safety**: Point-in-time isolation (<= T) is enforced for all historical data. Never access future data (> T). Rejects corrupt or incomplete data explicitly without fabricating synthetic values.
4. **Schema Enforcement**: Schema-governed JSON artifacts (`recommendations.json`, `performance.json`, `history/YYYY-MM-DD.json`) must validate against Draft 2020-12 schemas in `schemas/v2/`. Other published artifacts validate against internal dictionary payload contracts (`scripts/pipeline/validation.py`, `scripts/artifacts/`, `scripts/monitoring/`).
5. **No Routine Live Data Updates**: Never run `python scripts/generate_report.py --update` merely as routine validation. It fetches live market data and alters output artifacts. Execute live updates only when explicitly requested and authorized by the user.

---

## 2. Authoritative CLI Commands

Refer to [`docs/testing.md`](docs/testing.md) for complete details on backend and frontend test runners.

### Backend (Python >= 3.14 via `uv`)

```bash
# Sync dependencies
uv sync --frozen

# Lint & Format Python scripts
uv run --frozen ruff check --fix scripts
uv run --frozen ruff format scripts

# Run Python test suite
uv run --frozen pytest

# Offline report generation (using cached market data)
uv run --frozen python scripts/generate_report.py
```

### Frontend & Tooling (Vite+ / `vp`)

```bash
# Install dependencies
vp install

# Install Playwright browser binaries for testing
pnpm exec playwright install --with-deps chromium

# Run frontend tests (vite-plus/test in Playwright browser)
vp test

# Non-mutating frontend check (linting, type checking, formatting validation)
vp check

# Auto-fixing frontend check (lints, typechecks, auto-formats; modifies source files)
vp check --fix

# Run local development server
vp dev

# Build SSG production static site
vp build
```

---

## 3. Agent Execution Principles & Validation

- **Inspect First**: Read relevant code and documentation in `docs/` before making changes.
- **Minimal, Focused Edits**: Make targeted changes satisfying domain contracts. Keep PRs focused.
- **Keep Documentation Synchronized**: Update authoritative files in `docs/` whenever interfaces, behavior, or workflows change.
- **Documentation Validation**:
  - Verify relative Markdown links point to existing target files or valid section anchors.
  - Inspect git diffs to ensure edits do not introduce stale paths or unintended changes.
- **Proportional Testing**: For documentation-only changes, skip unnecessary test suite runs. For code edits, run targeted tests during development and execute full test suites when changes are complete.

<!-- vnai-bootstrap | auto-generated -->

# Vnstock Vibe Onboarding

Please visit https://vnstocks.com/onboard/agent-guide to learn how to setup AI Agents for vnstock.
