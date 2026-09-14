"""Unit tests for Market Data Unit Normalization (PR #71)."""

import unittest

import numpy as np
import pandas as pd

from scripts.lib.risk import (
    calculate_t25_risk_metrics,
    normalize_universe_liquidity_scores,
)
from scripts.lib.vietnam_market import (
    AVG_TRADING_VALUE_UNIT,
    PRICE_UNIT,
    TRADING_VALUE_UNIT,
    VOLUME_UNIT,
    normalize_ohlcv_units,
)


class TestUnitNormalization(unittest.TestCase):
    def test_unit_constants(self):
        """Verify canonical internal unit contract metadata constants."""
        self.assertEqual(PRICE_UNIT, "VND/share")
        self.assertEqual(VOLUME_UNIT, "shares")
        self.assertEqual(TRADING_VALUE_UNIT, "VND")
        self.assertEqual(AVG_TRADING_VALUE_UNIT, "billion_VND")

    def test_a_explicit_vnd_price(self):
        """Test A — Explicit VND price (50,000 VND/share, 1,000,000 shares -> 50.0 billion VND)."""
        n = 20
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        df = pd.DataFrame(
            {
                "time": dates,
                "open": [50000.0] * n,
                "high": [51000.0] * n,
                "low": [49000.0] * n,
                "close": [50000.0] * n,
                "volume": [1000000.0] * n,
            }
        )
        metrics = calculate_t25_risk_metrics(df)
        self.assertEqual(metrics["avg_value_20d"], 50.0)

    def test_b_no_magnitude_heuristic(self):
        """Test B — Verification that unit conversion strictly follows declared source contract, not numeric thresholds."""
        # Low stock price (e.g. 500 VND = penny stock or split stock) with explicit source unit "thousand_VND/share"
        df_low = pd.DataFrame(
            {
                "open": [0.5],
                "high": [0.52],
                "low": [0.48],
                "close": [0.5],
                "volume": [1000.0],
            }
        )
        norm_low = normalize_ohlcv_units(df_low, source_price_unit="thousand_VND/share")
        # 0.5 thousand VND -> 500.0 VND/share regardless of how low 0.5 looks
        self.assertEqual(norm_low["close"].iloc[0], 500.0)

        # Dataset already in VND/share with source_price_unit="VND/share"
        df_already_vnd = pd.DataFrame(
            {
                "open": [500.0],
                "high": [520.0],
                "low": [480.0],
                "close": [500.0],
                "volume": [1000.0],
            }
        )
        norm_already_vnd = normalize_ohlcv_units(df_already_vnd, source_price_unit="VND/share")
        self.assertEqual(norm_already_vnd["close"].iloc[0], 500.0)

    def test_c_volume_unit(self):
        """Test C — Volume unit (1,000,000 shares remains 1,000,000 shares without magnitude scaling)."""
        df = pd.DataFrame({"close": [50000.0], "volume": [1000000.0]})
        norm = normalize_ohlcv_units(df, source_volume_unit="shares")
        self.assertEqual(norm["volume"].iloc[0], 1000000.0)

    def test_d_trading_value_formula(self):
        """Test D — Trading value formula (price 30,000 x volume 2,000,000 = 60,000,000,000 VND = 60 billion VND)."""
        n = 20
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        df = pd.DataFrame(
            {
                "time": dates,
                "close": [30000.0] * n,
                "volume": [2000000.0] * n,
            }
        )
        metrics = calculate_t25_risk_metrics(df)
        trading_value_vnd = df["close"].iloc[0] * df["volume"].iloc[0]
        self.assertEqual(trading_value_vnd, 60_000_000_000.0)
        self.assertEqual(metrics["avg_value_20d"], 60.0)

    def test_e_20_day_average(self):
        """Test E — 20-day average trading value exact calculation."""
        n = 20
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        # Prices linearly increasing from 20,000 to 39,000
        prices = np.linspace(20000.0, 39000.0, n)
        volumes = [1000000.0] * n
        df = pd.DataFrame({"time": dates, "close": prices, "volume": volumes})

        expected_trading_values = prices * volumes
        expected_avg_bn = round(float(expected_trading_values.mean()) / 1e9, 2)

        metrics = calculate_t25_risk_metrics(df)
        self.assertEqual(metrics["avg_value_20d"], expected_avg_bn)

    def test_f_risk_calculations_unaffected(self):
        """Test F — Risk calculations (VaR, ES, Volatility, MDD) are unaffected by canonical prices."""
        n = 60
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        close_prices = 50000.0 + np.cumsum(np.random.normal(0, 500.0, n))
        close_prices = np.clip(close_prices, 10000.0, 100000.0)
        df = pd.DataFrame(
            {
                "time": dates,
                "open": close_prices - 100.0,
                "high": close_prices + 500.0,
                "low": close_prices - 500.0,
                "close": close_prices,
                "volume": [100000.0] * n,
            }
        )
        metrics = calculate_t25_risk_metrics(df)
        self.assertIsNotNone(metrics["var_t25"])
        self.assertIsNotNone(metrics["es_t25"])
        self.assertIsNotNone(metrics["volatility_60d"])
        self.assertIsNotNone(metrics["max_drawdown"])

    def test_g_liquidity_score(self):
        """Test G — Liquidity score percentile ranking continues to work on normalized billion-VND values."""
        scanned = [
            {"risk_metrics": {"avg_value_20d": 10.0, "liquidity_score": None}},
            {"risk_metrics": {"avg_value_20d": 50.0, "liquidity_score": None}},
            {"risk_metrics": {"avg_value_20d": 100.0, "liquidity_score": None}},
        ]
        norm = normalize_universe_liquidity_scores(scanned, market_regime="BULL")
        self.assertAlmostEqual(norm[0]["risk_metrics"]["liquidity_score"], 33.3, delta=1.0)
        self.assertAlmostEqual(norm[2]["risk_metrics"]["liquidity_score"], 100.0, delta=1.0)


if __name__ == "__main__":
    unittest.main()
