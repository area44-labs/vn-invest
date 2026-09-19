# Frontend & SSG Audit — React 19 / TanStack Router Architecture

## 1. Route Architecture & Page Mapping

The frontend is built with React 19, TypeScript, TanStack Router, Vite, and Tailwind CSS v4. The route structure is defined in `src/routes/`:

| Route Path       | File                           | Component                                   | Purpose                                                                                                                   | Generated Data Dependency                                       |
| ---------------- | ------------------------------ | ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| `/`              | `src/routes/index.tsx`         | `Dashboard` (`src/pages/Dashboard.tsx`)     | Main dashboard displaying market regime, breadth summary, top BUY/WATCH recommendations table, and stock filter controls. | `generated/recommendations.json`, `generated/market.json`       |
| `/history`       | `src/routes/history.tsx`       | `History` (`src/pages/History.tsx`)         | Historical report browser allowing users to view prior daily recommendations and market regimes.                          | `generated/history/index.json`, `generated/history/{date}.json` |
| `/methodology`   | `src/routes/methodology.tsx`   | `Methodology` (`src/pages/Methodology.tsx`) | Explains quantitative model methodology, indicator weights, risk horizons, and trade plan parameters.                     | None (Static documentation)                                     |
| `/stock/$symbol` | `src/routes/stock/$symbol.tsx` | `StockDetail` (`src/pages/StockDetail.tsx`) | Detailed stock page showing signal components, T+2.5 risk metrics, indicators, and interactive trade plan bounds.         | `generated/recommendations.json`                                |

---

## 2. SSG Prerendering & Static Build Pipeline

### Configuration (`vite.config.ts`)

- **Prerender Plugin:** Uses `@tanstack/router-plugin` with `prerenderRoutes` configured for static site generation (SSG).
- **Prerender Routes:** Prerenders `/`, `/history`, `/methodology`.
- **Generated Artifact Copying:**
  - In Dev Mode: Custom `generatedDataPlugin` serves files directly from root `generated/` folder.
  - In Production Build: Vite build script copies root `generated/` artifacts into `dist/client/generated/` and `dist/client/public/generated/`.

### GitHub Pages Compatibility & Base URL

- Base URL is configured for GitHub Pages deployment (`/` or custom domain).
- Client routing uses TanStack Router's HTML5 history mode with SSG fallback.

---

## 3. Business Logic Separation Audit

### Contract Strictness Evaluation

- **Principle:** Python = data + algorithms + quantitative logic; React = presentation + navigation + visualization; JSON = contract.

### Violations / Technical Debt Found in Frontend

1. **Frontend Loader Fallback Mechanics (`src/data/loader.ts`):**
   - _Evidence:_ Lines 45–120 in `src/data/loader.ts` contain mock recommendation generators and fallback JSON creation when network requests fail.
   - _Violation:_ Frontend should gracefully display an explicit error state or empty state when generated data artifacts are missing, rather than generating synthetic fallback recommendation data.

2. **Currency Formatting & Display Conversion (`src/lib/format.ts`):**
   - _Evidence:_ `formatVND` formats raw numeric prices.
   - _Status:_ **ACCEPTABLE / PRESENTATION ONLY**. The backend provides full VND integers in recommendation JSON (e.g., `33630`), and `formatVND` applies locale formatting (`33,630 ₫` or `33.630 ₫`). This is standard presentation formatting.

3. **Trade Plan Display Controls (`src/components/recommendation-card.tsx`):**
   - _Evidence:_ UI renders entry, stop loss, target 1, and target 2 values read directly from `rec.trade_plan`.
   - _Status:_ **SAFE**. UI does not compute stop loss or targets; all trade plan boundaries are calculated upstream in Python backend.
