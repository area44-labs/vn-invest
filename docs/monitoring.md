# Production Monitoring

This document is the agent-first guide for the operational monitoring subsystem in **VN Invest** (`area44-labs/vn-invest`). Monitoring validates pipeline execution, market-data quality, symbol coverage, data freshness, and performance metrics before reporting results.

Monitoring must reflect actual pipeline outcomes and use authoritative data sources. A successful CI run alone does not guarantee complete or up-to-date market data.

## 1. Monitoring Checks

- **Pipeline execution:** Verify required stages complete successfully and preserve failure diagnostics.
- **Symbol coverage:** Track expected, processed, skipped, and failed symbols.
- **Market data quality:** Validate OHLCV completeness, values, duplicates, and trading dates.
- **Benchmark quality:** Validate VNINDEX and VN30 independently when required or supplied.
- **Data freshness:** Compare the latest available trading date with the expected trading date, accounting for market holidays.
- **Performance monitoring:** Validate performance metrics and detect drift only when sufficient reliable data is available.

Checks must distinguish missing data, invalid data, skipped checks, and insufficient evidence.

## 2. Status and Thresholds

| Status | Meaning |
|---|---|
| `PASS` | Applicable checks satisfy their requirements. |
| `WARNING` | Non-critical data-quality or coverage issue. |
| `FAIL` | Critical validation or operational failure. |
| `INSUFFICIENT` | Not enough reliable evidence to evaluate a check. |

The existing processed-coverage policy is:

- `PASS`: processed ratio ≥ 0.80, subject to other checks.
- `WARNING`: 0.50 ≤ processed ratio < 0.80.
- `FAIL`: processed ratio < 0.50, subject to the configured failure policy.

Critical validation failures must not be overridden by coverage thresholds. Missing metrics must not be treated as zero, and market holidays must not be misclassified as stale data.

## 3. Performance and Drift

Performance monitoring consumes the performance payload from `universe_audit["performance"]` in memory.

Historical drift checks must use qualified reports and exclude incomplete or low-coverage baselines according to the existing implementation. If sufficient evidence is unavailable, return `INSUFFICIENT` rather than generating a misleading drift failure.

## 4. Reporting and Failure Handling

Monitoring output must follow the repository's authoritative schema and include, where available:

- Overall status and report timestamp.
- Pipeline and symbol-processing results.
- Market-data quality and freshness.
- Performance and drift results.
- Actionable warnings, failures, and diagnostic details.

Critical monitoring failures must follow the configured fail-closed policy, return a non-zero exit status when required, and preserve diagnostic artifacts where possible.

## 5. Testing and Maintenance

Tests must cover successful runs, partial processing, stale or invalid data, insufficient historical baselines, missing benchmarks, malformed inputs, and critical failures.

When monitoring behavior or thresholds change, update the implementation, tests, and this document together. Keep all documented artifact dependencies and schema fields consistent with the actual code.
