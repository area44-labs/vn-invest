"""Comprehensive Deterministic Unit Tests for OHLCV Data Quality Gate and Point-in-Time Universe.

Covers Tests A through M without live API dependencies.
"""

import unittest
from unittest.mock import patch

import pandas as pd

from scripts.generate_report import run_pipeline
from scripts.lib.recommendation import generate_recommendation
from scripts.lib.regime import detect_market_regime
from scripts.lib.vietnam_market import UniverseProvider, get_clean_ohlcv_data, validate_ohlcv_data


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
        df["close"] = df["close"].astype(object)
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


class TestHistoricalUniversePIT(unittest.TestCase):
    def test_point_in_time_universe_membership(self):
        """Verify Universe(as_of=T1) != Universe(as_of=T2) when symbol listing bounds change."""
        up = UniverseProvider()
        # Add a custom delisted candidate with valid_to
        up.candidates.append(
            {
                "symbol": "OLD_CO",
                "companyName": "Delisted Company",
                "sector": "Industrials",
                "exchange": "HOSE",
                "valid_from": "2020-01-01",
                "valid_to": "2024-12-31",
                "listing_status": "delisted",
            }
        )

        u_2022 = up.get_as_of_universe("2022-06-01")
        u_2025 = up.get_as_of_universe("2025-06-01")

        symbols_2022 = [c["symbol"] for c in u_2022]
        symbols_2025 = [c["symbol"] for c in u_2025]

        self.assertIn("OLD_CO", symbols_2022)
        self.assertNotIn("OLD_CO", symbols_2025)
        self.assertNotEqual(symbols_2022, symbols_2025)


class TestMarketCleanDataBoundary(unittest.TestCase):
    def test_a_invalid_latest_vnindex_row(self):
        """Test A — Invalid latest VNINDEX row: data_as_of uses latest clean valid date (2026-09-11), not invalid date (2026-09-12)."""
        df_raw = make_valid_df(30, start_date="2026-08-14")
        df_raw.loc[29, "close"] = -100.0

        clean_df, val_res = get_clean_ohlcv_data(df_raw, "VNINDEX")

        self.assertEqual(val_res["latest_date"], "2026-09-11")
        self.assertNotIn("2026-09-12", clean_df["time"].values)

        with patch("scripts.generate_report.get_historical_data") as mock_get:

            def side_effect(symbol, **_kwargs):
                if symbol == "VNINDEX":
                    return df_raw, "REAL_DATA", []
                elif symbol == "VN30":
                    return make_valid_df(30), "REAL_DATA", []
                else:
                    return make_valid_df(30), "REAL_DATA", []

            mock_get.side_effect = side_effect

            recs_data, market_data, _ = run_pipeline(update_data=False)
            self.assertEqual(recs_data["data_as_of"], "2026-09-11")
            self.assertEqual(market_data["data_as_of"], "2026-09-11")
            self.assertNotEqual(recs_data["data_as_of"], "2026-09-12")

    def test_b_duplicate_benchmark_date(self):
        """Test B — Duplicate benchmark date: all duplicate occurrences excluded from clean data, data_as_of and regime unaffected by excluded duplicates."""
        df_raw = make_valid_df(30, start_date="2026-08-01")
        dup_date = df_raw.loc[14, "time"]
        df_raw.loc[15, "time"] = dup_date

        clean_df, val_res = get_clean_ohlcv_data(df_raw, "VNINDEX")
        self.assertIn("duplicate_dates", val_res["issues"])
        self.assertNotIn(dup_date, clean_df["time"].values)

        regime = detect_market_regime(df_vnindex=clean_df)
        self.assertIsNotNone(regime["regime"])
        self.assertNotEqual(val_res["latest_date"], dup_date)

    def test_c_invalid_historical_row_does_not_affect_regime(self):
        """Test C — Invalid historical row: one invalid row that would materially change MA/return calculation if included does not affect regime(clean_df)."""
        df_raw = make_valid_df(30, start_date="2026-08-01")
        df_raw.loc[15, "close"] = -999.0

        clean_df, _val_res = get_clean_ohlcv_data(df_raw, "VNINDEX")

        regime_clean = detect_market_regime(df_vnindex=clean_df)
        self.assertGreater(regime_clean["metrics"]["vnindex_value"], 0)
        self.assertNotIn(-999.0, clean_df["close"].values)

    def test_d_partial_benchmark(self):
        """Test D — PARTIAL benchmark: fixture with >=20 valid rows + >=1 invalid row results in status PARTIAL and market calculations consume clean_df only."""
        df_raw = make_valid_df(30, start_date="2026-08-01")
        df_raw.loc[5, "high"] = 10.0

        clean_df, val_res = get_clean_ohlcv_data(df_raw, "VNINDEX")
        self.assertEqual(val_res["status"], "PARTIAL")
        self.assertEqual(len(clean_df), 29)

        regime = detect_market_regime(df_vnindex=clean_df)
        self.assertIn(regime["regime"], ["STRONG_BULL", "BULL", "NEUTRAL", "DEFENSIVE", "BEAR", "PANIC"])

    def test_e_insufficient_clean_benchmark(self):
        """Test E — Insufficient clean benchmark: fixture with >=20 raw rows but <20 valid rows produces INSUFFICIENT status and graceful fallback."""
        df_raw = make_valid_df(25, start_date="2026-08-01")
        for i in range(10):
            df_raw.loc[i, "close"] = -1.0

        clean_df, val_res = get_clean_ohlcv_data(df_raw, "VNINDEX")
        self.assertEqual(val_res["status"], "INSUFFICIENT")
        self.assertEqual(len(clean_df), 15)

        regime = detect_market_regime(df_vnindex=clean_df)
        self.assertEqual(regime["regime"], "DEFENSIVE")
        self.assertEqual(regime["confidence"], 0.40)
        self.assertIsNone(regime["metrics"]["vnindex_value"])

    def test_f_no_mutation(self):
        """Test F — No mutation: Raw VNINDEX/VN30 DataFrames remain unchanged after validation and cleaning."""
        df_vnindex_raw = make_valid_df(30, start_date="2026-08-01")
        df_vnindex_raw.loc[5, "close"] = -50.0
        df_vn30_raw = make_valid_df(30, start_date="2026-08-01")
        df_vn30_raw.loc[10, "volume"] = -100.0

        copy_vnindex = df_vnindex_raw.copy(deep=True)
        copy_vn30 = df_vn30_raw.copy(deep=True)

        _clean_vnindex, _val_vnindex = get_clean_ohlcv_data(df_vnindex_raw, "VNINDEX")
        _clean_vn30, _val_vn30 = get_clean_ohlcv_data(df_vn30_raw, "VN30")

        pd.testing.assert_frame_equal(df_vnindex_raw, copy_vnindex)
        pd.testing.assert_frame_equal(df_vn30_raw, copy_vn30)


if __name__ == "__main__":
    unittest.main()
