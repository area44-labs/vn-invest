# CI/CD Workflows, Automation & Build Invariants

This document specifies the GitHub Actions workflows, automated scheduled pipeline jobs, testing triggers, and CI invariants in **VN Invest** (`area44-labs/vn-invest`).

---

## 1. GitHub Actions Workflows Overview (`.github/workflows/`)

The repository includes four primary GitHub Actions workflows:

| Workflow File         | Trigger Events                                            | Primary Responsibilities                                                                        |
| :-------------------- | :-------------------------------------------------------- | :---------------------------------------------------------------------------------------------- |
| **`tests.yml`**       | `push` / `pull_request` on `main`                         | Python backend test suite execution (`uv run --frozen pytest`) with conditional path detection. |
| **`lint-format.yml`** | `push` / `pull_request` on `main`                         | Python autofix/formatting (`ruff check --fix` / `ruff format`) and Vite+ check.                 |
| **`update-data.yml`** | `schedule` (`cron: "0 11 * * 1-5"`) / `workflow_dispatch` | Scheduled EOD market data update and daily report regeneration.                                 |
| **`pages.yml`**       | `push` on `main` / `pull_request` / `workflow_dispatch`   | SSG prerender build via Vite+ and deployment to GitHub Pages.                                   |

---

## 2. Detailed Breakdown of Workflows

### 2.1 Python Test Suite Workflow (`tests.yml`)

- **Environment**: `ubuntu-latest`, Python 3.14, managed via `astral-sh/setup-uv@v10`.
- **Timeout**: `timeout-minutes: 10` for test job.
- **Conditional Job Execution (`dorny/paths-filter`)**:
  - Permissions: `contents: read`, `pull-requests: read`.
  - Uses `dorny/paths-filter@ceb8a2b8f2d89434be7ff52d3de7ec3738c5cc9d` (# v4.0.3) in a `changes` job to inspect modified files against `**/*.py`, `pyproject.toml`, `uv.lock`, `pytest.ini`, and `.github/workflows/tests.yml`.
  - Executes the `test` job (`actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1` # v7.0.1, `uv sync --frozen` & `uv run --frozen pytest`) conditionally when Python code, dependencies, or test configurations change.
  - Skips the `test` job cleanly for documentation-only changes.

### 2.2 Linting & Formatting Workflow (`lint-format.yml`)

- **Environment**: `ubuntu-latest`.
- **Python Step**:
  ```bash
  ruff check --fix scripts
  ruff format scripts
  ```
- **Frontend Step**: Uses `area44/workflows/lint-format` for Vite+ checks.

### 2.3 Daily Scheduled EOD Market Update (`update-data.yml`)

- **Schedule**: `cron: "0 11 * * 1-5"` (11:00 UTC = 18:00 ICT, Mon–Fri, following HOSE/HNX/UPCoM market close).
- **Execution Command**:
  ```bash
  uv run --frozen python scripts/generate_report.py --update
  ```
- **Commit & Push Step**:
  - Checks `git status --porcelain generated/`.
  - If new data was generated, commits updated `generated/` artifacts with message `chore(data): update daily market recommendations` and pushes to `main`.
- **Fail-Closed Invariant**: If market data acquisition fails or is incomplete, `generate_report.py --update` exits code 1, halting the workflow and preserving existing on-disk report artifacts without pushing corrupt updates.

### 2.4 GitHub Pages SSG Deployment (`pages.yml`)

- **Build Step**: Executes `area44/workflows/vite-plus` outputting static SSG files to `dist/client`.
- **Deploy Step**: Deploys `dist/client` to GitHub Pages environment.

---

## 3. Essential CI Commands Standard

All local development and CI steps must use these exact commands:

```bash
# Backend Dependencies & Testing
uv sync --frozen
uv run --frozen pytest

# Backend Formatting & Linting
uv run --frozen ruff check --fix scripts
uv run --frozen ruff format scripts

# Frontend Development & SSG Prerender
vp install
vp check --fix
vp build
```
