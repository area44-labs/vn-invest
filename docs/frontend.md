# Frontend Architecture, SSG Build & shadcn/ui Design Standards

This document specifies the React static site generation (SSG) frontend architecture, frontend/backend separation boundaries, JSON integration contract, build toolchain, and shadcn/ui design standards for **VN Invest** (`area44-labs/vn-invest`).

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
│ TanStack Start -> Data Loaders -> shadcn/ui Components      │
│            -> Interactive Visualizer & Routing              │
└─────────────────────────────────────────────────────────────┘
```

### 1.1 Backend Responsibilities (`scripts/`)

- **Market Data Acquisition & Normalization**: Fetching OHLCV data from sources (`VnstockMarketProvider`), price/volume unit normalization, and temporal consistency checks (`data_as_of`).
- **Quantitative Calculations**: Computing technical indicators (RSI, MACD, MA, Divergence), market regimes, signal recommendation scores, and T+2.5 VaR/ES risk plans.
- **Data Integrity & Monitoring**: Performing drift detection, symbol accounting, schema compliance checks against `schemas/v2/`, and publishing artifacts atomically.
- **Artifact Generation**: Persisting static JSON payloads in `generated/` (`recommendations.json`, `market.json`, `monitoring.json`, `history/index.json`, `history/{YYYY-MM-DD}.json`).

### 1.2 Frontend Responsibilities (`src/`)

- **Static Page Prerendering**: Building static HTML pages via React 19 and TanStack Start SSG prerendering.
- **Routing & Navigation**: Managing client and static file-based routing (`src/routes/` and `src/pages/`).
- **Data Loading**: Reading pre-rendered JSON artifacts during SSG build or fetching them in browser runtime (`src/data/loader.ts`).
- **Data Visualization & Presentation**: Rendering tables, metric summary cards, modal overlays, and historical report selectors using shadcn/ui primitives.
- **User Experience**: Handling theme switching (light/dark mode), client-side search/filtering, and interactive modal dialogs.

### 1.3 Non-Negotiable Boundary Rules

- **Zero Financial Calculations**: The frontend must never calculate technical indicators, signal confidence scores, trade plan targets (stop-loss, cut-loss, entry range), or risk metrics.
- **Zero Data Fabrication**: The frontend must never invent missing market data, synthesize missing recommendations, or guess placeholder prices/volumes when artifacts are incomplete.
- **Zero Status Reinterpretation**: The frontend must display backend status codes (`BULLISH`, `BEARISH`, `SIDEWAYS`, `BUY`, `HOLD`, `SELL`, `WATCHLIST`, `WARNING`, `PASS`, `FAIL`) verbatim as provided by the schema-validated artifacts without changing business classification logic.

---

## 2. Integration Contract & Data Flow

### 2.1 Interface & Data Ownership

The `generated/` directory is the single, canonical contract interface between backend and frontend.

- **Data Ownership**: The backend exclusively owns data content, structure, and schema validity. The frontend exclusively owns visual layout, formatting, and DOM composition.
- **Schema Compatibility**: All backend JSON artifacts strictly validate against Draft 2020-12 schemas in `schemas/v2/`. TypeScript type definitions in `src/types/` must mirror these JSON schemas.

### 2.2 Data Loading Mechanics (`src/data/loader.ts`)

Data is loaded using dual-mode resolution:

1. **SSG Prerender Mode (Node.js)**: Uses `node:fs/promises` to directly read static files from disk (`generated/*.json`). If a required artifact is missing or invalid during build, the SSG build fails fast with an explicit error.
2. **Browser Runtime Mode**: Uses HTTP `fetch` to load relative JSON assets relative to `import.meta.env.BASE_URL` (`dist/client/generated/*.json`).

### 2.3 Handling Error, Empty, and Warning States

- **Loading States**: Display skeleton loaders or spinner indicators during asynchronous data resolution.
- **Empty / Incomplete Data**: When recommendations or market summaries contain empty lists, display explicit, user-friendly empty state banners (e.g., "No stock recommendations available for this market session").
- **Data Freshness & Warning Banners**: If backend operational monitoring outputs `WARNING` status or data lag in `market.json` / `monitoring.json`, display a non-blocking warning notification to notify users without failing UI rendering.
- **Missing / Fatal Artifact Failure**: If an artifact fails to load, present a structured fallback error UI instead of breaking client navigation or throwing uncaught React errors.

---

## 3. Frontend Technology Stack & Configuration

The project configuration and dependencies serve as the single source of truth for the frontend architecture.

### 3.1 Technology Stack

- **Framework**: React 19 (`react`, `react-dom`) + TanStack Start (`@tanstack/react-start`, `@tanstack/react-router`).
- **UI Component Base**: shadcn/ui primitive architecture configured with `@base-ui/react` primitives and `class-variance-authority` (`cva`).
- **Styling & CSS Engine**: Tailwind CSS v4 (`tailwindcss`, `@tailwindcss/vite`, `tw-animate-css`).
- **Icons**: Lucide React (`lucide-react`).
- **Typography**: Geist Sans and Geist Mono variable fonts (`@fontsource-variable/geist`, `@fontsource-variable/geist-mono`).
- **Build Toolchain**: Vite+ (`vite-plus`, `vp`).

### 3.2 Key Configuration Files

- **`components.json`**: Authoritative shadcn/ui CLI configuration (`style: "base-nova"`, `tailwind.css: "src/styles/index.css"`, aliases pointing to `@/components`, `@/components/ui`, `@/lib`, `@/hooks`).
- **`package.json`**: Package dependencies and standard scripts (`vp dev`, `vp build`, `vp check`, `vp fmt`).
- **`vite.config.ts`**: Merged build configuration integrating TanStack Start and `@tailwindcss/vite`.
- **`src/styles/index.css`**: CSS variables, OKLCH design tokens, theme definitions, and `@theme inline` mappings.

---

## 4. shadcn/ui Design Standards

VN Invest adopts **shadcn/ui** as the mandatory component standard for all UI development.

### 4.1 Component Selection & Hierarchy

To maintain visual consistency and avoid code duplication:

1. **Primitive Layer (`src/components/ui/`)**: Low-level, generic, accessible primitives generated via `shadcn` CLI or adapted to the Base UI foundation (e.g., `button.tsx`, `badge.tsx`, `card.tsx`, `dialog.tsx`, `table.tsx`, `tabs.tsx`, `tooltip.tsx`, `select.tsx`, `input.tsx`, `dropdown-menu.tsx`).
2. **Domain UI Layer (`src/components/`)**: Reusable composite financial components built from primitive components (e.g., `market-summary.tsx`, `stock-table.tsx`, `recommendation-card.tsx`, `stock-detail-modal.tsx`, `header.tsx`).
3. **Page Composition Layer (`src/pages/` & `src/routes/`)**: View routing and top-level layout composition.

**Rule**: Always inspect and reuse existing primitives in `src/components/ui/` before introducing custom UI elements. Avoid installing parallel UI component libraries.

### 4.2 Design Tokens & Styling Conventions

- **Design System Tokens**: Use semantic CSS variables defined in `src/styles/index.css` (e.g., `bg-background`, `text-foreground`, `border-border`, `bg-card`, `bg-muted`, `text-muted-foreground`).
- **Financial Trend Colors (OKLCH)**:
  - Bullish / Up Trend: `bg-[var(--trend-up-bg)]`, `text-[var(--trend-up-text)]`, `border-[var(--trend-up-border)]` (or `Badge` variant `success`).
  - Bearish / Down Trend: `bg-[var(--trend-down-bg)]`, `text-[var(--trend-down-text)]`, `border-[var(--trend-down-border)]` (or `Badge` variant `destructive`).
  - Warning / Caution: `bg-[var(--warning-bg)]`, `text-[var(--warning-text)]`, `border-[var(--warning-border)]` (or `Badge` variant `warning`).
- **Typography & Font Stacks**:
  - Sans-serif / Headings: `font-sans` (Geist Variable).
  - Numeric / Financial Data / Tickers: `font-mono` (Geist Mono Variable) for tabular numbers and precise alignment.
- **Utility Function**: Combine class names exclusively using `cn()` from `@/lib/utils` (re-exporting `clsx` and `tailwind-merge`).

### 4.3 Accessibility & Responsiveness

- **Keyboard Navigation & Focus**: All interactive controls (`Button`, `Dialog`, `Select`, `Tabs`) must support full keyboard accessibility and visible focus rings (`focus-visible:ring-ring`).
- **Responsive Layouts**: Design for fluid responsiveness across screen widths (mobile, tablet, desktop) using standard Tailwind breakpoints (`sm:`, `md:`, `lg:`, `xl:`).
- **Dark Mode Support**: Ensure dark mode contrast compliance via `.dark` CSS variable overrides in `src/styles/index.css`.

---

## 5. Frontend Development Commands

Use Vite+ (`vp`) for all frontend operations:

```bash
# Install dependencies
vp install

# Check linter, TypeScript types, and code formatting
vp check

# Automatically fix linting and formatting issues
vp check --fix

# Start local development server
vp dev

# Build static production prerender (SSG)
vp build
```
