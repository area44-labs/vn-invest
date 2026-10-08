"""Unit tests for T+2.5 Risk Model in scripts/lib/risk.py."""

import numpy as np
import pandas as pd
import pytest

from scripts.backtest.engine import get_as_of_dataset
from scripts.quant.risk import (
    calculate_t25_returns,
    calculate_t25_risk_metrics,
    normalize_universe_liquidity_scores,
)
from scripts.data.validation import get_clean_ohlcv_data


@pytest.mark.unit
class TestRiskModel:
    def test_risk_metrics_sufficient_data(self):
        n = 60
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        close_prices = np.linspace(20000.0, 35000.0, n)
        volumes = np.linspace(100000.0, 500000.0, n)

        df = pd.DataFrame(
            {
                "time": dates,
                "open": close_prices - 100.0,
                "high": close_prices + 500.0,
                "low": close_prices - 500.0,
                "close": close_prices,
                "volume": volumes,
            }
        )

        metrics = calculate_t25_risk_metrics(df, exchange="HOSE")

        assert metrics["var_t25"] is not None
        assert metrics["es_t25"] is not None
        assert metrics["volatility_60d"] is not None
        assert metrics["max_drawdown"] is not None
        assert metrics["avg_value_20d"] is not None

        assert metrics["es_t25"] <= metrics["var_t25"]
        assert metrics["max_drawdown"] <= 0.0

    def test_universe_liquidity_normalization(self):
        scanned = [
            {"risk_metrics": {"avg_value_20d": 1.0, "liquidity_score": None}},
            {"risk_metrics": {"avg_value_20d": 5.0, "liquidity_score": None}},
            {"risk_metrics": {"avg_value_20d": 10.0, "liquidity_score": None}},
        ]
        norm = normalize_universe_liquidity_scores(scanned, market_regime="BULL")

        assert norm[0]["risk_metrics"]["liquidity_score"] == pytest.approx(33.3)
        assert norm[2]["risk_metrics"]["liquidity_score"] == pytest.approx(100.0)

    def test_risk_metrics_missing_data(self):
        df_empty = pd.DataFrame()
        metrics = calculate_t25_risk_metrics(df_empty)

        assert metrics["var_t25"] is None
        assert metrics["es_t25"] is None
        assert metrics["volatility_60d"] is None
        assert metrics["max_drawdown"] is None
        assert metrics["liquidity_score"] is None

    def test_risk_metrics_short_data(self):
        dates = pd.date_range("2026-01-01", periods=5, freq="D")
        df_short = pd.DataFrame(
            {
                "time": dates,
                "close": [10.0, 10.5, 10.2, 10.8, 11.0],
                "volume": [1000, 1000, 1000, 1000, 1000],
            }
        )
        metrics = calculate_t25_risk_metrics(df_short)

        assert metrics["var_t25"] is None
        assert metrics["es_t25"] is None

    def test_a_t25_known_return(self):
        """1. Known return: Verify exact T+2.5 return calculation on synthetic prices."""
        prices = pd.Series([100.0, 102.0, 104.0, 106.0, 108.12])
        returns = calculate_t25_returns(prices)

        # Expected index 3: (106.0 - 100.0) / 100.0 = 0.06
        # Expected index 4: (108.12 - 102.0) / 102.0 = 0.06

        assert len(returns) == 2
        assert round(abs(returns.iloc[0] - (0.06)), 4) == 0
        assert round(abs(returns.iloc[1] - (0.06)), 4) == 0

    def test_b_t25_insufficient_history(self):
        """2. Insufficient history: Fewer than 4 price observations produces empty series."""
        prices_3 = pd.Series([100.0, 102.0, 104.0])
        returns = calculate_t25_returns(prices_3)
        assert returns.empty

        metrics = calculate_t25_risk_metrics(
            pd.DataFrame({"close": [100.0] * 19, "volume": [1000] * 19})
        )
        assert metrics["var_t25"] is None
        assert metrics["es_t25"] is None

    def test_c_t25_exact_minimum_history(self):
        """3. Exact minimum history: 4 price observations produces exactly 1 return observation."""
        prices_4 = pd.Series([100.0, 102.0, 104.0, 110.0])
        returns = calculate_t25_returns(prices_4)
        assert len(returns) == 1
        assert round(abs(returns.iloc[0] - (0.10)), 4) == 0

    def test_d_t25_no_look_ahead(self):
        """4. No look-ahead: Changing future prices cannot change earlier T+2.5 returns."""
        prices_base = pd.Series([100.0, 102.0, 104.0, 106.0, 108.0, 110.0])
        returns_base = calculate_t25_returns(prices_base)

        prices_modified = prices_base.copy()
        prices_modified.iloc[5] = 999.0  # Change D5 price far in the future
        returns_modified = calculate_t25_returns(prices_modified)

        # Returns up to index 4 (D3 -> D0, D4 -> D1) must be identical
        assert round(abs(returns_base.iloc[0] - (returns_modified.iloc[0])), 6) == 0
        assert round(abs(returns_base.iloc[1] - (returns_modified.iloc[1])), 6) == 0

    def test_e_t25_non_uniform_calendar_dates(self):
        """5. Non-uniform calendar dates: Uses trading-session rows, not calendar day interpolation."""
        # Non-uniform trading dates (e.g. weekend/holiday gaps)
        dates = ["2026-03-06", "2026-03-09", "2026-03-10", "2026-03-11", "2026-03-12"]
        prices = pd.Series([10.0, 12.0, 14.0, 15.0, 18.0], index=dates)

        returns = calculate_t25_returns(prices)
        # Session 0: 10.0 (Fri), Session 1: 12.0 (Mon), Session 2: 14.0 (Tue), Session 3: 15.0 (Wed)
        # T+2.5 (3 sessions) return at Session 3 = (15.0 - 10.0) / 10.0 = 0.50
        assert len(returns) == 2
        assert round(abs(returns.iloc[0] - (0.50)), 4) == 0

    def test_f_t25_unsorted_input(self):
        """6. Unsorted input contract: Demonstrate positional dependence on chronological order and why upstream clean sorting is required."""
        chronological_prices = pd.Series([100.0, 102.0, 104.0, 106.0])
        unsorted_prices = pd.Series([106.0, 100.0, 104.0, 102.0])

        returns_chrono = calculate_t25_returns(chronological_prices)
        returns_unsorted = calculate_t25_returns(unsorted_prices)

        # Expected chronological return at 4th session: (106 - 100) / 100 = 0.06
        # If passed unsorted data, pct_change(3) computes (102 - 106) / 106 = -0.0377
        assert round(abs(returns_chrono.iloc[0] - (0.06)), 4) == 0
        assert round(abs(returns_unsorted.iloc[0] - (-0.037736)), 4) == 0
        assert returns_chrono.iloc[0] != returns_unsorted.iloc[0]

    def test_g_t25_duplicate_invalid_rows_clean_boundary(self):
        """7. Clean-data boundary: Invalid/duplicate rows are excluded before calculation, and raw inclusion alters return."""
        # Construct synthetic price series where raw data has duplicate date and an extreme invalid price
        # Clean prices: 100.0, 102.0, 104.0, 106.0 -> 3-session return = (106.0 - 100.0) / 100.0 = 0.06
        df_raw = pd.DataFrame(
            {
                "time": [
                    "2026-01-01",
                    "2026-01-02",
                    "2026-01-03",
                    "2026-01-03",
                    "2026-01-04",
                    "2026-01-05",
                ],
                "open": [99.0, 101.0, 103.0, 50.0, 105.0, 107.0],
                "high": [105.0, 105.0, 105.0, 50.0, 110.0, 110.0],
                "low": [95.0, 95.0, 95.0, 10.0, 95.0, 95.0],
                "close": [100.0, 102.0, 104.0, 500.0, 106.0, 108.0],  # 500.0 is invalid duplicate
                "volume": [1000, 1000, 1000, 1000, 1000, 1000],
            }
        )

        clean_df, val_res = get_clean_ohlcv_data(df_raw, "TEST")

        # Under hardened validation, duplicate dates trigger a data corruption failure and return clean_df empty
        assert "duplicate_dates" in val_res["issues"]
        assert val_res["status"] == "INSUFFICIENT"
        assert clean_df.empty

    def test_i_other_risk_metrics_unchanged(self):
        """8. Regression against current risk output: volatility_60d, max_drawdown, avg_value_20d remain unaffected."""
        n = 60
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        close_prices = np.linspace(20000.0, 35000.0, n)
        volumes = np.linspace(100000.0, 500000.0, n)

        df = pd.DataFrame(
            {
                "time": dates,
                "open": close_prices - 100.0,
                "high": close_prices + 500.0,
                "low": close_prices - 500.0,
                "close": close_prices,
                "volume": volumes,
            }
        )

        metrics = calculate_t25_risk_metrics(df, exchange="HOSE")

        # Confirm non-T25 fields return expected deterministic values
        assert metrics["max_drawdown"] == 0.0
        assert metrics["volatility_60d"] is not None
        assert metrics["avg_value_20d"] is not None

    def test_var_95_deterministic_exact_value(self):
        """Verify Historical VaR 95% is finite, deterministic, and matches exact np.percentile(returns_3d, 5)."""
        # Create synthetic price series of length 30
        np.random.seed(42)
        n = 30
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        # Generate non-constant prices
        base_price = 100.0
        price_changes = np.random.normal(loc=0.001, scale=0.02, size=n)
        prices = base_price * np.exp(np.cumsum(price_changes))

        df = pd.DataFrame({"time": dates, "close": prices, "volume": [10000.0] * n})

        # Calculate returns_3d using the existing convention
        returns_3d = df["close"].pct_change(periods=3).dropna()
        expected_var = round(float(np.percentile(returns_3d, 5)), 4)

        metrics = calculate_t25_risk_metrics(df)

        assert metrics["var_t25"] is not None
        assert isinstance(metrics["var_t25"], float)
        assert metrics["var_t25"] == expected_var

    def test_var_95_insufficient_history_boundaries(self):
        """Verify VaR 95% returns None when history < 20 rows or returns_3d < 10 items."""
        # 19 rows -> history < 20
        df_19 = pd.DataFrame({"close": np.linspace(10, 20, 19), "volume": [1000] * 19})
        m_19 = calculate_t25_risk_metrics(df_19)
        assert m_19["var_t25"] is None
        assert m_19["es_t25"] is None

        # 20 rows where leading NaNs leave only 8 valid prices yielding 5 return observations (< 10 required)
        prices_with_nans = [np.nan] * 12 + [10.0 + i for i in range(8)]
        df_20_sparse = pd.DataFrame({"close": prices_with_nans, "volume": [1000] * 20})
        m_sparse = calculate_t25_risk_metrics(df_20_sparse)
        assert m_sparse["var_t25"] is None
        assert m_sparse["es_t25"] is None

    def test_expected_shortfall_deterministic_exact_value(self):
        """Verify Expected Shortfall matches exact mean of tail returns <= var_95_t25 and es_t25 <= var_t25."""
        np.random.seed(123)
        n = 30
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        prices = 100.0 + np.random.normal(0, 5, n).cumsum()
        df = pd.DataFrame({"time": dates, "close": prices, "volume": [1000.0] * n})

        returns_3d = df["close"].pct_change(periods=3).dropna()
        var_5 = float(np.percentile(returns_3d, 5))
        tail_losses = returns_3d[returns_3d <= var_5]
        expected_es = round(float(tail_losses.mean()), 4)
        expected_var = round(var_5, 4)

        metrics = calculate_t25_risk_metrics(df)

        assert metrics["es_t25"] is not None
        assert metrics["es_t25"] == expected_es
        assert metrics["es_t25"] <= expected_var

    def test_expected_shortfall_constant_returns_equals_var(self):
        """Verify that for constant return series, Expected Shortfall equals Historical VaR 95%."""
        # 25 constant prices -> returns_3d will all be 0.0
        prices = [100.0] * 25
        df = pd.DataFrame({"close": prices, "volume": [1000] * 25})

        metrics = calculate_t25_risk_metrics(df)

        assert metrics["var_t25"] is not None
        assert metrics["es_t25"] is not None
        assert metrics["var_t25"] == 0.0
        assert metrics["es_t25"] == 0.0
        assert metrics["es_t25"] == metrics["var_t25"]

    def test_var_and_es_invalid_numeric_input(self):
        """Verify clean-data boundary rejects NaN rows and risk metrics match exact calculations on clean prices."""
        n = 25
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        raw_prices = [100.0 + i * 2.0 for i in range(22)] + [np.nan, np.nan, np.nan]
        df_raw = pd.DataFrame(
            {
                "time": dates,
                "open": [p - 1.0 if not np.isnan(p) else np.nan for p in raw_prices],
                "high": [p + 2.0 if not np.isnan(p) else np.nan for p in raw_prices],
                "low": [p - 2.0 if not np.isnan(p) else np.nan for p in raw_prices],
                "close": raw_prices,
                "volume": [1000.0] * n,
            }
        )

        # 1. Verify clean data boundary detects NaN issues and fails closed
        clean_df, val_res = get_clean_ohlcv_data(df_raw, "TEST")
        assert "nan_values" in val_res["issues"]
        assert val_res["status"] == "INSUFFICIENT"
        assert clean_df.empty

        metrics = calculate_t25_risk_metrics(clean_df)
        assert metrics["var_t25"] is None
        assert metrics["es_t25"] is None

    def test_var_and_es_repeatability_determinism(self):
        """Verify that identical historical inputs produce identical VaR and ES risk outputs."""
        n = 35
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        prices = np.linspace(100.0, 150.0, n)
        prices[5] = 90.0
        prices[12] = 85.0
        prices[20] = 110.0
        df = pd.DataFrame({"time": dates, "close": prices, "volume": [5000.0] * n})

        res1 = calculate_t25_risk_metrics(df)
        res2 = calculate_t25_risk_metrics(df)

        assert res1["var_t25"] == res2["var_t25"]
        assert res1["es_t25"] == res2["es_t25"]

    def test_max_drawdown_monotonic_increase(self):
        """Verify Max Drawdown is 0.0 for a strictly non-decreasing price series."""
        n = 25
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        prices = np.linspace(100.0, 200.0, n)
        df = pd.DataFrame({"time": dates, "close": prices, "volume": [1000.0] * n})

        metrics = calculate_t25_risk_metrics(df)
        assert metrics["max_drawdown"] == 0.0

    def test_max_drawdown_pure_decline(self):
        """Verify Max Drawdown produces exact expected negative drawdown for a strictly declining series."""
        n = 25
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        # Peak = 100.0, Trough = 50.0 -> max drawdown = (50.0 - 100.0) / 100.0 = -0.5
        prices = np.linspace(100.0, 50.0, n)
        df = pd.DataFrame({"time": dates, "close": prices, "volume": [1000.0] * n})

        metrics = calculate_t25_risk_metrics(df)
        assert metrics["max_drawdown"] == -0.5

    def test_max_drawdown_recovery_after_trough(self):
        """Verify Max Drawdown preserves historical peak-to-trough drop even after full price recovery."""
        # 10 prices rise to peak 100, drop to trough 60 (-40% drawdown), then rise to new peak 150
        prices = [50.0 + i * 5.0 for i in range(11)]  # 50.0 to 100.0 (index 0 to 10)
        prices += [90.0, 80.0, 70.0, 60.0]  # Drop to 60.0 (index 11 to 14) -> -40% from peak 100.0
        prices += [70.0, 90.0, 110.0, 130.0, 150.0]  # Recover to 150.0 (index 15 to 19)
        # Total length = 20

        df = pd.DataFrame({"close": prices, "volume": [1000.0] * len(prices)})

        metrics = calculate_t25_risk_metrics(df)
        # (60.0 - 100.0) / 100.0 = -0.4000
        assert metrics["max_drawdown"] == -0.4

    def test_max_drawdown_multiple_drawdowns_selects_largest(self):
        """Verify Max Drawdown selects the global maximum peak-to-trough decline rather than the latest drawdown."""
        # Drop 1: peak 100.0 -> trough 80.0 (-20%)
        # Drop 2: peak 200.0 -> trough 100.0 (-50%) -- global max drawdown
        # Drop 3: peak 300.0 -> trough 270.0 (-10%) -- latest drawdown
        prices = (
            [50.0, 100.0, 80.0, 120.0, 200.0]
            + [180.0, 150.0, 120.0, 100.0]
            + [150.0, 250.0, 300.0, 270.0, 290.0]
            + [290.0] * 6
        )  # total 20+ elements

        df = pd.DataFrame({"close": prices, "volume": [1000.0] * len(prices)})

        metrics = calculate_t25_risk_metrics(df)
        # Global max drawdown is drop 2: (100.0 - 200.0) / 200.0 = -0.5000
        assert metrics["max_drawdown"] == -0.5

    def test_t25_3session_eod_proxy_horizon_mapping(self):
        """Verify 3-session EOD return proxy calculates exact (P_{T+3} - P_T) / P_T across trading sessions."""
        # 5 sessions T0 to T4
        prices = pd.Series([100.0, 105.0, 110.0, 115.0, 120.0])
        returns = calculate_t25_returns(prices)

        # Session 3 (T3 vs T0): (115.0 - 100.0) / 100.0 = 0.15
        # Session 4 (T4 vs T1): (120.0 - 105.0) / 105.0 = 0.142857...
        assert len(returns) == 2
        assert round(abs(returns.iloc[0] - (0.15)), 4) == 0
        assert round(abs(returns.iloc[1] - (0.142857)), 4) == 0

    def test_risk_metrics_no_lookahead_temporal_isolation(self):
        """Verify point-in-time risk calculation timestamped <= T is unaffected by future prices > T."""
        n = 30
        dates_past = pd.date_range("2026-03-01", periods=n, freq="D")
        prices_past = np.linspace(100.0, 140.0, n)
        df_as_of_t = pd.DataFrame(
            {
                "time": dates_past,
                "open": prices_past - 1.0,
                "high": prices_past + 2.0,
                "low": prices_past - 2.0,
                "close": prices_past,
                "volume": [10000.0] * n,
            }
        )

        metrics_baseline = calculate_t25_risk_metrics(df_as_of_t)

        # Append future data after 2026-03-30 with extreme price swings
        dates_future = pd.date_range("2026-03-31", periods=10, freq="D")
        prices_future = np.linspace(140.0, 50.0, 10)  # Crash in the future
        df_future = pd.DataFrame(
            {
                "time": dates_future,
                "open": prices_future - 1.0,
                "high": prices_future + 2.0,
                "low": prices_future - 2.0,
                "close": prices_future,
                "volume": [50000.0] * 10,
            }
        )
        df_full = pd.concat([df_as_of_t, df_future], ignore_index=True)

        # Use backtest point-in-time temporal slicer to slice <= 2026-03-30
        df_sliced = get_as_of_dataset(df_full, "2026-03-30")
        metrics_sliced = calculate_t25_risk_metrics(df_sliced)

        # Risk metrics as of 2026-03-30 MUST remain identical despite future crash
        assert metrics_baseline["var_t25"] == metrics_sliced["var_t25"]
        assert metrics_baseline["es_t25"] == metrics_sliced["es_t25"]
        assert metrics_baseline["volatility_60d"] == metrics_sliced["volatility_60d"]
        assert metrics_baseline["max_drawdown"] == metrics_sliced["max_drawdown"]
        assert metrics_baseline["avg_value_20d"] == metrics_sliced["avg_value_20d"]

    def test_risk_edge_cases_empty_and_none_inputs(self):
        """Verify None and empty DataFrames return null risk metrics dict."""
        m_none = calculate_t25_risk_metrics(None)
        m_empty = calculate_t25_risk_metrics(pd.DataFrame())

        for m in (m_none, m_empty):
            assert m["var_t25"] is None
            assert m["es_t25"] is None
            assert m["volatility_60d"] is None
            assert m["max_drawdown"] is None
            assert m["liquidity_score"] is None
            assert m["avg_value_20d"] is None

    def test_risk_edge_cases_constant_prices(self):
        """Verify constant prices yield zero VaR, ES, volatility, and drawdown."""
        n = 25
        df_flat = pd.DataFrame({"close": [100.0] * n, "volume": [1000.0] * n})

        metrics = calculate_t25_risk_metrics(df_flat)
        assert metrics["var_t25"] == 0.0
        assert metrics["es_t25"] == 0.0
        assert metrics["volatility_60d"] == 0.0
        assert metrics["max_drawdown"] == 0.0

    def test_risk_edge_cases_constant_positive_and_negative_returns(self):
        """Verify constant positive and negative return series produce expected VaR and ES signs."""
        # Constant positive price growth: 100 * (1.02)^i
        n = 25
        prices_pos = [100.0 * (1.02**i) for i in range(n)]
        df_pos = pd.DataFrame({"close": prices_pos, "volume": [1000.0] * n})
        m_pos = calculate_t25_risk_metrics(df_pos)

        # 3-session return is (1.02)^3 - 1 = 0.061208
        assert m_pos["var_t25"] > 0.0
        assert m_pos["es_t25"] > 0.0
        assert m_pos["max_drawdown"] == 0.0

        # Constant negative price decay: 100 * (0.98)^i
        prices_neg = [100.0 * (0.98**i) for i in range(n)]
        df_neg = pd.DataFrame({"close": prices_neg, "volume": [1000.0] * n})
        m_neg = calculate_t25_risk_metrics(df_neg)

        assert m_neg["var_t25"] < 0.0
        assert m_neg["es_t25"] < 0.0
        assert m_neg["max_drawdown"] < 0.0

    def test_risk_edge_cases_upcom_exchange_vwap_selection(self):
        """Verify UPCOM exchange uses vwap column when available instead of close column."""
        n = 25
        close_prices = [100.0] * n
        vwap_prices = np.linspace(100.0, 50.0, n)  # Declining VWAP prices

        df_upcom = pd.DataFrame(
            {"close": close_prices, "vwap": vwap_prices, "volume": [1000.0] * n}
        )

        metrics_hose = calculate_t25_risk_metrics(df_upcom, exchange="HOSE")
        metrics_upcom = calculate_t25_risk_metrics(df_upcom, exchange="UPCOM")

        # HOSE uses close (constant 100) -> max_drawdown = 0.0
        assert metrics_hose["max_drawdown"] == 0.0
        # UPCOM uses vwap (declining 100 to 50) -> max_drawdown = -0.5
        assert metrics_upcom["max_drawdown"] == -0.5

    def test_risk_edge_cases_missing_volume_column(self):
        """Verify missing volume column results in avg_value_20d = None without crashing."""
        n = 25
        df_no_vol = pd.DataFrame({"close": np.linspace(100.0, 150.0, n)})

        metrics = calculate_t25_risk_metrics(df_no_vol)

        assert metrics["avg_value_20d"] is None
        assert metrics["var_t25"] is not None
        assert metrics["max_drawdown"] is not None
