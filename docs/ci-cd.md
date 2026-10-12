# CI/CD Workflows, Automation & Build Invariants

This document specifies the GitHub Actions workflows, path filtering rules, scheduled market updates, and deployment pipelines in **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Purpose & When to Consult

Consult this document when inspecting CI build behavior, modifying `.github/workflows/`, investigating workflow failures, or configuring deployment rules. Refer to [`docs/testing.md`](testing.md) for testing commands and guidelines.

---

## 2. GitHub Actions Workflows Summary (`.github/workflows/`)

| Workflow File         | Trigger Events                                                                           | Primary Responsibilities & Path Filters                                                                                                                                                                                                                                                                                                                               |
| :-------------------- | :--------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`tests.yml`**       | `push` (restricted to `main` branch) / `pull_request` (any branch)                       | Runs backend pytest (`backend-test`) when backend paths change (`**/*.py`, `pyproject.toml`, `uv.lock`, `pytest.ini`, `.github/workflows/tests.yml`); runs frontend Playwright Vitest (`frontend-test`) when frontend paths change (`src/**`, `package.json`, `pnpm-lock.yaml`, `vite.config.ts`, `tsconfig.json`, `components.json`, `.github/workflows/tests.yml`). |
| **`lint-format.yml`** | `push` (restricted to `main` branch) / `pull_request` (any branch)                       | Runs on all pushes to `main` and pull requests **without path filters**. Executes Python Ruff (`ruff check --fix scripts` & `ruff format scripts`) and Vite+ lint/format action (`area44/workflows/lint-format`).                                                                                                                                                     |
| **`update-data.yml`** | `schedule` (`cron: "0 11 * * 1-5"`) / `workflow_dispatch`                                | Scheduled daily EOD market update (11:00 UTC = 18:00 ICT, Mon-Fri). Runs `python scripts/generate_report.py --update` on `main` and commits updated `generated/` artifacts.                                                                                                                                                                                           |
| **`pages.yml`**       | `push` (restricted to `main` branch) / `pull_request` (any branch) / `workflow_dispatch` | Builds static site via Vite+ SSG (`dist/client`). Deployment to GitHub Pages environment occurs **strictly on push to `main`** (`if: github.ref == 'refs/heads/main'`).                                                                                                                                                                                               |

---

## 3. Playwright & Frontend Environment Setup

The `frontend-test` job in `.github/workflows/tests.yml` sets up Vite+ via `voidzero-dev/setup-vp@v1` and installs Playwright Chromium and system dependencies using:

```bash
pnpm exec playwright install --with-deps chromium
```

Vitest browser tests run headless Chromium via `@vitest/browser-playwright` as configured in `vite.config.ts`.

---

## 4. Authoritative Local Commands Matching CI

To replicate CI checks locally before submitting code:

```bash
# Backend CI Checks
uv sync --frozen
uv run --frozen ruff check --fix scripts
uv run --frozen ruff format scripts
uv run --frozen pytest

# Frontend CI Checks
vp install
pnpm exec playwright install --with-deps chromium
vp check
vp test
vp build
```
