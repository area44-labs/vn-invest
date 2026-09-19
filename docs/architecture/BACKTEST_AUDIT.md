# Backtest Engine Audit — Point-in-Time & Execution Integrity

## 1. Backtest Architecture Overview

The repository features two distinct backtesting modules:

1. **Stock-Level Backtest Engine** (`scripts/lib/backtest.py`): Measures historical signal accuracy, forward return outcomes (5D, 10D, 20D), market execution eligibility, confidence calibration, and component attribution across individual stocks.
2. **Portfolio-Level Backtest Engine** (`scripts/lib/portfolio_backtest.py`): Evaluates equal-weighted multi-stock portfolio strategies, selection tie-breaking, position allocation caps, transaction costs, and slippage.

---

## 2. Comprehensive Contract Audit Table

| Audit Dimension                 | Status              | Evidence & Implementation Details                                                                                                                                                                                                     | Code Location                                                                          |
| ------------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| **Point-in-Time Slicing**       | **SAFE**            | Strict point-in-time slicing via `get_as_of_dataset(df, as_of_date)` using explicit date filtering `df[df['time'] <= as_of_date]`. Rejects unsorted or duplicate dates fail-closed.                                                   | `scripts/lib/backtest.py :: get_as_of_dataset`                                         |
| **Future Data Leakage**         | **SAFE**            | Temporal isolation verified by anti-lookahead regression tests. Mutating future data (`> T`) produces zero change in signals, indicators, trade plans, or market regimes at `T`.                                                      | `scripts/tests/test_e2e_backtest_integrity.py`, `scripts/tests/test_recommendation.py` |
| **Universe Leakage**            | **SAFE**            | Candidate selection at `T` strictly uses observable signals, risk scores, and candidate metadata timestamped `<= T`.                                                                                                                  | `scripts/lib/portfolio_backtest.py :: evaluate_portfolio_at_date`                      |
| **Survivorship Bias**           | **POTENTIAL ISSUE** | The default universe provider relies on current active listed stocks (30 symbols). If historical backtests run over multi-year horizons without accounting for delisted stocks, survivorship bias is present in the input dataset.    | `scripts/lib/vietnam_market.py :: UniverseProvider`                                    |
| **Execution Timing**            | **SAFE**            | Signal is generated at EOD `T`. Forward outcomes evaluate execution starting at session `T+1` closing through `T+N`.                                                                                                                  | `scripts/lib/backtest.py :: evaluate_forward_outcomes`                                 |
| **Transaction Costs**           | **SAFE**            | Deterministic transaction cost modeling via `calculate_execution_return()`. Costs subtract explicitly from entry and exit trade values.                                                                                               | `scripts/lib/backtest.py :: calculate_execution_return`                                |
| **Slippage Modeling**           | **SAFE**            | Adverse slippage adjustment implemented: increases entry price and decreases exit price for BUY actions; decreases entry price and increases exit price for SELL actions.                                                             | `scripts/lib/backtest.py :: calculate_execution_return`                                |
| **Portfolio Construction**      | **SAFE**            | Equal-weighted allocation with configurable `max_weight_per_position`. Preserves unallocated weight (`1.0 - sum(weights)`). Deterministic tie-breaking: `(signal_score desc, risk_adjusted_score desc, confidence desc, symbol asc)`. | `scripts/lib/portfolio_backtest.py :: evaluate_portfolio_at_date`                      |
| **Position Sizing**             | **SAFE**            | Weight invariant under transaction costs. Weight constraints enforced fail-closed (`validate_portfolio_weights`).                                                                                                                     | `scripts/lib/portfolio_backtest.py :: validate_portfolio_weights`                      |
| **Benchmark Alignment**         | **SAFE**            | Benchmarks (`VNINDEX`, `VN30`) are cleaned and sliced using exact point-in-time boundaries. Relative strength and market regime use exact benchmark alignment.                                                                        | `scripts/lib/regime.py`, `scripts/lib/recommendation.py`                               |
| **Missing Trading Days**        | **SAFE**            | Forward outcomes map exact trading session index offsets (`T+1`, `T+N`), bypassing calendar day arithmetic. Gaps, holidays, and weekends do not corrupt session counting.                                                             | `scripts/lib/backtest.py :: evaluate_forward_outcomes`                                 |
| **Missing Outcome Propagation** | **SAFE**            | If forward data is incomplete at horizon `N`, `forward_return` is set to `None`. Prevents zero-filling or denominator pollution in aggregate returns.                                                                                 | `scripts/lib/portfolio_backtest.py :: evaluate_portfolio_at_date`                      |
| **Model Version Consistency**   | **SAFE**            | Model version (`SIGNAL_MODEL_VERSION = "2.0"`) is embedded in recommendation payloads, backtest results, and snapshot schema contracts.                                                                                               | `scripts/lib/config.py`, `schemas/recommendations.schema.json`                         |

---

## 3. Backtest Execution Eligibility & Cost Model Detail

### Execution Eligibility Contract (`ExecutionEligibility`)

Market execution eligibility is evaluated point-in-time timestamped `<= T` using configurable `ExecutionConfig` parameters:

- `min_avg_traded_value_bn`: Minimum 20-day average trading value in billion VND (default: 5.0 billion VND).
- `min_avg_volume`: Minimum 20-day average trading volume in shares.
- `min_price`: Minimum closing price threshold.
- `max_participation_rate`: Maximum order size relative to 20-day average volume (e.g. 10%).

If liquidity history is insufficient or thresholds are violated, `ExecutionEligibility` sets `is_executable = False` with explicit reason codes (`insufficient_liquidity_history`, `exceeds_max_participation`, `below_min_value`).

### Transaction Cost & Slippage Mathematics

For trade entry $P_{entry}$ and exit $P_{exit}$, with transaction cost rate $c$ and slippage rate $s$:

- **BUY Action:**
  $$\text{Adjusted Entry Price} = P_{entry} \times (1 + s)$$
  $$\text{Adjusted Exit Price} = P_{exit} \times (1 - s)$$
  $$\text{Gross Return} = \frac{P_{exit} - P_{entry}}{P_{entry}}$$
  $$\text{Net Return} = \frac{\text{Adjusted Exit Price} \times (1 - c) - \text{Adjusted Entry Price} \times (1 + c)}{\text{Adjusted Entry Price} \times (1 + c)}$$

- **Non-Executed Actions (`WATCH`, `HOLD`, `AVOID`):**
  $$\text{Return} = 0.0 \quad (\text{No execution costs or slippage applied})$$

This model is verified by deterministic mathematical oracle unit tests in `scripts/tests/test_execution_costs.py`.
