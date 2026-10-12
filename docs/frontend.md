# Frontend SSG Architecture, Routing & UI Standards

This document specifies the React static site generation (SSG) frontend architecture, typed data loader contracts, UI component standards, accessibility guidelines, and build tools in **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Frontend Responsibilities & Non-Negotiable Boundaries

- **Static Page Prerendering**: HTML pages are prerendered at build time using React 19 and TanStack Start SSG (`@tanstack/react-start`).
- **Read-Only Visualizer**: Frontend code under `src/` consumes pre-rendered static JSON artifacts from `generated/`.
- **Zero Financial Calculations**: The frontend must never compute technical indicators, signal confidence scores, trade plan targets (stop-loss, cut-loss, entry range), or risk metrics.
- **Zero Data Fabrication**: The frontend must never invent missing market data, synthesize missing recommendations, or guess placeholder prices/volumes when artifacts are incomplete.
- **Verbatim Status Codes**: Display backend status strings (`STRONG_BULL`, `BULL`, `DEFENSIVE`, `BEAR`, `PANIC`, `BUY`, `HOLD`, `SELL`, `WATCHLIST`, `WARNING`, `PASS`, `FAIL`) verbatim as supplied by schema-validated payloads without reinterpreting business logic.

---

## 2. Integration Contract & Typed Data Loading

### 2.1 Interface & Data Ownership

The `generated/` directory is the single, canonical contract interface between backend and frontend.

- **Data Ownership**: The backend exclusively owns data content, structure, and contract validity. The frontend exclusively owns visual layout, formatting, and DOM composition.
- **Schema Compatibility & Market Regime Contract**:
  - Primary recommendation and performance payloads (`recommendations.json`, `performance.json`, `history/YYYY-MM-DD.json`) strictly validate against Draft 2020-12 JSON Schemas in `schemas/v2/`. Non-schema-governed artifacts (`market.json`, `monitoring.json`, `provenance.json`, `history/index.json`) validate against their respective internal dictionary contracts in `scripts/pipeline/validation.py`, `scripts/artifacts/`, and `scripts/monitoring/`.
  - TypeScript type definitions in `src/types/` mirror the relevant frontend data contracts consumed by typed loaders (`src/data/loader.ts`).
  - **Market Regime Enum Contract**: The active market regimes supported by the frontend validator (`src/data/loader.ts`) and TypeScript definitions (`src/types/recommendation.ts`) are `STRONG_BULL`, `BULL`, `DEFENSIVE`, `BEAR`, and `PANIC`.
  - _Note on Backend/Frontend Alignment_: While `NEUTRAL` is defined in backend `QuantConfig` for planned future support, it is currently excluded from `VALID_MARKET_REGIMES` in `src/data/loader.ts`. Payloads containing `NEUTRAL` will trigger a validation error in the frontend.

### 2.2 Typed Loader Contract (`src/data/loader.ts`)

Data fetching functions in `src/data/loader.ts` return a typed `LoadResult<T>` sum type to cleanly separate successful payloads, genuinely missing resources (404 / ENOENT), and network or JSON parsing failures:

```typescript
export type LoadResult<T> =
  | { status: "SUCCESS"; data: T }
  | { status: "NOT_FOUND" }
  | { status: "ERROR"; error: string };
```

Data resolution mechanics:

1. **SSG Prerender Mode (Node.js)**: Reads static files directly from disk (`generated/*.json`) via `node:fs/promises`.
   - Missing required file (e.g. `recommendations.json`): Throws an explicit build error (`ENOENT`) halting SSG build.
   - Missing optional artifact (`optional: true`, e.g. `market.json`): Returns `{ status: "NOT_FOUND" }` gracefully.
2. **Browser Runtime Mode**: Fetches JSON assets via HTTP `fetch` relative to `import.meta.env.BASE_URL`:
   - `404 Not Found`: Returns `{ status: "NOT_FOUND" }`.
   - `200 OK` with valid JSON: Returns `{ status: "SUCCESS", data }`.
   - Non-200 HTTP status, network failure, or invalid JSON: Returns `{ status: "ERROR", error: "..." }`.

### 2.3 Race Condition Protection, Component States & Retry Paths

- **Asynchronous Race Protection**: Page components (e.g. `src/pages/history.tsx`, `src/pages/stock-detail.tsx`) track cancellation tokens or `useRef` request tokens when dates or stock symbols change. Late responses from previous selections are discarded and cannot corrupt current view state.
- **State Disambiguation & Recovery**:
  - **Loading State**: Displayed while `LoadResult` is pending when user changes selected date or symbol. State is cleared immediately on selection change to prevent stale views.
  - **Successful Data State**: Rendered when `status === "SUCCESS"`.
  - **Genuinely Missing Data State**: Rendered when `status === "NOT_FOUND"` (e.g., missing historical report or unknown stock symbol).
  - **Request / Parsing Error State**: Rendered when `status === "ERROR"`. **Network or parsing errors must never be presented as "not found".** An interactive retry button allows users to re-fetch and recover cleanly.
- **Dashboard Synchronization**: Dashboard re-fetches both recommendations and market data on retry to ensure complete recovery.
- **Warning Banners**: Freshness warnings or fallback notifications present in valid backend payloads render explicit inline warning banners without blocking page rendering.

---

## 3. Technology Stack & Project Configuration

The project configuration and dependencies in `package.json` serve as the source of truth for the frontend setup.

### 3.1 Technology Stack

- **Framework**: React 19 (`react`, `react-dom`) + TanStack Start (`@tanstack/react-start`, `@tanstack/react-router`).
- **UI Components**: Primitives built using shadcn/ui standards over `@base-ui/react` and `class-variance-authority` (`cva`).
- **Styling & CSS Engine**: Tailwind CSS v4 (`tailwindcss`, `@tailwindcss/vite`, `tw-animate-css`).
- **Icons**: Lucide React (`lucide-react`).
- **Typography**: Geist Sans and Geist Mono variable fonts (`@fontsource-variable/geist`, `@fontsource-variable/geist-mono`).
- **Build & Test Toolchain**: Vite+ (`vite-plus`, `vp`), embedded Vitest, and `@vitest/browser-playwright` with Playwright Chromium.

### 3.2 Key Configuration Files

- **`package.json`**: Package dependencies and scripts (`vp dev`, `vp build`, `vp check`, `vp check --fix`, `vp test`).
- **`vite.config.ts`**: Merged build and test configuration integrating TanStack Start, `@tailwindcss/vite`, and `@vitest/browser-playwright`.
- **`src/styles/index.css`**: Design tokens, CSS variables, theme definitions, and `@theme inline` mappings.

---

## 4. UI Design Standards, Accessibility & Component Hierarchy

### 4.1 File Naming & Component Architecture

**File Naming Rule**: All frontend source files under `src/` (pages, components, hooks, utilities, tests, styles) MUST use `kebab-case` filenames (e.g., `src/pages/dashboard.tsx`). React component exported identifiers remain `PascalCase` (e.g. `export function StockDetail()`).

To maintain consistency and avoid unnecessary complexity:

1. **Primitive Components (`src/components/ui/`)**: Lightweight, reusable UI primitives (`button.tsx`, `badge.tsx`, `card.tsx`, `dialog.tsx`, `table.tsx`, `tabs.tsx`, `tooltip.tsx`, `select.tsx`, `input.tsx`, `dropdown-menu.tsx`).
2. **Domain UI Components (`src/components/`)**: Composite financial components built from primitives (`market-summary.tsx`, `stock-table.tsx`, `recommendation-card.tsx`, `stock-detail-modal.tsx`, `header.tsx`).
3. **Page Views (`src/pages/` & `src/routes/`)**: Top-level page composition and routing.

### 4.2 Accessibility & Responsive Behavior

- **Semantic HTML**: Structural layout uses semantic tags (`<header>`, `<nav>`, `<main>`, `<section>`, `<article>`, `<footer>`).
- **Keyboard Navigation**: Interactive elements (such as stock table rows wrapped in TanStack Router `<Link>`) support keyboard navigation and standard web accessibility expectations.
- **Focus Rings**: All interactive controls feature visible focus indicators (`focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring`).
- **Responsive Layouts**: Content scales cleanly across mobile, tablet, and desktop viewports using flex wrapping and scrollable table wrappers (`overflow-x-auto`).

### 4.3 Styling & Tokens

- **Semantic CSS Variables**: Use theme variables defined in `src/styles/index.css` (e.g., `bg-background`, `text-foreground`, `border-border`, `bg-card`, `bg-muted`).
- **Financial Trend Tokens (OKLCH)**:
  - Bullish / Up Trend: `bg-[var(--trend-up-bg)]`, `text-[var(--trend-up-text)]`, `border-[var(--trend-up-border)]` (or `Badge` variant `success`).
  - Bearish / Down Trend: `bg-[var(--trend-down-bg)]`, `text-[var(--trend-down-text)]`, `border-[var(--trend-down-border)]` (or `Badge` variant `destructive`).
  - Warning / Caution: `bg-[var(--warning-bg)]`, `text-[var(--warning-text)]`, `border-[var(--warning-border)]` (or `Badge` variant `warning`).
- **Typography**:
  - General text & headings: `font-sans` (Geist Variable).
  - Tickers, prices, & financial numbers: `font-mono` (Geist Mono Variable).
- **Class Merging**: Use `cn()` from `@/lib/utils` to merge Tailwind classes cleanly.

### 4.4 Market Metric Formatting Rules

- **VN-INDEX Card**: Displays index value, `vnindex_change_pct` percentage change with trend arrows/colors, and volume ratio.
- **Market Regime & Confidence Card**: Displays regime status string/score, and confidence percentage (`Độ tin cậy 85%`) formatted with neutral secondary badge styling. **Confidence is never presented as a price change.**
- **Market Breadth Card**: Displays market breadth percentage (`24.0%`) with neutral outline badge styling. **Breadth ratio is never presented as a price change.**

---

## 5. Development Commands, Testing & CI/CD Deployment

### 5.1 Authoritative Vite+ Commands

Use Vite+ (`vp`) for all frontend operations. Component tests run in real browser mode (Playwright Headless Chromium) via `vite-plus/test`:

```bash
# Install dependencies & Playwright browser binaries
vp install && pnpm exec playwright install --with-deps chromium

# Execute frontend unit and regression test suite in real browser mode
vp test

# Check linter, TypeScript types, and code formatting (non-mutating)
vp check

# Auto-fix linting and formatting issues (modifies source files)
vp check --fix

# Start local development server
vp dev

# Build static production prerender (SSG)
vp build
```

### 5.2 GitHub Pages Deployment Architecture

The frontend static site is automatically built and deployed via GitHub Actions:

- **Workflow File**: `.github/workflows/pages.yml`.
- **Triggers**: Automated build and deployment on push to `main`, pull request checks, or manual `workflow_dispatch`.
- **Build Execution**: Uses action `area44/workflows/vite-plus` to execute `vp build`, outputting prerendered static assets and copied JSON data into `dist/client`.
- **Deployment**: Uses `actions/deploy-pages` to publish the static contents of `dist/client` to GitHub Pages.
