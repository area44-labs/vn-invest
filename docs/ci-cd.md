# CI/CD Workflows, Automation & Build Invariants

This document specifies the GitHub Actions workflows, path filtering rules, scheduled market updates, and deployment pipelines in **VN Invest** (`area44-labs/vn-invest`).

---

## 1. GitHub Actions Workflows Summary (`.github/workflows/`)

| Workflow File         | Trigger Events                                                                           | Primary Responsibilities & Path Filters                                                                                                                                                                                                                                                                            |
| :-------------------- | :--------------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`tests.yml`**       | `push` (restricted to `main` branch) / `pull_request` (any branch)                       | Runs backend pytest (`backend-test`) when backend paths change; runs frontend Playwright Vitest (`frontend-test`) when frontend paths change. Note: `uv run --frozen pytest` in CI executes all tests; `@pytest.mark.live` tests are not filtered automatically unless explicitly configured via pytest CLI flags. |
| **`lint-format.yml`** | `push` (restricted to `main` branch) / `pull_request` (any branch)                       | Runs on all pushes to `main` and pull requests **without path filters**.                                                                                                                                                                                                                                           |
| **`update-data.yml`** | `schedule` (`cron: "0 11 * * 1-5"`) / `workflow_dispatch`                                | Scheduled daily EOD market update (11:00 UTC = 18:00 ICT, Mon-Fri). Runs `uv run --frozen python scripts/generate_report.py --update` on `main` and commits updated `generated/` artifacts.                                                                                                                        |
| **`pages.yml`**       | `push` (restricted to `main` branch) / `pull_request` (any branch) / `workflow_dispatch` | Builds static site via Vite+ SSG (`dist/client`). Deployment to GitHub Pages environment.                                                                                                                                                                                                                          |

---

## 2. Authoritative Local Commands Matching CI

To replicate CI checks locally before submitting code:

```bash
# Backend CI Checks
uv sync --frozen
uv run --frozen ruff check --fix scripts    # Auto-fix check (modifies source files)
uv run --frozen ruff format scripts         # Formatting check (modifies source files)
uv run --frozen pytest

# Frontend CI Checks
vp install
pnpm exec playwright install --with-deps chromium
vp check    # Preferred frontend validation (lints, typechecks, auto-formats; modifies source files)
vp test
vp build
```

_Note on Scheduled Data Updates_: `.github/workflows/update-data.yml` executes `uv run --frozen python scripts/generate_report.py --update`. This command fetches external live market data and mutates generated artifacts under `generated/`. **Never run `--update` merely as routine local validation.**
