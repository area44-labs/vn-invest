# Frontend Architecture, SSG Build & Deployment

This document specifies the React static site generation (SSG) frontend architecture, data consumption boundaries, build toolchain, and GitHub Pages deployment in **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Frontend Technology Stack & Toolchain

- **Framework**: React 19 + TanStack Start (SSG Prerendering).
- **Styling**: Tailwind CSS.
- **Build & Lint Standard**: Vite+ (`vp`). All frontend commands use `vp` (`vp install`, `vp check`, `vp build`, `vp dev`).
- **Configuration**: Merged into `vite.config.ts` and `package.json`.

---

## 2. Directory Structure

Frontend source code resides under `src/`.

```text
src/
├── components/      # React UI components (charts, tables, cards, navigation)
├── data/            # Static JSON data loaders and adapters (loader.ts)
├── hooks/           # Custom React hooks for state management and logic
├── lib/             # Utility functions (utils.ts re-exporting cn)
├── pages/           # Page-level components
├── routes/          # TanStack Start file-based routing
├── types/           # TypeScript interface definitions (recommendation.ts, etc.)
└── styles/          # Global Tailwind CSS definitions
```

---

## 3. Frontend / Backend Boundary & Data Consumption

### 3.1 Strict Separation of Concerns

- **Zero Financial Calculations in Frontend**: All quantitative indicators, signal scores, risk metrics, market regimes, and trade plans are pre-computed by the Python Quantitative Engine (`scripts/`) and saved as static JSON payloads in `generated/`.
- **Pure Visualizer**: The frontend acts exclusively as a read-only visualizer displaying pre-calculated data from `generated/`.

### 3.2 Data Loading Mechanics (`src/data/loader.ts`)

- The frontend loads JSON artifacts directly from `generated/` during development or static build prerendering (`dist/client/generated/` in production builds).
- Adapter loader `loader.ts` reads `recommendations.json`, `market.json`, `monitoring.json`, and `history/index.json`.

---

## 4. Build & Deployment Architecture

### 4.1 Development Server

Start local Vite+ development server:

```bash
vp dev
```

### 4.2 Linting & Formatting

Check and autofix frontend code formatting and TypeScript check:

```bash
vp check --fix
```

### 4.3 Production Static Site Generation (SSG) Build

Build static production prerender:

```bash
vp build
```

- Outputs prerendered static HTML, JS, CSS, and copied `generated/*.json` artifacts into `dist/client/`.

### 4.4 Deployment to GitHub Pages

- **GitHub Actions Workflow**: `.github/workflows/pages.yml`.
- Runs `area44/workflows/vite-plus` to compile SSG prerender into `dist/client`.
- Uses `actions/deploy-pages` to deploy `dist/client` to GitHub Pages.
