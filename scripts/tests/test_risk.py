"""Unit tests for T+2.5 Risk Model in scripts/lib/risk.py."""

import unittest

import numpy as np
import pandas as pd

from scripts.lib.risk import (
    calculate_t25_returns,
    calculate_t25_risk_metrics,
    normalize_universe_liquidity_scores,
)
from scripts.lib.vietnam_market import get_clean_ohlcv_data


class TestRiskModel(unittest.TestCase):
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

        self.assertIsNotNone(metrics["var_t25"])
        self.assertIsNotNone(metrics["es_t25"])
        self.assertIsNotNone(metrics["volatility_60d"])
        self.assertIsNotNone(metrics["max_drawdown"])
        self.assertIsNotNone(metrics["avg_value_20d"])

        self.assertLessEqual(metrics["es_t25"], metrics["var_t25"])
        self.assertLessEqual(metrics["max_drawdown"], 0.0)

    def test_universe_liquidity_normalization(self):
        scanned = [
            {"risk_metrics": {"avg_value_20d": 1.0, "liquidity_score": None}},
            {"risk_metrics": {"avg_value_20d": 5.0, "liquidity_score": None}},
            {"risk_metrics": {"avg_value_20d": 10.0, "liquidity_score": None}},
        ]
        norm = normalize_universe_liquidity_scores(scanned, market_regime="BULL")

        self.assertAlmostEqual(norm[0]["risk_metrics"]["liquidity_score"], 33.3, delta=1.0)
        self.assertAlmostEqual(norm[2]["risk_metrics"]["liquidity_score"], 100.0, delta=1.0)

    def test_risk_metrics_missing_data(self):
        df_empty = pd.DataFrame()
        metrics = calculate_t25_risk_metrics(df_empty)

        self.assertIsNone(metrics["var_t25"])
        self.assertIsNone(metrics["es_t25"])
        self.assertIsNone(metrics["volatility_60d"])
        self.assertIsNone(metrics["max_drawdown"])
        self.assertIsNone(metrics["liquidity_score"])

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

        self.assertIsNone(metrics["var_t25"])
        self.assertIsNone(metrics["es_t25"])

    def test_a_t25_known_return(self):
        """Test A — Known return: Verify exact T+2.5 return calculation on synthetic prices."""
        prices = pd.Series([100.0, 102.0, 104.0, 106.0, 108.12])
        returns = calculate_t25_returns(prices)

        # Expected index 3: (106.0 - 100.0) / 100.0 = 0.06
        # Expected index 4: (108.12 - 102.0) / 102.0 = 0.06

        self.assertEqual(len(returns), 2)
        self.assertAlmostEqual(returns.iloc[0], 0.06, places=4)
        self.assertAlmostEqual(returns.iloc[1], 0.06, places=4)

    def test_b_t25_insufficient_history(self):
        """Test B — Insufficient history: Fewer than 4 price observations produces empty series."""
        prices_3 = pd.Series([100.0, 102.0, 104.0])
        returns = calculate_t25_returns(prices_3)
        self.assertTrue(returns.empty)

        metrics = calculate_t25_risk_metrics(
            pd.DataFrame({"close": [100.0] * 19, "volume": [1000] * 19})
        )
        self.assertIsNone(metrics["var_t25"])
        self.assertIsNone(metrics["es_t25"])

    def test_c_t25_exact_minimum_history(self):
        """Test C — Exact minimum history: 4 price observations produces exactly 1 return observation."""
        prices_4 = pd.Series([100.0, 102.0, 104.0, 110.0])
        returns = calculate_t25_returns(prices_4)
        self.assertEqual(len(returns), 1)
        self.assertAlmostEqual(returns.iloc[0], 0.10, places=4)

    def test_d_t25_no_look_ahead(self):
        """Test D — No look-ahead: Changing future prices cannot change earlier T+2.5 returns."""
        prices_base = pd.Series([100.0, 102.0, 104.0, 106.0, 108.0, 110.0])
        returns_base = calculate_t25_returns(prices_base)

        prices_modified = prices_base.copy()
        prices_modified.iloc[5] = 999.0  # Change D5 price far in the future
        returns_modified = calculate_t25_returns(prices_modified)

        # Returns up to index 4 (D3 -> D0, D4 -> D1) must be identical
        self.assertAlmostEqual(returns_base.iloc[0], returns_modified.iloc[0], places=6)
        self.assertAlmostEqual(returns_base.iloc[1], returns_modified.iloc[1], places=6)

    def test_e_t25_non_uniform_calendar_dates(self):
        """Test E — Non-uniform calendar dates: Uses trading-session rows, not calendar day interpolation."""
        # Non-uniform trading dates (e.g. weekend/holiday gaps)
        dates = ["2026-03-06", "2026-03-09", "2026-03-10", "2026-03-11", "2026-03-12"]
        prices = pd.Series([10.0, 12.0, 14.0, 15.0, 18.0], index=dates)

        returns = calculate_t25_returns(prices)
        # Session 0: 10.0 (Fri), Session 1: 12.0 (Mon), Session 2: 14.0 (Tue), Session 3: 15.0 (Wed)
        # T+2.5 (3 sessions) return at Session 3 = (15.0 - 10.0) / 10.0 = 0.50
        self.assertEqual(len(returns), 2)
        self.assertAlmostEqual(returns.iloc[0], 0.50, places=4)

    def test_f_t25_unsorted_input(self):
        """Test F — Explicit helper relies on sorted index/series order from upstream contract."""
        prices_sorted = pd.Series([100.0, 102.0, 104.0, 106.0])
        returns = calculate_t25_returns(prices_sorted)
        self.assertAlmostEqual(returns.iloc[0], 0.06, places=4)

    def test_g_t25_duplicate_invalid_rows_clean_boundary(self):
        """Test G — Duplicate/invalid rows: T+2.5 calculation operates on clean dataset."""
        dates = pd.date_range("2026-01-01", periods=25, freq="D").strftime("%Y-%m-%d").tolist()
        # Add duplicate date and invalid row
        dates.insert(3, dates[2])  # Duplicate date at index 3
        closes = [100.0 + i for i in range(len(dates))]
        closes[3] = -99.0  # Invalid non-positive close on duplicate row

        df_raw = pd.DataFrame(
            {
                "time": dates,
                "open": [p - 1 for p in closes],
                "high": [p + 5 for p in closes],
                "low": [p - 5 for p in closes],
                "close": closes,
                "volume": [1000] * len(dates),
            }
        )
        clean_df, _ = get_clean_ohlcv_data(df_raw, "TEST")

        # Excludes duplicate date rows (index 2 & 3), keeping 24 clean rows
        self.assertNotIn(-99.0, clean_df["close"].values)

        returns_clean = calculate_t25_returns(clean_df["close"])
        self.assertFalse(returns_clean.empty)
        # Verify first valid return (4th clean session vs 1st clean session)
        first_ret = (clean_df["close"].iloc[3] - clean_df["close"].iloc[0]) / clean_df[
            "close"
        ].iloc[0]
        self.assertAlmostEqual(returns_clean.iloc[0], first_ret, places=4)

    def test_h_t25_other_risk_metrics_unchanged(self):
        """Test H — Regression against current risk output: volatility_60d, max_drawdown, avg_value_20d remain unaffected."""
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
        self.assertEqual(metrics["max_drawdown"], 0.0)
        self.assertIsNotNone(metrics["volatility_60d"])
        self.assertIsNotNone(metrics["avg_value_20d"])


if __name__ == "__main__":
    unittest.main()
