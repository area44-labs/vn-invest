# Refactoring Roadmap — VN Invest Development Plan

This roadmap defines the sequential phases for refactoring and enhancing the VN Invest system. Order of execution is strictly governed by architectural dependencies.

---

## Roadmap Overview

```
Phase 0: Audit & Architecture Analysis (CURRENT PHASE — COMPLETE)
    │
    ▼
Phase 1: Architecture & Data Foundation (Unidirectional Imports & Ownership)
    │
    ▼
Phase 2: Data Quality, Boundary Hardening & Historical Universe (Universe(as_of=T))
    │
    ▼
Phase 3: Quant Engine Decoupling & Pure Functional Separation
    │
    ▼
Phase 4: Research & Backtest Validation (Parity Tests & Characterization)
    │
    ▼
Phase 5: Application Pipeline & Snapshot Separation
    │
    ▼
Phase 6: Artifact Contract Strictness & Automated TS Type Generation
    │
    ▼
Phase 7: Operational Monitoring & Drift Enhancement
    │
    ▼
Phase 8: Frontend Loader & SSG Cleanup (Explicit Error States)
    │
    ▼
Phase 9: CI/CD Hardening & Automated Quality Gates (Branch Coverage & Gates)
```

---

## Phase Details

### Phase 1: Architecture & Data Foundation

- **Goal:** Resolve circular import dependency (`risk.py` <-> `recommendation.py`), establish a strict unidirectional import graph (`config` -> `risk` -> `scoring` -> `recommendation`), and centralize configuration imports.
- **Dependencies:** Phase 0 Audit Complete.
- **Files Affected:** `scripts/lib/risk.py`, `scripts/lib/recommendation.py`, `scripts/lib/config.py`, new `scripts/lib/scoring.py`, `scripts/lib/formatting.py`.
- **Expected Outcome:** `risk.py` operates without importing `recommendation.py`. Shared scoring logic (`calculate_risk_adjusted_score`) and constants (`VALID_MARKET_REGIMES`) reside in `config.py` / `scoring.py`.
- **Risk:** **LOW** (Refactoring module boundaries and import locations without altering mathematical formulas).
- **Validation:** Run `python scripts/tests/run_tests.py` and verify `scripts.lib.risk` imports cleanly in isolation.

### Phase 2: Data Quality, Boundary Hardening & Historical Universe Membership

- **Goal:** Externalize candidate stock universe definitions into configuration files and implement point-in-time historical universe resolution (`Universe(as_of=T)`), supporting delisted or historically tracked securities.
- **Dependencies:** Phase 1 Complete.
- **Files Affected:** `scripts/lib/vietnam_market.py`, `scripts/data_provider.py`, new `config/universe_default.json`.
- **Expected Outcome:** Candidate stock lists read from JSON configuration instead of hardcoded Python dictionaries, with point-in-time historical universe awareness preventing survivorship bias.
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

- **Goal:** Enforce characterization parity tests (`old_output == new_output`) prior to decomposing `scripts/lib/backtest.py` into focused submodules (`execution.py`, `walk_forward.py`, `calibration.py`).
- **Dependencies:** Phase 3 Complete.
- **Files Affected:** `scripts/lib/backtest.py`, `scripts/lib/portfolio_backtest.py`, `scripts/tests/test_backtest.py`, `scripts/tests/test_parity.py`.
- **Expected Outcome:** Clean separation of stock backtesting, portfolio evaluation, and calibration logic with verified 100% mathematical output parity.
- **Risk:** **MEDIUM**.
- **Validation:** Run `test_backtest.py`, `test_portfolio_backtest.py`, `test_e2e_backtest_integrity.py`, `test_parity.py`.

### Phase 5: Application Pipeline & Snapshot Separation

- **Goal:** Decompose God module `scripts/generate_report.py` into modular orchestrator (`pipeline_orchestrator.py`), snapshot loader (`snapshot_loader.py`), and report writer (`report_writer.py`) components.
- **Dependencies:** Phase 3 & 4 Complete.
- **Files Affected:** `scripts/generate_report.py`, new `scripts/pipeline_orchestrator.py`, `scripts/snapshot_loader.py`.
- **Expected Outcome:** Modular pipeline orchestrator with isolated historical report generation and snapshot loading.
- **Risk:** **HIGH**.
- **Validation:** Run `test_historical_report.py`, `test_parity.py`, `test_history_index.py`.

### Phase 6: Artifact Contract Strictness & Automated TS Type Generation

- **Goal:** Implement automated build-time generation of TypeScript interfaces (`src/types/recommendation.ts`) directly from `schemas/recommendations.schema.json` using `json-schema-to-typescript`, eliminating manual type sync drift.
- **Dependencies:** Phase 5 Complete.
- **Files Affected:** `schemas/recommendations.schema.json`, `src/types/recommendation.ts`, `package.json`, `scripts/tests/test_schema.py`.
- **Expected Outcome:** Automated type generation ensuring TypeScript interfaces match JSON Schema contracts exactly.
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

- **Goal:** Remove synthetic fallback recommendation generators from `src/data/loader.ts` and ensure graceful empty/error state UI rendering when generated JSON artifacts are missing.
- **Dependencies:** Phase 6 Complete.
- **Files Affected:** `src/data/loader.ts`, `src/pages/Dashboard.tsx`, `src/routes/*`.
- **Expected Outcome:** Frontend displays explicit error or empty state UI when generated data artifacts are missing, eliminating synthetic mock data generation.
- **Risk:** **MEDIUM**.
- **Validation:** Run `pnpm check`, `pnpm build`, `test_ssg_html.py`.

### Phase 9: CI/CD Hardening & Automated Quality Gates

- **Goal:** Enforce strict automated testing, line/branch coverage reporting (`pytest --cov`), and build checks across GitHub Actions workflows.
- **Dependencies:** Phase 1–8 Complete.
- **Files Affected:** `.github/workflows/tests.yml`, `.github/workflows/pages.yml`.
- **Expected Outcome:** Automated end-to-end pipeline verification and quality gates on all pull requests and main branch deployments.
- **Risk:** **LOW**.
- **Validation:** Execute full CI workflow locally and on GitHub.
