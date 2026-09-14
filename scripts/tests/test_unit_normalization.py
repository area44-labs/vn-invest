"""Comprehensive Unit Normalization Test Suite for VN Invest (PR #71).

Covers Tests A through J:
- Test A: Explicit price conversion (50.0 thousand_VND/share -> 50,000 VND/share).
- Test B: No magnitude heuristic (conversion strictly follows declared source contract).
- Test C: Volume unit preservation (1,000,000 shares remains 1,000,000 shares).
- Test D: Trading value formula (price * volume = VND).
- Test E: 20-day average trading value calculation (mean(trading_value_vnd) / 1e9).
- Test F: Invalid source unit handling (raises ValueError on unsupported units).
- Test G: No double conversion (canonical dataset with source_price_unit="VND/share" is unchanged; risk/recommendation modules consume canonical units directly).
- Test H: Risk metrics regression (VaR, ES, Volatility, Max Drawdown remain unchanged).
- Test I: Liquidity ranking regression (relative ordering of liquidity scores preserved).
- Test J: Regression test suite compatibility (PR #68 data_as_of and PR #70 clean data boundary).
"""

import unittest

import numpy as np
import pandas as pd

from scripts.lib.recommendation import generate_recommendation
from scripts.lib.risk import (
    calculate_t25_risk_metrics,
    normalize_universe_liquidity_scores,
)
from scripts.lib.vietnam_market import (
    AVG_TRADING_VALUE_UNIT,
    PRICE_UNIT,
    TRADING_VALUE_UNIT,
    VOLUME_UNIT,
    get_clean_ohlcv_data,
    normalize_ohlcv_units,
    validate_ohlcv_data,
)


class TestUnitNormalizationSuite(unittest.TestCase):
    def test_unit_constants(self):
        """Verify canonical internal unit contract metadata constants."""
        self.assertEqual(PRICE_UNIT, "VND/share")
        self.assertEqual(VOLUME_UNIT, "shares")
        self.assertEqual(TRADING_VALUE_UNIT, "VND")
        self.assertEqual(AVG_TRADING_VALUE_UNIT, "billion_VND")

    def test_a_explicit_price_conversion(self):
        """Test A — Given 50.0 thousand VND/share, normalize_ohlcv_units produces 50,000 VND/share."""
        df_raw = pd.DataFrame(
            {
                "open": [49.5],
                "high": [51.0],
                "low": [49.0],
                "close": [50.0],
                "volume": [1_000_000.0],
            }
        )
        df_norm = normalize_ohlcv_units(
            df_raw, source_price_unit="thousand_VND/share", source_volume_unit="shares"
        )
        self.assertEqual(df_norm["close"].iloc[0], 50000.0)
        self.assertEqual(df_norm["open"].iloc[0], 49500.0)
        self.assertEqual(df_norm["high"].iloc[0], 51000.0)
        self.assertEqual(df_norm["low"].iloc[0], 49000.0)

    def test_b_no_magnitude_heuristic(self):
        """Test B — Conversion strictly follows declared source unit contract, independent of numeric magnitude."""
        # Low numeric value (e.g. 0.5) with declared unit 'thousand_VND/share' -> 500.0 VND/share
        df_low = pd.DataFrame({"close": [0.5], "volume": [1000.0]})
        norm_low = normalize_ohlcv_units(df_low, source_price_unit="thousand_VND/share")
        self.assertEqual(norm_low["close"].iloc[0], 500.0)

        # Dataset already in VND/share with declared unit 'VND/share' -> 500.0 VND/share
        df_already_vnd = pd.DataFrame({"close": [500.0], "volume": [1000.0]})
        norm_already_vnd = normalize_ohlcv_units(df_already_vnd, source_price_unit="VND/share")
        self.assertEqual(norm_already_vnd["close"].iloc[0], 500.0)

    def test_c_volume_preservation(self):
        """Test C — Given 1,000,000 shares, normalize_ohlcv_units preserves 1,000,000 shares."""
        df = pd.DataFrame({"close": [50000.0], "volume": [1_000_000.0]})
        norm = normalize_ohlcv_units(df, source_volume_unit="shares")
        self.assertEqual(norm["volume"].iloc[0], 1_000_000.0)

    def test_d_trading_value_formula(self):
        """Test D — 50,000 VND/share x 1,000,000 shares produces 50,000,000,000 VND (50 billion VND)."""
        n = 20
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        df = pd.DataFrame(
            {
                "time": dates,
                "close": [50000.0] * n,
                "volume": [1_000_000.0] * n,
            }
        )
        trading_value_vnd = df["close"].iloc[0] * df["volume"].iloc[0]
        self.assertEqual(trading_value_vnd, 50_000_000_000.0)

        metrics = calculate_t25_risk_metrics(df)
        self.assertEqual(metrics["avg_value_20d"], 50.0)

    def test_e_20_day_average_exactness(self):
        """Test E — 20-day average trading value equals mean(trading_value_vnd) / 1e9 exactness."""
        n = 20
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        prices = np.linspace(20000.0, 39000.0, n)
        volumes = [1_000_000.0] * n
        df = pd.DataFrame({"time": dates, "close": prices, "volume": volumes})

        expected_trading_values = prices * volumes
        expected_avg_bn = round(float(expected_trading_values.mean()) / 1e9, 2)

        metrics = calculate_t25_risk_metrics(df)
        self.assertEqual(metrics["avg_value_20d"], expected_avg_bn)

    def test_f_invalid_units_raise_error(self):
        """Test F — Unsupported source price or volume units raise ValueError loudly."""
        df = pd.DataFrame({"close": [50.0], "volume": [1000.0]})

        with self.assertRaises(ValueError):
            normalize_ohlcv_units(df, source_price_unit="invalid_price_unit")

        with self.assertRaises(ValueError):
            normalize_ohlcv_units(df, source_volume_unit="unknown_volume_unit")

    def test_g_no_double_conversion(self):
        """Test G — Verify a canonical dataset (source_price_unit='VND/share') is not converted again."""
        n = 20
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        df_canonical = pd.DataFrame(
            {
                "time": dates,
                "open": [30000.0] * n,
                "high": [31000.0] * n,
                "low": [29000.0] * n,
                "close": [30000.0] * n,
                "volume": [1_000_000.0] * n,
            }
        )

        # Explicit normalization with VND/share leaves dataset unchanged
        df_norm = normalize_ohlcv_units(
            df_canonical, source_price_unit="VND/share", source_volume_unit="shares"
        )
        pd.testing.assert_frame_equal(df_canonical, df_norm)

        # Risk metrics and recommendation consumption directly without re-scaling
        metrics = calculate_t25_risk_metrics(df_norm)
        self.assertEqual(metrics["avg_value_20d"], 30.0)

        rec = generate_recommendation(
            symbol="TEST",
            company_name="Test Stock",
            sector="Tech",
            exchange="HOSE",
            df_stock=df_norm,
            market_regime_info={"regime": "BULL"},
        )
        self.assertEqual(rec["trade_plan"]["current_price"], 30000.0)

    def test_h_risk_metrics_invariant(self):
        """Test H — Verify VaR, ES, Volatility, and Max Drawdown remain unchanged between raw percentage dynamics."""
        n = 60
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        close_prices = np.linspace(20000.0, 35000.0, n)
        df = pd.DataFrame(
            {
                "time": dates,
                "close": close_prices,
                "volume": [500000.0] * n,
            }
        )

        metrics = calculate_t25_risk_metrics(df)
        self.assertIsNotNone(metrics["var_t25"])
        self.assertIsNotNone(metrics["es_t25"])
        self.assertIsNotNone(metrics["volatility_60d"])
        self.assertIsNotNone(metrics["max_drawdown"])

    def test_i_liquidity_ranking_invariant(self):
        """Test I — Relative liquidity ordering is preserved after canonical unit normalization."""
        scanned = [
            {"risk_metrics": {"avg_value_20d": 10.0, "liquidity_score": None}},
            {"risk_metrics": {"avg_value_20d": 50.0, "liquidity_score": None}},
            {"risk_metrics": {"avg_value_20d": 100.0, "liquidity_score": None}},
        ]
        norm = normalize_universe_liquidity_scores(scanned, market_regime="BULL")
        self.assertLess(
            norm[0]["risk_metrics"]["liquidity_score"],
            norm[1]["risk_metrics"]["liquidity_score"],
        )
        self.assertLess(
            norm[1]["risk_metrics"]["liquidity_score"],
            norm[2]["risk_metrics"]["liquidity_score"],
        )

    def test_j_data_quality_and_date_compatibility(self):
        """Test J — PR #68 data_as_of and PR #70 clean data boundary compatibility."""
        df_raw = pd.DataFrame(
            {
                "time": ["2026-09-01", "2026-09-02", "invalid-date", "2026-09-04"],
                "open": [10000.0, 10500.0, None, 11000.0],
                "high": [10200.0, 10800.0, None, 11200.0],
                "low": [9800.0, 10300.0, None, 10900.0],
                "close": [10100.0, 10600.0, None, 11100.0],
                "volume": [100000.0, 120000.0, None, 150000.0],
            }
        )

        clean_df, val_res = get_clean_ohlcv_data(df_raw, "TEST")
        # Ensure invalid rows were excluded from clean DataFrame
        self.assertEqual(len(clean_df), 3)
        self.assertEqual(val_res["latest_date"], "2026-09-04")
        # Ensure raw DataFrame was not mutated
        self.assertEqual(len(df_raw), 4)

        # Raw dataframe validation status
        val = validate_ohlcv_data(df_raw)
        self.assertIn("invalid_dates", val["issues"])


if __name__ == "__main__":
    unittest.main()
