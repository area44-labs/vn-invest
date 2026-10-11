# CI/CD Workflows, Automation & Build Invariants

This document specifies the GitHub Actions workflows, path filtering rules, scheduled market updates, and deployment pipelines in **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Purpose & When to Consult

Consult this document when inspecting CI build behavior, modifying `.github/workflows/`, investigating workflow failures, or configuring deployment rules.

---

## 2. GitHub Actions Workflows Summary (`.github/workflows/`)

| Workflow File         | Trigger Events                                          | Primary Responsibilities & Path Filters                                                                                                                                                                                               |
| :-------------------- | :------------------------------------------------------ | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **`tests.yml`**       | `push` / `pull_request` on `main`                       | Runs backend pytest (`backend-test`) when `*.py`, `pyproject.toml`, `uv.lock`, or `pytest.ini` change; runs frontend Playwright Vitest (`frontend-test`) when `src/**`, `package.json`, `pnpm-lock.yaml`, or `vite.config.ts` change. |
| **`lint-format.yml`** | `push` / `pull_request` on `main`                       | Runs `ruff check --fix` and `ruff format` on `scripts/`, plus Vite+ lint/format checks on frontend.                                                                                                                                   |
| **`update-data.yml`** | `cron: "0 11 * * 1-5"` / `workflow_dispatch`            | Scheduled daily EOD market update (11:00 UTC = 18:00 ICT, Mon-Fri). Runs `python scripts/generate_report.py --update` and commits updated `generated/` artifacts.                                                                     |
| **`pages.yml`**       | `push` on `main` / `pull_request` / `workflow_dispatch` | Builds static site via Vite+ SSG (`dist/client`) and deploys to GitHub Pages upon push to `main`.                                                                                                                                     |

---

## 3. Playwright & Frontend Environment Setup

The `frontend-test` job in `.github/workflows/tests.yml` installs Playwright Chromium and system dependencies using:

```bash
pnpm exec playwright install --with-deps chromium
```

Vitest browser tests run headless Chromium via `@vitest/browser-playwright` as configured in `vite.config.ts`.

---

## 4. Authoritative Local Commands Matching CI

To replicate CI checks locally before submitting code:

```bash
# Backend CI Check
uv sync --frozen
uv run --frozen ruff check scripts
uv run --frozen pytest

# Frontend CI Check
vp install
pnpm exec playwright install --with-deps chromium
vp check
vp test
vp build
```
