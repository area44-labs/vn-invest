# Refactoring Roadmap — VN Invest Development Plan

This roadmap defines the sequential phases for refactoring and enhancing the VN Invest system. Order of execution is strictly governed by architectural dependencies.

---

## Roadmap Overview

```
Phase 0: Audit & Architecture Analysis (CURRENT PHASE — COMPLETE)
    │
    ▼
Phase 1: Architecture & Data Foundation
    │
    ▼
Phase 2: Data Quality & Boundary Hardening
    │
    ▼
Phase 3: Quant Engine Decoupling & Pure Functional Separation
    │
    ▼
Phase 4: Research & Backtest Validation
    │
    ▼
Phase 5: Application Pipeline & Snapshot Separation
    │
    ▼
Phase 6: Artifact Contract & Schema Strictness
    │
    ▼
Phase 7: Operational Monitoring & Drift Enhancement
    │
    ▼
Phase 8: Frontend Loader & SSG Cleanup
    │
    ▼
Phase 9: CI/CD Hardening & Automated Quality Gates
```

---

## Phase Details

### Phase 1: Architecture & Data Foundation

- **Goal:** Resolve circular import dependency (`risk.py` <-> `recommendation.py`) and centralize configuration imports.
- **Dependencies:** Phase 0 Audit Complete.
- **Files Affected:** `scripts/lib/risk.py`, `scripts/lib/recommendation.py`, `scripts/lib/config.py`, new `scripts/lib/formatting.py`.
- **Expected Outcome:** Clean unidirectional import graph: `formatting.py` handles VND string formatting; `risk.py` is purely numeric without importing `recommendation.py`.
- **Risk:** **LOW** (Refactoring imports and utility location without changing mathematical formulas).
- **Validation:** Run `python scripts/tests/run_tests.py`.

### Phase 2: Data Quality & Boundary Hardening

- **Goal:** Externalize hardcoded universe provider candidate stock list into snapshot/config files and enforce strict clean-data boundaries.
- **Dependencies:** Phase 1 Complete.
- **Files Affected:** `scripts/lib/vietnam_market.py`, `scripts/data_provider.py`, new `config/universe_default.json`.
- **Expected Outcome:** Candidate stock lists read from JSON configuration instead of hardcoded Python dictionaries.
- **Risk:** **LOW**.
- **Validation:** Run `test_data_provider.py`, `test_data_quality.py`, `test_unit_normalization.py`.

### Phase 3: Quant Engine Decoupling & Pure Functional Separation

- **Goal:** Eliminate in-place dictionary mutations during universe liquidity score normalization and standardize parameter imports.
- **Dependencies:** Phase 1 & 2 Complete.
- **Files Affected:** `scripts/lib/risk.py`, `scripts/lib/recommendation.py`, `scripts/generate_report.py`.
- **Expected Outcome:** `normalize_universe_liquidity_scores` returns new updated payloads without mutating input dictionaries in-place.
- **Risk:** **MEDIUM**.
- **Validation:** Run `test_risk.py`, `test_recommendation.py`, `test_parity.py`.

### Phase 4: Research & Backtest Validation

- **Goal:** Decompose `scripts/lib/backtest.py` into focused submodules (execution eligibility, walk-forward, calibration).
- **Dependencies:** Phase 3 Complete.
- **Files Affected:** `scripts/lib/backtest.py`, `scripts/lib/portfolio_backtest.py`, `scripts/tests/test_backtest.py`.
- **Expected Outcome:** Clean separation of stock backtesting, portfolio evaluation, and calibration logic.
- **Risk:** **MEDIUM**.
- **Validation:** Run `test_backtest.py`, `test_portfolio_backtest.py`, `test_e2e_backtest_integrity.py`.

### Phase 5: Application Pipeline & Snapshot Separation

- **Goal:** Decompose God module `scripts/generate_report.py` into modular orchestrator, snapshot loader, and report writer components.
- **Dependencies:** Phase 3 & 4 Complete.
- **Files Affected:** `scripts/generate_report.py`, new `scripts/pipeline_orchestrator.py`, `scripts/snapshot_loader.py`.
- **Expected Outcome:** Modular pipeline orchestrator with isolated historical report generation and snapshot loading.
- **Risk:** **HIGH**.
- **Validation:** Run `test_historical_report.py`, `test_parity.py`, `test_history_index.py`.

### Phase 6: Artifact Contract & Schema Strictness

- **Goal:** Align TypeScript frontend interfaces (`src/types/recommendation.ts`) strictly with `schemas/recommendations.schema.json`.
- **Dependencies:** Phase 5 Complete.
- **Files Affected:** `schemas/recommendations.schema.json`, `src/types/recommendation.ts`, `scripts/tests/test_schema.py`.
- **Expected Outcome:** Automated build-time validation ensuring TypeScript types match JSON Schema contracts exactly.
- **Risk:** **LOW**.
- **Validation:** Run `test_schema.py` and `pnpm check`.

### Phase 7: Operational Monitoring & Drift Enhancement

- **Goal:** Enhance data/model drift monitoring alerts and operational health report outputs.
- **Dependencies:** Phase 5 & 6 Complete.
- **Files Affected:** `scripts/lib/monitoring.py`, `scripts/tests/test_monitoring.py`, `scripts/tests/test_drift_monitoring.py`.
- **Expected Outcome:** Robust monitoring artifacts saved to `generated/monitoring.json`.
- **Risk:** **LOW**.
- **Validation:** Run `test_monitoring.py` and `test_drift_monitoring.py`.

### Phase 8: Frontend Loader & SSG Cleanup

- **Goal:** Remove synthetic fallback recommendation generators from `src/data/loader.ts` and ensure graceful empty/error state UI rendering.
- **Dependencies:** Phase 6 Complete.
- **Files Affected:** `src/data/loader.ts`, `src/pages/Dashboard.tsx`, `src/routes/*`.
- **Expected Outcome:** Frontend displays explicit error or empty state UI when generated data artifacts are missing, eliminating synthetic mock data generation.
- **Risk:** **MEDIUM**.
- **Validation:** Run `pnpm check`, `pnpm build`, `test_ssg_html.py`.

### Phase 9: CI/CD Hardening & Automated Quality Gates

- **Goal:** Enforce strict automated testing and build checks across GitHub Actions workflows.
- **Dependencies:** Phase 1–8 Complete.
- **Files Affected:** `.github/workflows/tests.yml`, `.github/workflows/pages.yml`.
- **Expected Outcome:** Automated end-to-end pipeline verification on all pull requests and main branch deployments.
- **Risk:** **LOW**.
- **Validation:** Execute full CI workflow locally and on GitHub.
