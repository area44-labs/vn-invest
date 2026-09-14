"""Comprehensive Deterministic Unit Tests for OHLCV Data Quality Gate.

Covers Tests A through M without live API dependencies.
"""

import unittest

import pandas as pd

from scripts.lib.recommendation import generate_recommendation
from scripts.lib.vietnam_market import get_clean_ohlcv_data, validate_ohlcv_data


def make_valid_df(num_rows: int = 30, start_date: str = "2026-08-01") -> pd.DataFrame:
    """Helper to construct a valid EOD OHLCV DataFrame."""
    dates = pd.date_range(start=start_date, periods=num_rows, freq="D").strftime("%Y-%m-%d")
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
        """Test C — Invalid numeric value -> invalid row excluded from clean dataset."""
        df = make_valid_df(30)
        df.loc[5, "close"] = "abc"
        res = validate_ohlcv_data(df)
        self.assertIn("non_numeric_values", res["issues"])
        self.assertIn("nan_values", res["issues"])
        self.assertEqual(res["valid_row_count"], 29)
        self.assertNotIn(df.loc[5, "time"], res["clean_df"]["time"].values)

    def test_d_nan(self):
        """Test D — NaN in OHLCV -> invalid row excluded from clean dataset."""
        df = make_valid_df(30)
        df.loc[10, "volume"] = None
        res = validate_ohlcv_data(df)
        self.assertIn("nan_values", res["issues"])
        self.assertEqual(res["status"], "PARTIAL")
        self.assertEqual(res["valid_row_count"], 29)
        self.assertNotIn(df.loc[10, "time"], res["clean_df"]["time"].values)

    def test_e_invalid_ohlc_relationship(self):
        """Test E — Invalid OHLC relationship -> invalid row excluded."""
        df = make_valid_df(30)
        # high < close
        df.loc[8, "high"] = 20.0
        df.loc[8, "close"] = 35.0
        res = validate_ohlcv_data(df)
        self.assertIn("invalid_ohlc_relationship", res["issues"])
        self.assertEqual(res["valid_row_count"], 29)
        self.assertNotIn(df.loc[8, "time"], res["clean_df"]["time"].values)

    def test_f_negative_volume(self):
        """Test F — Negative volume -> invalid row excluded."""
        df = make_valid_df(30)
        df.loc[12, "volume"] = -500
        res = validate_ohlcv_data(df)
        self.assertIn("negative_volume", res["issues"])
        self.assertEqual(res["valid_row_count"], 29)
        self.assertNotIn(df.loc[12, "time"], res["clean_df"]["time"].values)

    def test_g_duplicate_dates(self):
        """Test G — Duplicate dates -> duplicate_dates, duplicate observations excluded."""
        df = make_valid_df(30)
        df.loc[15, "time"] = df.loc[14, "time"]
        res = validate_ohlcv_data(df)
        self.assertIn("duplicate_dates", res["issues"])
        # Both occurrences of the duplicated date must be excluded
        dup_date = df.loc[14, "time"]
        self.assertNotIn(dup_date, res["clean_df"]["time"].values)

    def test_h_valid_dataset(self):
        """Test H — Valid dataset returns expected SUFFICIENT quality status."""
        df = make_valid_df(30, start_date="2026-08-01")
        res = validate_ohlcv_data(df)
        self.assertEqual(res["status"], "SUFFICIENT")
        self.assertEqual(res["issues"], [])
        self.assertEqual(res["valid_row_count"], 30)
        self.assertEqual(res["latest_date"], "2026-08-30")

    def test_i_partial_dataset_pipeline_behavior(self):
        """Test I — PARTIAL dataset (30 valid rows + 1 invalid row).

        Verifies status is PARTIAL, invalid row is excluded, and downstream calculations proceed on clean_df.
        """
        df = make_valid_df(31, start_date="2026-08-01")
        # Introduce 1 invalid row at index 15
        invalid_time = df.loc[15, "time"]
        df.loc[15, "close"] = -10.0

        clean_df, res = get_clean_ohlcv_data(df, "TEST")
        self.assertEqual(res["status"], "PARTIAL")
        self.assertEqual(res["valid_row_count"], 30)
        self.assertNotIn(invalid_time, clean_df["time"].values)

        # Test actual recommendation generation pipeline with this PARTIAL dataset
        regime_info = {"regime": "BULL", "confidence": 0.8}
        rec = generate_recommendation(
            symbol="TEST",
            company_name="Test Company",
            sector="Finance",
            exchange="HOSE",
            df_stock=df,
            market_regime_info=regime_info,
        )
        self.assertEqual(rec["data_quality"], "PARTIAL")
        self.assertIn("non_positive_prices", rec["data_quality_issues"])
        self.assertIsNotNone(rec["signal_score"])
        self.assertIsNotNone(rec["risk_adjusted_score"])

    def test_j_partial_raw_insufficient_clean_rows(self):
        """Test J — Raw dataset with 21 rows but 5 invalid rows (16 valid rows remaining) -> INSUFFICIENT."""
        df = make_valid_df(21)
        for idx in range(5):
            df.loc[idx, "close"] = -5.0

        res = validate_ohlcv_data(df)
        self.assertEqual(res["valid_row_count"], 16)
        self.assertEqual(res["status"], "INSUFFICIENT")
        self.assertIn("insufficient_history", res["issues"])

    def test_k_no_normal_recommendation_from_insufficient_data(self):
        """Test K — Insufficient data produces non-actionable recommendation with null scores."""
        df_short = make_valid_df(10)
        regime_info = {"regime": "STRONG_BULL", "confidence": 0.9}
        rec = generate_recommendation(
            symbol="ABC",
            company_name="Short History Co",
            sector="Technology",
            exchange="HOSE",
            df_stock=df_short,
            market_regime_info=regime_info,
        )
        self.assertEqual(rec["action"], "AVOID")
        self.assertIsNone(rec["signal_score"])
        self.assertIsNone(rec["risk_adjusted_score"])
        self.assertEqual(rec["data_quality"], "INSUFFICIENT")

    def test_l_data_as_of_uses_latest_usable_date(self):
        """Test L — data_as_of uses latest usable valid date when latest raw row is invalid."""
        df = make_valid_df(30, start_date="2026-08-01")
        # Make the latest raw row invalid (e.g. close <= 0)
        latest_raw_date = df.iloc[-1]["time"]
        expected_usable_date = df.iloc[-2]["time"]
        df.loc[df.index[-1], "close"] = 0.0

        res = validate_ohlcv_data(df)
        self.assertEqual(res["latest_date"], expected_usable_date)
        self.assertNotEqual(res["latest_date"], latest_raw_date)

        regime_info = {"regime": "NEUTRAL", "confidence": 0.7}
        rec = generate_recommendation(
            symbol="LATEST",
            company_name="Latest Test Co",
            sector="Energy",
            exchange="HOSE",
            df_stock=df,
            market_regime_info=regime_info,
        )
        self.assertEqual(rec["data_as_of"], expected_usable_date)

    def test_m_raw_data_is_not_mutated(self):
        """Test M — Validation and cleaning never mutate the original raw DataFrame."""
        df_orig = make_valid_df(30)
        df_orig.loc[5, "close"] = -99.0
        df_orig.loc[10, "high"] = 1.0
        df_orig.loc[10, "close"] = 100.0
        df_copy = df_orig.copy(deep=True)

        _res = validate_ohlcv_data(df_orig, "MUTATE_TEST")

        pd.testing.assert_frame_equal(df_orig, df_copy)


if __name__ == "__main__":
    unittest.main()
