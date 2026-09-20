# Data Flow Audit — End-to-End Lineage & Schema Contracts

This document provides a complete audit of the data lineage, validation boundaries, unit transformations, timestamp semantics, schema versioning, and persistence contracts across the VN Invest quantitative engine and frontend application.

---

## 1. End-to-End Data Lineage & Lifecycle

```
[External VNStock API / KBS / MSN]
              │ (HTTP Request / vnstock.api.quote)
              ▼
[Raw Provider Response]
              │
              ├─► validate_canonical_ohlcv() [data_provider.py]
              │      - Checks required columns (time, open, high, low, close, volume)
              │      - Rejects empty, NaN, Inf, duplicate dates, unsorted dates
              │      - Raises CanonicalOHLCVError on invalid data
              │
              ▼
[Provider Standardized DataFrame]
              │
              ├─► normalize_ohlcv_units() [vietnam_market.py]
              │      - Converts prices from thousand VND/share to full VND/share (* 1000)
              │      - Preserves volume in shares
              │      - Calculates trading_value_vnd = close * volume
              │      - Calculates avg_value_20d_bn = mean(trading_value_vnd[-20:]) / 1e9
              │
              ▼
[Canonical Unit DataFrame]
              │
              ├─► get_clean_ohlcv_data() [vietnam_market.py]
              │      - Performs non-mutating validation (validate_ohlcv_data)
              │      - Removes invalid rows (NaN, non-positive close/volume)
              │      - Checks OHLC logical relationships (High >= Low, High >= Open/Close, Low <= Open/Close)
              │      - Assesses data quality: 'SUFFICIENT' (>= 50 sessions), 'PARTIAL' (20–49), 'INSUFFICIENT' (< 20)
              │
              ▼
[Clean Benchmark & Stock DataFrames]
              │
              ├─► Market Regime & Breadth [regime.py, generate_report.py]
              │      - Breadth ratio = count(stock_close > MA20) / total_valid_stocks
              │      - Regime = detect_market_regime(df_vnindex, df_vn30, breadth_ratio)
              │        Valid regimes: {"STRONG_BULL", "BULL", "NEUTRAL", "DEFENSIVE", "BEAR", "PANIC"}
              │      - Market data_as_of = extract_latest_trading_date(df_vnindex)
              │
              ├─► Signal Engine & Recommendations [recommendation.py, features.py, risk.py, scoring.py]
              │      - Features = calculate_multi_timeframe_features(df_stock)
              │      - Signal Score = calculate_signal_score(features)
              │      - Risk Metrics = calculate_t25_risk_metrics(df_stock)
              │      - Trade Plan = entry, stop_loss, target_1, target_2, position_size
              │
              ▼
[Raw Recommendations Payload]
              │
              ├─► calculate_liquidity_scores() [scoring.py]
              │      - Ranks 20-day avg trading values across universe
              │      - Calculates percentile liquidity_score (0.0 – 100.0) without mutating inputs
              │
              ▼
[Final Quant Payload (dict)]
              │
              ├─► Schema Validation & Monitoring [generate_report.py, monitoring.py]
              │      - jsonschema.validate(payload, schema)
              │      - check_required_artifacts(), find_nan_or_inf()
              │      - evaluate_data_and_model_drift()
              │
              ▼
[JSON Artifact Persistence] [generated/]
              │   ├── recommendations.json
              │   ├── market.json
              │   ├── monitoring.json
              │   ├── history/YYYY-MM-DD.json
              │   └── history/index.json
              │
              ▼
[SSG Build & Client Hydration] [vite.config.ts, src/data/loader.ts]
              │   - Dev server plugin serves generated/ JSON
              │   - Build copies generated/ to dist/client/generated/
              │   - TanStack Router prerenders static HTML pages
              │   - Client React components consume typed loader data
```

---

## 2. Canonical Schema Contract & Version Semantics

### Canonical Schema Source of Truth

`schemas/recommendations.schema.json` is the canonical contract for all generated report payloads.

1. **MarketRegime Domain Alignment:**
   - Canonical Enum: `["STRONG_BULL", "BULL", "NEUTRAL", "DEFENSIVE", "BEAR", "PANIC"]`.
   - All layers (Python `VALID_MARKET_REGIMES`, JSON Schema, generated JSON payloads, and TypeScript `src/types/recommendation.ts`) must support `"NEUTRAL"`.
   - Phase 6 implements automated TypeScript interface generation (`json-schema-to-typescript`) directly from `schemas/recommendations.schema.json` to prevent type drift.

2. **Explicit Version Semantics:**
   - `schema_version` (e.g. `"2.0"`): Version of the JSON structure and schema contract. Incrementing `schema_version` indicates structural schema or field definition changes.
   - `signal_model_version` (e.g. `"2.0"`): Version of the quantitative scoring algorithm and signal rules. Present in top-level JSON payloads and TypeScript types.
   - `generated_at`: ISO 8601 UTC timestamp representing system execution time.
   - `data_as_of`: Calendar date (`YYYY-MM-DD`) representing the latest EOD market data session present in the dataset.

---

## 3. Answers to Data Audit Questions

### Q1: Where is data fetched from?

**Code Location:** `scripts/data_provider.py :: VnstockDataProvider.fetch_ohlcv`
**Details:** Data is fetched from Vietnamese equity market endpoints via the `vnstock` package (`vnstock.api.quote.quote`). The primary provider source is configured as `'KBS'` or `'MSN'`.

### Q2: When is data cached?

**Code Location:** `scripts/generate_report.py :: main` and `load_historical_ohlcv`
**Details:** In production daily updates, historical OHLCV data is fetched per symbol during pipeline execution. In historical report generation mode (`--as-of`), OHLCV history can be loaded from an explicit pre-saved snapshot file (`--universe-snapshot`), skipping live network requests.

### Q3: Where is the cache located?

**Code Location:** `generated/history/*.json` and user-provided snapshot files.
**Details:** Disk artifacts in `generated/` serve as persistent point-in-time snapshots.

### Q4: Where is data validated?

**Code Location:**

1. Raw Boundary: `scripts/data_provider.py :: validate_canonical_ohlcv`
2. Cleaning Boundary: `scripts/lib/vietnam_market.py :: validate_ohlcv_data`
3. Pipeline Schema Boundary: `scripts/generate_report.py :: load_schema` & `jsonschema.validate`
4. Operational Monitoring Boundary: `scripts/lib/monitoring.py :: evaluate_production_monitoring`

### Q5: Where is OHLCV normalized?

**Code Location:** `scripts/lib/vietnam_market.py :: normalize_ohlcv_units`
**Details:** Raw provider prices in `thousand_VND/share` are multiplied by `1000.0` to convert to full `VND/share`. Volume is preserved in `shares`. Trading values are calculated as `close * volume` (VND). The 20-day average trading value is expressed in `billion_VND`.

### Q6: How is data timestamp determined?

**Code Location:** `scripts/lib/vietnam_market.py :: extract_latest_trading_date`
**Details:** Timestamps are derived strictly from the latest EOD trading session date present in the validated clean dataset (`df['time'].iloc[-1]`), formatted as `YYYY-MM-DD`. Current system execution date (`datetime.now()`) is **never** substituted for market data timestamps.

### Q7: Where is "data_as_of" created?

**Code Location:** `scripts/generate_report.py :: run_pipeline` and `generate_historical_report`
**Details:** `data_as_of` for top-level market reports is extracted directly from the validated benchmark `VNINDEX` DataFrame: `data_as_of = extract_latest_trading_date(clean_vnindex)`. If `clean_vnindex` is empty or null, `data_as_of` remains `None`. In historical `--as-of` mode, `data_as_of` is the explicitly supplied target date string.

### Q8: How is missing data handled?

**Code Location:** `scripts/lib/vietnam_market.py :: get_clean_ohlcv_data`, `scripts/lib/recommendation.py`
**Details:**

- If stock history < 20 sessions: `data_quality` is set to `'INSUFFICIENT'`, recommendation action is forced to `'AVOID'`, and signal/risk scores return `None`.
- If stock history is between 20 and 49 sessions: `data_quality` is `'PARTIAL'`, confidence is penalized, but indicators are calculated on available data.
- In risk metrics (`scripts/lib/risk.py`): If returns series has < 10 observations, VaR 95% and ES 95% return `None` (no zero-filling).
- In backtesting (`scripts/lib/backtest.py` and `portfolio_backtest.py`): Missing forward outcome trading sessions result in forward returns marked as `None`, explicitly preventing zero-filling or denominator pollution.

### Q9: How is duplicate data handled?

**Code Location:** `scripts/data_provider.py :: validate_canonical_ohlcv` and `scripts/generate_report.py :: update_history_index`
**Details:**

- `validate_canonical_ohlcv` checks `df['time'].duplicated().any()`. If duplicates exist, it raises `CanonicalOHLCVError` fail-closed.
- `update_history_index` enforces unique, strictly descending trading session dates in `history/index.json`. Duplicate dates cause explicit exceptions.

### Q10: How is stale data handled?

**Code Location:** `scripts/lib/monitoring.py :: evaluate_production_monitoring`
**Details:** Operational monitoring compares top-level `data_as_of` against the current execution date UTC. If `data_as_of` is more than 3 calendar days behind execution date, a `WARNING` status is flagged in pipeline monitoring. Additionally, individual stock recommendations retain their own stock-level `data_as_of` so stale individual tickers are visible.

### Q11: Where could future data leak into historical calculations?

**Code Location Audit:** `scripts/lib/backtest.py :: get_as_of_dataset`
**Details:** Point-in-time isolation is enforced via explicit filtering: `df[df['time'] <= as_of_date]`. Anti-lookahead regression tests in `scripts/tests/test_recommendation.py` and `scripts/tests/test_e2e_backtest_integrity.py` verify that mutating future data (`> T`) produces zero change in signals, indicators, trade plans, or regime at `T`.

### Q12: How is generated JSON created?

**Code Location:** `scripts/generate_report.py :: save_json_files`
**Details:** Python dictionaries produced by `run_pipeline` or `generate_historical_report` are serialized to JSON using `json.dump(indent=2, ensure_ascii=False)` and saved to `generated/recommendations.json`, `generated/market.json`, `generated/monitoring.json`, `generated/history/YYYY-MM-DD.json`, and `generated/history/index.json`.

### Q13: Where does frontend consume JSON?

**Code Location:** `src/data/loader.ts`
**Details:** The frontend loader fetches JSON files from `generated/recommendations.json`, `generated/market.json`, `generated/history/index.json`, and `generated/history/{date}.json`. During Vite SSG build, if generated JSON artifacts are missing, explicit build errors are thrown.
