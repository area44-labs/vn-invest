# VN Invest — Technical & Operational Playbook for AI Coding Agents

This document is the authoritative entry point for AI coding agents working on **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Documentation Index

For the full documentation index and task-to-document mapping, see [`docs/index.md`](docs/index.md).

Primary guides:

- **Architecture & System Boundaries**: [`docs/architecture.md`](docs/architecture.md)
- **Agent Workflow & Execution Sequence**: [`docs/agent-workflow.md`](docs/agent-workflow.md)
- **Data Contracts & Schemas**: [`docs/data-contracts.md`](docs/data-contracts.md)
- **Frontend SSG Architecture**: [`docs/frontend.md`](docs/frontend.md)
- **Testing Standards**: [`docs/testing.md`](docs/testing.md)
- **CI/CD Workflows**: [`docs/ci-cd.md`](docs/ci-cd.md)

---

## 2. Mandatory Guardrails & Non-Negotiable Constraints

1. **Subsystem Isolation**: Backend Python logic resides under `scripts/`. Frontend React SSG code resides under `src/`.
2. **Read-Only Frontend Visualizer**: `src/` displays pre-rendered artifacts from `generated/`. **Zero financial or quantitative calculations occur in the frontend.**
3. **Fail-Closed & Anti-Lookahead Safety**: Point-in-time isolation (<= T) is enforced for all historical data. Never access future data (> T). Rejects corrupt or incomplete data explicitly without fabricating synthetic values.
4. **Schema Enforcement**: Published JSON artifacts in `generated/` must validate against schemas in `schemas/v2/` via `scripts/schema/registry.py`.
5. **No Routine Live Data Updates**: Never run `python scripts/generate_report.py --update` merely as routine validation. It fetches live market data and alters output artifacts. Execute live updates only when explicitly requested and authorized by the user.

---

## 3. Authoritative CLI Commands

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

# Run frontend linting, formatting, and type checks
vp check --fix    # Preferred frontend validation (lints, typechecks, auto-formats; modifies source files)

# Run local development server
vp dev

# Build SSG production static site
vp build
```

---

## 4. Agent Execution Principles & Validation

- **Inspect First**: Read relevant code and documentation in `docs/` before making changes.
- **Minimal, Focused Edits**: Make targeted changes satisfying domain contracts. Keep PRs focused.
- **Keep Documentation Synchronized**: Update authoritative files in `docs/` whenever interfaces, behavior, or workflows change.
- **Documentation Validation**:
  - Verify relative Markdown links point to existing target files or valid section anchors.
  - Inspect git diffs to ensure edits do not introduce stale paths or unintended changes.
  - Distinguish prose/link verification from application code checks (`vp check --fix` / `pytest`).
- **Proportional Testing**: For documentation-only changes, skip unnecessary test suite runs. For code edits, run targeted tests during development and execute full test suites when changes are complete.
