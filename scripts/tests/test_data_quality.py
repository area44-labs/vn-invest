"""Deterministic Unit Tests for OHLCV Data Quality Gate.

Covers Tests A through I without live API dependencies.
"""

import unittest

import pandas as pd

from scripts.lib.recommendation import generate_recommendation
from scripts.lib.vietnam_market import validate_ohlcv_data


def make_valid_df(num_rows: int = 30) -> pd.DataFrame:
    """Helper to construct a valid EOD OHLCV DataFrame."""
    dates = pd.date_range(end="2026-09-11", periods=num_rows, freq="D").strftime("%Y-%m-%d")
    data = []
    base_price = 30.0
    for i, d in enumerate(dates):
        p = base_price + (i * 0.1)
        data.append(
            {
                "time": d,
                "open": p,
                "high": p + 0.5,
                "low": p - 0.5,
                "close": p + 0.2,
                "volume": 100000 + (i * 1000),
            }
        )
    return pd.DataFrame(data)


class TestDataQualityGate(unittest.TestCase):
    def test_a_empty_data(self):
        """Test A — Empty data DataFrame -> INSUFFICIENT."""
        res_none = validate_ohlcv_data(None)
        self.assertEqual(res_none["status"], "INSUFFICIENT")
        self.assertIn("empty_dataframe", res_none["issues"])

        res_empty = validate_ohlcv_data(pd.DataFrame())
        self.assertEqual(res_empty["status"], "INSUFFICIENT")
        self.assertIn("empty_dataframe", res_empty["issues"])

    def test_b_missing_required_column(self):
        """Test B — Missing required column -> INSUFFICIENT."""
        df = make_valid_df(30)
        df_no_close = df.drop(columns=["close"])
        res = validate_ohlcv_data(df_no_close)
        self.assertEqual(res["status"], "INSUFFICIENT")
        self.assertIn("missing_required_columns", res["issues"])

        df_no_date = df.drop(columns=["time"])
        res_date = validate_ohlcv_data(df_no_date)
        self.assertEqual(res_date["status"], "INSUFFICIENT")
        self.assertIn("missing_date_column", res_date["issues"])

    def test_c_invalid_numeric_value(self):
        """Test C — Invalid numeric value -> validation failure."""
        df = make_valid_df(30)
        df.loc[5, "close"] = "abc"
        res = validate_ohlcv_data(df)
        self.assertIn("non_numeric_values", res["issues"])
        self.assertIn("nan_values", res["issues"])

    def test_d_nan(self):
        """Test D — NaN in OHLCV -> validation failure / PARTIAL according to defined contract."""
        df = make_valid_df(30)
        df.loc[10, "volume"] = None
        res = validate_ohlcv_data(df)
        self.assertIn("nan_values", res["issues"])
        self.assertEqual(res["status"], "PARTIAL")

    def test_e_invalid_ohlc_relationship(self):
        """Test E — Invalid OHLC relationship -> invalid row detected."""
        df = make_valid_df(30)
        # high < close
        df.loc[8, "high"] = 20.0
        df.loc[8, "close"] = 35.0
        res = validate_ohlcv_data(df)
        self.assertIn("invalid_ohlc_relationship", res["issues"])

    def test_f_negative_volume(self):
        """Test F — Negative volume -> invalid."""
        df = make_valid_df(30)
        df.loc[12, "volume"] = -500
        res = validate_ohlcv_data(df)
        self.assertIn("negative_volume", res["issues"])

    def test_g_duplicate_dates(self):
        """Test G — Duplicate dates -> duplicate_dates detected."""
        df = make_valid_df(30)
        df.loc[15, "time"] = df.loc[14, "time"]
        res = validate_ohlcv_data(df)
        self.assertIn("duplicate_dates", res["issues"])

    def test_h_valid_dataset(self):
        """Test H — Valid dataset returns expected SUFFICIENT quality status."""
        df = make_valid_df(30)
        res = validate_ohlcv_data(df)
        self.assertEqual(res["status"], "SUFFICIENT")
        self.assertEqual(res["issues"], [])
        self.assertEqual(res["valid_row_count"], 30)
        self.assertEqual(res["latest_date"], "2026-09-11")

    def test_i_invalid_dataset_cannot_produce_normal_recommendation(self):
        """Test I — Invalid dataset cannot produce normal recommendation."""
        regime_info = {"regime": "STRONG_BULL", "confidence": 0.8}

        # Case 1: Insufficient history (< 20 rows)
        df_short = make_valid_df(10)
        rec_short = generate_recommendation(
            symbol="ABC",
            company_name="Test Co",
            sector="Finance",
            exchange="HOSE",
            df_stock=df_short,
            market_regime_info=regime_info,
        )
        self.assertEqual(rec_short["action"], "AVOID")
        self.assertIsNone(rec_short["signal_score"])
        self.assertIsNone(rec_short["risk_adjusted_score"])
        self.assertEqual(rec_short["data_quality"], "INSUFFICIENT")
        self.assertIn("insufficient_history", rec_short["data_quality_issues"])

        # Case 2: Missing required column
        df_invalid = make_valid_df(30).drop(columns=["close"])
        rec_invalid = generate_recommendation(
            symbol="XYZ",
            company_name="Test Co 2",
            sector="Tech",
            exchange="HOSE",
            df_stock=df_invalid,
            market_regime_info=regime_info,
        )
        self.assertEqual(rec_invalid["action"], "AVOID")
        self.assertIsNone(rec_invalid["signal_score"])
        self.assertIsNone(rec_invalid["risk_adjusted_score"])
        self.assertEqual(rec_invalid["data_quality"], "INSUFFICIENT")
        self.assertIn("missing_required_columns", rec_invalid["data_quality_issues"])


if __name__ == "__main__":
    unittest.main()
