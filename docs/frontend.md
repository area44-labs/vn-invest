# Frontend SSG Architecture, Routing & UI Standards

This document specifies the React static site generation (SSG) frontend architecture, typed data loader contracts, UI component standards, accessibility guidelines, and build tools in **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Frontend Responsibilities & Non-Negotiable Boundaries

- **Static Page Prerendering**: HTML pages are prerendered at build time using React 19 and TanStack Start SSG (`@tanstack/react-start`).
- **Read-Only Visualizer**: Frontend code under `src/` consumes pre-rendered static JSON artifacts from `generated/`.
- **Zero Financial Calculations**: The frontend must never compute technical indicators, signal confidence scores, trade plan targets, or risk metrics.
- **Verbatim Status Codes**: Display backend status strings (`STRONG_BULL`, `BULL`, `NEUTRAL`, `DEFENSIVE`, `BEAR`, `PANIC`, `BUY`, `HOLD`, `SELL`, `WATCHLIST`, `WARNING`, `PASS`, `FAIL`) verbatim as supplied by schema-validated payloads without reinterpreting business logic.

---

## 2. Typed Data Loader Contract (`src/data/loader.ts`)

Data fetching functions return a typed `LoadResult<T>` sum type to cleanly separate success from missing resources and errors:

```typescript
export type LoadResult<T> =
  | { status: "SUCCESS"; data: T }
  | { status: "NOT_FOUND" }
  | { status: "ERROR"; error: string };
```

- **SSG Prerender Mode (Node.js)**: Reads `generated/*.json` directly via `node:fs/promises`.
- **Browser Runtime Mode**: Fetches JSON assets via HTTP `fetch` relative to `import.meta.env.BASE_URL`. Returns `NOT_FOUND` on 404, `SUCCESS` on 200 with valid JSON, and `ERROR` on non-200 or parsing error.
- **Race Condition Protection**: Page components (`src/pages/history.tsx`, `src/pages/stock-detail.tsx`) use `useRef` tokens or cancellation flags in `useEffect` to discard out-of-order asynchronous responses from superseded symbol/date selections.

---

## 3. Technology Stack

- **Framework**: React 19 + TanStack Start (`@tanstack/react-start`, `@tanstack/react-router`).
- **UI Component Primitives**: Primitives in `src/components/ui/` built using shadcn/ui standards over `@base-ui/react` and `class-variance-authority` (`cva`).
- **Styling**: Tailwind CSS v4 (`tailwindcss`, `@tailwindcss/vite`).
- **Toolchain**: Vite+ (`vite-plus`, `vp`), embedded Vitest, and `@vitest/browser-playwright`. See [`naming.md`](naming.md) for canonical file and identifier naming rules.

---

## 4. UI Accessibility & Design Standards

- **Semantic HTML**: Use structural layout tags (`<header>`, `<nav>`, `<main>`, `<section>`, `<footer>`).
- **Keyboard Navigation**: Interactive controls and stock table rows support keyboard events (`Enter`, `Space`, `role="button"`, `tabIndex={0}`).
- **Focus Rings**: Use visible focus ring styles (`focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring`).
- **Financial Trend Tokens**: Use semantic design tokens in `src/styles/index.css` (`bg-[var(--trend-up-bg)]`, `bg-[var(--trend-down-bg)]`, `bg-[var(--warning-bg)]`).
- **Font Standards**: Use `font-sans` (Geist Variable) for body text and `font-mono` (Geist Mono Variable) for financial numbers, tickers, and prices.

---

## 5. Authoritative Development Commands

See [`testing.md`](testing.md) for complete details on frontend testing and checks.

```bash
# Install dependencies
vp install

# Install Playwright browser binaries
pnpm exec playwright install --with-deps chromium

# Run frontend test suite (in Playwright Chromium)
vp test

# Preferred frontend validation (lints, typechecks, auto-formats; modifies source files)
vp check --fix

# Local dev server
vp dev

# Prerender static SSG site
vp build
```
