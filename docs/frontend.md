# Frontend Architecture, SSG Build & UI Standards

This document specifies the React static site generation (SSG) frontend architecture, layer separation boundaries, JSON integration contract, data loading result contract, build toolchain, deployment, and UI standards for **VN Invest** (`area44-labs/vn-invest`).

---

## 1. System Responsibilities & Layer Separation

VN Invest strictly separates quantitative report generation (backend) from presentation and visualization (frontend).

```text
┌─────────────────────────────────────────────────────────────┐
│                 Python Quantitative Backend                 │
│                         (scripts/)                          │
│ Market Data -> Canonical Validation -> Indicators & Signals │
│     -> T+2.5 Risk Models -> Monitoring -> Schema Check      │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               │ Schema-Validated JSON Artifacts
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 Static Artifact Contract                    │
│                        (generated/)                         │
│ recommendations.json / market.json / history/*.json / ...   │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               │ SSG Build (Vite+ Prerender)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                      React SSG Frontend                     │
│                           (src/)                            │
│     TanStack Start -> Data Loaders -> Presentation UI       │
│            -> Interactive Visualizer & Routing              │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               │ Static Site Artifacts
                               ▼
┌─────────────────────────────────────────────────────────────┐
│               GitHub Pages Deployment (dist/client)         │
└─────────────────────────────────────────────────────────────┘
```

### 1.1 Backend Responsibilities (`scripts/`)

- **Market Data Acquisition & Validation**: Fetching OHLCV market data (`VnstockMarketProvider`), price/volume normalization, and temporal consistency checks (`data_as_of`).
- **Quantitative Calculations**: Computing technical indicators (RSI, MACD, MA, Divergence), market regimes, signal recommendation scores, and T+2.5 VaR/ES risk plans.
- **Monitoring & Quality Assurance**: Performing drift detection, symbol accounting, schema compliance checks against `schemas/v2/`, and publishing artifacts atomically.
- **Artifact Generation**: Persisting static JSON payloads in `generated/` (`recommendations.json`, `market.json`, `monitoring.json`, `history/index.json`, `history/{YYYY-MM-DD}.json`).

### 1.2 Frontend Responsibilities (`src/`)

- **Static Page Prerendering**: Building static HTML pages via React 19 and TanStack Start SSG prerendering.
- **Routing & Navigation**: Managing client and static file-based routing (`src/routes/` and `src/pages/`).
- **Data Loading**: Reading pre-rendered JSON artifacts during SSG build or fetching them in browser runtime (`src/data/loader.ts`).
- **Presentation & Visualization**: Rendering stock tables, metric summary cards, modal overlays, and historical report selectors using existing component primitives.
- **User Interactions**: Handling theme switching (light/dark mode), client-side search/filtering, interactive dialogs, and request retry actions.

### 1.3 Non-Negotiable Boundary Rules

- **Zero Financial Calculations**: The frontend must never calculate technical indicators, signal confidence scores, trade plan targets (stop-loss, cut-loss, entry range), or risk metrics.
- **Zero Data Fabrication**: The frontend must never invent missing market data, synthesize missing recommendations, or guess placeholder prices/volumes when artifacts are incomplete.
- **Zero Status Reinterpretation**: The frontend must display backend status codes (`BULLISH`, `BEARISH`, `SIDEWAYS`, `BUY`, `HOLD`, `SELL`, `WATCHLIST`, `WARNING`, `PASS`, `FAIL`) verbatim as provided by the schema-validated artifacts without changing business classification logic.

---

## 2. Integration Contract & Typed Data Loading

### 2.1 Interface & Data Ownership

The `generated/` directory is the single, canonical contract interface between backend and frontend.

- **Data Ownership**: The backend exclusively owns data content, structure, and schema validity. The frontend exclusively owns visual layout, formatting, and DOM composition.
- **Schema Compatibility**: All backend JSON artifacts strictly validate against Draft 2020-12 schemas in `schemas/v2/`. TypeScript type definitions in `src/types/` mirror these JSON schemas.

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
   - Missing file (`ENOENT`): Returns `{ status: "NOT_FOUND" }`.
   - Invalid JSON or file error: Throws an explicit `[SSG Build Error]` halting SSG prerendering immediately.
2. **Browser Runtime Mode**: Fetches JSON assets via HTTP `fetch` relative to `import.meta.env.BASE_URL`:
   - `404 Not Found`: Returns `{ status: "NOT_FOUND" }`.
   - `200 OK` with valid JSON: Returns `{ status: "SUCCESS", data }`.
   - Non-200 HTTP status or invalid JSON: Returns `{ status: "ERROR", error: "..." }`.
   - Network failure or TypeError: Returns `{ status: "ERROR", error: "..." }`.

### 2.3 Race Condition Protection, Component States & Retry Paths

- **Asynchronous Race Protection**: Page components (`src/pages/history.tsx`, `src/pages/stock-detail.tsx`) track cancellation tokens (`isCancelled` flag in `useEffect`) when dates or stock symbols change. Late responses from previous selections are discarded and cannot corrupt current state.
- **State Disambiguation & Recovery**:
  - **Loading State**: Displayed while `LoadResult` is pending when user changes selected date or symbol. State is cleared immediately on selection change to prevent stale views.
  - **Successful Data State**: Rendered when `status === "SUCCESS"`.
  - **Genuinely Missing Data State**: Rendered when `status === "NOT_FOUND"` (e.g., "Không tìm thấy file báo cáo ngày YYYY-MM-DD" or "Không tìm thấy dữ liệu phân tích cho mã 'XYZ'").
  - **Request / Parsing Error State**: Rendered when `status === "ERROR"` (e.g., "Lỗi tải báo cáo: HTTP 500"). **Network or parsing errors must never be presented as "not found".** An interactive **"Thử lại"** button allows users to retry and recover cleanly.
- **Dashboard Synchronization**: Dashboard re-fetches both `loadRecommendationsResult()` and `loadMarketResult()` on retry to ensure complete data recovery.
- **Warning Banners**: Freshness warnings or status flags present in valid backend payloads (such as `source_date` age checks in `src/pages/dashboard.tsx`) render inline warning banners without blocking page rendering.

---

## 3. Technology Stack & Project Configuration

The project configuration and dependencies in `package.json` and `components.json` serve as the source of truth for the frontend setup.

### 3.1 Technology Stack

- **Framework**: React 19 (`react`, `react-dom`) + TanStack Start (`@tanstack/react-start`, `@tanstack/react-router`).
- **UI Components**: Primitives built using shadcn/ui standards over `@base-ui/react` and `class-variance-authority` (`cva`).
- **Styling & CSS Engine**: Tailwind CSS v4 (`tailwindcss`, `@tailwindcss/vite`, `tw-animate-css`).
- **Icons**: Lucide React (`lucide-react`).
- **Typography**: Geist Sans and Geist Mono variable fonts (`@fontsource-variable/geist`, `@fontsource-variable/geist-mono`).
- **Build & Test Toolchain**: Vite+ (`vite-plus`, `vp`), embedded Vitest, and `@vitest/browser-playwright` with Playwright Chromium.

### 3.2 Key Configuration Files

- **`components.json`**: shadcn CLI configuration (`style: "base-nova"`, `tailwind.css: "src/styles/index.css"`, aliases for `@/components`, `@/components/ui`, `@/lib`, `@/hooks`).
- **`package.json`**: Package dependencies and scripts (`vp dev`, `vp build`, `vp check`, `vp fmt`, `vp test`).
- **`vite.config.ts`**: Merged build and test configuration integrating TanStack Start, `@tailwindcss/vite`, and `@vitest/browser-playwright`.
- **`src/styles/index.css`**: Design tokens, CSS variables, theme definitions, and `@theme inline` mappings.

---

## 4. UI Design Standards & Component Hierarchy

### 4.1 File Naming & Component Architecture

**File Naming Rule**: All frontend source files under `src/` (pages, components, hooks, utilities, tests, styles) MUST use `kebab-case` filenames (`ten-file.tsx`), e.g., `src/pages/dashboard.tsx`, `src/pages/history.tsx`, `src/pages/stock-detail.tsx`, `src/components/market-summary.tsx`. React component exported identifiers remain `PascalCase` (`export function StockDetail()`).

To maintain consistency and avoid unnecessary complexity:

1. **Primitive Components (`src/components/ui/`)**: Lightweight, reusable UI primitives (`button.tsx`, `badge.tsx`, `card.tsx`, `dialog.tsx`, `table.tsx`, `tabs.tsx`, `tooltip.tsx`, `select.tsx`, `input.tsx`, `dropdown-menu.tsx`).
2. **Domain UI Components (`src/components/`)**: Composite financial components built from primitives (`market-summary.tsx`, `stock-table.tsx`, `recommendation-card.tsx`, `stock-detail-modal.tsx`, `header.tsx`).
3. **Page Views (`src/pages/` & `src/routes/`)**: Top-level page composition and routing (`dashboard.tsx`, `history.tsx`, `methodology.tsx`, `stock-detail.tsx`).

### 4.2 Styling & Tokens

- **Semantic CSS Variables**: Use theme variables defined in `src/styles/index.css` (e.g., `bg-background`, `text-foreground`, `border-border`, `bg-card`, `bg-muted`).
- **Financial Trend Tokens (OKLCH)**:
  - Bullish / Up Trend: `bg-[var(--trend-up-bg)]`, `text-[var(--trend-up-text)]`, `border-[var(--trend-up-border)]` (or `Badge` variant `success`).
  - Bearish / Down Trend: `bg-[var(--trend-down-bg)]`, `text-[var(--trend-down-text)]`, `border-[var(--trend-down-border)]` (or `Badge` variant `destructive`).
  - Warning / Caution: `bg-[var(--warning-bg)]`, `text-[var(--warning-text)]`, `border-[var(--warning-border)]` (or `Badge` variant `warning`).
- **Typography**:
  - General text & headings: `font-sans` (Geist Variable).
  - Tickers, prices, & financial numbers: `font-mono` (Geist Mono Variable).
- **Class Merging**: Use `cn()` from `@/lib/utils` to merge Tailwind classes cleanly.

### 4.3 Market Metric Formatting Rules

- **VN-INDEX Card**: Displays index value, `vnindex_change_pct` percentage change with trend arrows/colors, and volume ratio.
- **Market Regime & Confidence Card**: Displays regime status string/score, and confidence percentage (`Độ tin cậy 85%`) formatted with neutral secondary badge styling. **Confidence is never presented as a price change.**
- **Market Breadth Card**: Displays market breadth percentage (`24.0%`) with neutral outline badge styling. **Breadth ratio is never presented as a price change.**

---

## 5. Development Commands, Testing & CI/CD Deployment

### 5.1 Authoritative Vite+ Commands

Use Vite+ (`vp`) for all frontend operations. Component tests run in real browser mode (Playwright Headless Chromium) via `vite-plus/test`:

```bash
# Install dependencies & Playwright browser binaries
vp install && pnpm exec playwright install chromium

# Execute frontend unit and regression test suite in real browser mode
vp test

# Check linter, TypeScript types, and code formatting
vp check

# Automatically fix linting and formatting issues
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
