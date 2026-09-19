# Target Architecture Proposal — Layered Modular Design

## 1. Target Architecture Overview

To resolve identified architectural problems (circular imports, God module responsibilities, hardcoded universe data, frontend fallback logic), the target architecture establishes strict unidirectional data flow across 5 cleanly separated layers:

```
┌─────────────────────────────────────────────────────────┐
│                     1. Data Layer                       │
│  providers / cache / unit normalization / validation    │
│  files: scripts/data_provider.py, lib/vietnam_market.py │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│                    2. Quant Engine                      │
│   indicators / features / signals / scoring / risk      │
│   files: lib/config.py, lib/features.py, lib/regime.py  │
│          lib/risk.py, lib/recommendation.py             │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│                   3. Research Engine                    │
│    point-in-time slicing / execution / backtest         │
│    portfolio / calibration / walk-forward evaluation    │
│    files: lib/backtest.py, lib/portfolio_backtest.py    │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│               4. Application Pipeline                   │
│   orchestration / snapshots / monitoring / persistence  │
│   files: scripts/generate_report.py, lib/monitoring.py  │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
               JSON Schema Data Contract
            (schemas/recommendations.schema.json)
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│                     5. React SSG                        │
│             presentation & visualization only           │
│             files: src/routes/*, src/components/*       │
└─────────────────────────────────────────────────────────┘
```

---

## 2. Layer & Module Boundaries

### Layer 1: Data Layer

- **Responsibility:** Raw market data acquisition from `vnstock`, provider abstraction, canonical unit normalization (`VND/share`, `shares`, `VND`), clean-data boundary validation (`get_clean_ohlcv_data`), and snapshot loading.
- **Strict Boundary Rule:** Must NOT import from Quant Engine, Research Engine, or Application Pipeline.

### Layer 2: Quant Engine

- **Responsibility:** Pure mathematical quantitative algorithms: technical indicator calculation (`features.py`), market regime detection (`regime.py`), T+2.5 risk metrics (`risk.py`), composite signal scoring, confidence calculation, and trade plan generation (`recommendation.py`).
- **Strict Boundary Rule:** Pure functions only. Zero network calls, zero file I/O side effects, zero circular imports. Quantitative formatting helpers (e.g. `format_vnd`) reside in a dedicated utility module (`formatting.py`).

### Layer 3: Research Engine

- **Responsibility:** Point-in-time temporal dataset slicing (`get_as_of_dataset`), market execution eligibility, transaction cost & adverse slippage calculation, equal-weighted portfolio simulation, walk-forward analysis, and confidence calibration.
- **Strict Boundary Rule:** Reuses Quant Engine functions for point-in-time signal generation without modifying production model weights or formulas.

### Layer 4: Application Pipeline

- **Responsibility:** Pipeline orchestration (`run_pipeline`), historical snapshot generation (`generate_historical_report`), health checks, schema validation against `schemas/recommendations.schema.json`, data/model drift monitoring, and artifact persistence (`generated/`).
- **Strict Boundary Rule:** Orchestrates lower layers; does not define quantitative formulas or UI presentation logic.

### Layer 5: React SSG Presentation Layer

- **Responsibility:** Static site prerendering via TanStack Router and Vite, route management (`/`, `/history`, `/methodology`, `/stock/$symbol`), interactive UI components, and charts.
- **Strict Boundary Rule:** Presentation only. Zero quantitative formula recomputation, zero synthetic fallback recommendation generation. Displays explicit error/empty UI when generated JSON artifacts are absent.

---

## 3. Reproducibility Architecture & Mechanisms

To guarantee deterministic, byte-for-byte reproducible execution across environments:

1. **Explicit Evaluation Date (`data_as_of`):** All calculations are strictly bound to an explicit trading session date $T$.
2. **Point-in-Time Dataset Slicing:** Raw historical DataFrames are sliced strictly `<= T` using `get_as_of_dataset()`, ensuring future data (`> T`) is completely isolated.
3. **Fixed ISO Timestamp Normalization for Reproducibility Verification:** `canonicalize_report_for_reproducibility()` replaces dynamic system runtime execution timestamps (`generated_at`) with a fixed placeholder (`2026-01-01T00:00:00+00:00`) during automated regression parity testing (`test_parity.py`).
4. **Deterministic Tie-Breaking:** Candidate selection in portfolio backtesting enforces deterministic multi-key sorting: `(signal_score desc, risk_adjusted_score desc, confidence desc, symbol asc)`.
5. **Pinned Python & Node Dependencies:** Pinned package requirements in `requirements.txt` and `pnpm-lock.yaml` ensure identical dependency environments.
