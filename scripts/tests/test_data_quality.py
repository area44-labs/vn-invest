"""Comprehensive Deterministic Unit Tests for OHLCV Data Quality Gate.

Covers Tests A through M without live API dependencies.
"""

import unittest
from unittest.mock import patch

import pandas as pd

from scripts.generate_report import run_pipeline
from scripts.lib.recommendation import generate_recommendation
from scripts.lib.regime import detect_market_regime
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
        """Test C — Invalid numeric value -> fail closed, clean dataset empty."""
        df = make_valid_df(30)
        df["close"] = df["close"].astype(object)
        df.loc[5, "close"] = "abc"
        res = validate_ohlcv_data(df)
        self.assertIn("non_numeric_values", res["issues"])
        self.assertIn("nan_values", res["issues"])
        self.assertEqual(res["valid_row_count"], 0)
        self.assertTrue(res["clean_df"].empty)

    def test_d_nan(self):
        """Test D — NaN in OHLCV -> fail closed, clean dataset empty."""
        df = make_valid_df(30)
        df.loc[10, "volume"] = None
        res = validate_ohlcv_data(df)
        self.assertIn("nan_values", res["issues"])
        self.assertEqual(res["status"], "INSUFFICIENT")
        self.assertEqual(res["valid_row_count"], 0)
        self.assertTrue(res["clean_df"].empty)

    def test_e_invalid_ohlc_relationship(self):
        """Test E — Invalid OHLC relationship -> fail closed, clean dataset empty."""
        df = make_valid_df(30)
        # high < close
        df.loc[8, "high"] = 20.0
        df.loc[8, "close"] = 35.0
        res = validate_ohlcv_data(df)
        self.assertIn("invalid_ohlc_relationship", res["issues"])
        self.assertEqual(res["valid_row_count"], 0)
        self.assertTrue(res["clean_df"].empty)

    def test_f_negative_volume(self):
        """Test F — Negative volume -> fail closed, clean dataset empty."""
        df = make_valid_df(30)
        df.loc[12, "volume"] = -500
        res = validate_ohlcv_data(df)
        self.assertIn("negative_volume", res["issues"])
        self.assertEqual(res["valid_row_count"], 0)
        self.assertTrue(res["clean_df"].empty)

    def test_g_duplicate_dates(self):
        """Test G — Duplicate dates -> duplicate_dates, fail closed."""
        df = make_valid_df(30)
        df.loc[15, "time"] = df.loc[14, "time"]
        res = validate_ohlcv_data(df)
        self.assertIn("duplicate_dates", res["issues"])
        self.assertEqual(res["valid_row_count"], 0)
        self.assertTrue(res["clean_df"].empty)

    def test_h_valid_dataset(self):
        """Test H — Valid dataset returns expected SUFFICIENT quality status."""
        df = make_valid_df(30, start_date="2026-08-01")
        res = validate_ohlcv_data(df)
        self.assertEqual(res["status"], "SUFFICIENT")
        self.assertEqual(res["issues"], [])
        self.assertEqual(res["valid_row_count"], 30)
        self.assertEqual(res["latest_date"], "2026-08-30")

    def test_i_partial_dataset_pipeline_behavior(self):
        """Test I — Dataset with invalid row fails closed under hardened validation."""
        df = make_valid_df(31, start_date="2026-08-01")
        # Introduce 1 invalid row at index 15
        df.loc[15, "close"] = -10.0

        clean_df, res = get_clean_ohlcv_data(df, "TEST")
        self.assertEqual(res["status"], "INSUFFICIENT")
        self.assertEqual(res["valid_row_count"], 0)
        self.assertTrue(clean_df.empty)

        # Test actual recommendation generation pipeline with this dataset
        regime_info = {"regime": "BULL", "confidence": 0.8}
        rec = generate_recommendation(
            symbol="TEST",
            company_name="Test Company",
            sector="Finance",
            exchange="HOSE",
            df_stock=df,
            market_regime_info=regime_info,
        )
        self.assertEqual(rec["action"], "AVOID")
        self.assertEqual(rec["data_quality"], "INSUFFICIENT")
        self.assertIn("non_positive_prices", rec["data_quality_issues"])
        self.assertIsNone(rec["signal_score"])
        self.assertIsNone(rec["risk_adjusted_score"])

    def test_j_partial_raw_insufficient_clean_rows(self):
        """Test J — Raw dataset with non-positive prices fails closed -> INSUFFICIENT."""
        df = make_valid_df(21)
        for idx in range(5):
            df.loc[idx, "close"] = -5.0

        res = validate_ohlcv_data(df)
        self.assertEqual(res["valid_row_count"], 0)
        self.assertEqual(res["status"], "INSUFFICIENT")
        self.assertIn("non_positive_prices", res["issues"])

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
        """Test L — data_as_of remains None when market dataset has corrupted rows."""
        df = make_valid_df(30, start_date="2026-08-01")
        # Make the latest raw row invalid (e.g. close <= 0)
        df.loc[df.index[-1], "close"] = 0.0

        res = validate_ohlcv_data(df)
        self.assertIsNone(res["latest_date"])
        self.assertEqual(res["status"], "INSUFFICIENT")

        regime_info = {"regime": "NEUTRAL", "confidence": 0.7}
        rec = generate_recommendation(
            symbol="LATEST",
            company_name="Latest Test Co",
            sector="Energy",
            exchange="HOSE",
            df_stock=df,
            market_regime_info=regime_info,
        )
        self.assertEqual(rec["action"], "AVOID")

    def test_m_raw_data_is_not_mutated(self):
        """Test M — Validation and cleaning never mutate the original raw DataFrame."""
        df_orig = make_valid_df(30)
        df_orig.loc[5, "close"] = -99.0
        df_orig.loc[10, "high"] = 1.0
        df_orig.loc[10, "close"] = 100.0
        df_copy = df_orig.copy(deep=True)

        _res = validate_ohlcv_data(df_orig, "MUTATE_TEST")

        pd.testing.assert_frame_equal(df_orig, df_copy)


class TestMarketCleanDataBoundary(unittest.TestCase):
    def test_a_invalid_latest_vnindex_row(self):
        """Test A — Corrupted latest VNINDEX row fails validation fail-closed."""
        df_raw = make_valid_df(30, start_date="2026-08-14")
        df_raw.loc[29, "close"] = -100.0

        clean_df, val_res = get_clean_ohlcv_data(df_raw, "VNINDEX")

        self.assertIsNone(val_res["latest_date"])
        self.assertEqual(val_res["status"], "INSUFFICIENT")
        self.assertTrue(clean_df.empty)

    def test_b_duplicate_benchmark_date(self):
        """Test B — Duplicate benchmark date fails validation fail-closed."""
        df_raw = make_valid_df(30, start_date="2026-08-01")
        dup_date = df_raw.loc[14, "time"]
        df_raw.loc[15, "time"] = dup_date

        clean_df, val_res = get_clean_ohlcv_data(df_raw, "VNINDEX")
        self.assertIn("duplicate_dates", val_res["issues"])
        self.assertEqual(val_res["status"], "INSUFFICIENT")
        self.assertTrue(clean_df.empty)

    def test_c_invalid_historical_row_does_not_affect_regime(self):
        """Test C — Invalid historical row fails validation fail-closed."""
        df_raw = make_valid_df(30, start_date="2026-08-01")
        df_raw.loc[15, "close"] = -999.0

        clean_df, val_res = get_clean_ohlcv_data(df_raw, "VNINDEX")
        self.assertEqual(val_res["status"], "INSUFFICIENT")
        self.assertTrue(clean_df.empty)

    def test_e_insufficient_clean_benchmark(self):
        """Test E — Insufficient clean benchmark: fixture with >=20 raw rows but corrupted rows produces INSUFFICIENT status."""
        df_raw = make_valid_df(25, start_date="2026-08-01")
        for i in range(10):
            df_raw.loc[i, "close"] = -1.0

        clean_df, val_res = get_clean_ohlcv_data(df_raw, "VNINDEX")
        self.assertEqual(val_res["status"], "INSUFFICIENT")
        self.assertTrue(clean_df.empty)

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


class TestHardenedPerSymbolDataValidation(unittest.TestCase):
    """Deterministic offline test suite for per-symbol OHLCV validation (15 required core scenarios)."""

    def test_1_valid_ohlcv_returns_real_data(self):
        """1. Valid OHLCV DataFrame -> 'REAL_DATA' tag."""
        from scripts.lib.vietnam_market import get_historical_data

        df = make_valid_df(25)
        with patch("scripts.lib.vietnam_market.VnstockDataProvider") as mock_prov_cls:
            mock_prov_cls.return_value.fetch_ohlcv.return_value = df
            _df_res, tag, issues = get_historical_data("FPT")
            self.assertEqual(tag, "REAL_DATA")
            self.assertEqual(issues, [])

    def test_2_empty_dataframe_fails(self):
        """2. Empty dataframe -> failure."""
        res_none = validate_ohlcv_data(None)
        self.assertEqual(res_none["status"], "INSUFFICIENT")
        self.assertIn("empty_dataframe", res_none["issues"])

        res_empty = validate_ohlcv_data(pd.DataFrame())
        self.assertEqual(res_empty["status"], "INSUFFICIENT")
        self.assertIn("empty_dataframe", res_empty["issues"])

    def test_3_missing_required_column_fails(self):
        """3. Missing required column -> failure."""
        df = make_valid_df(25).drop(columns=["close"])
        res = validate_ohlcv_data(df)
        self.assertEqual(res["status"], "INSUFFICIENT")
        self.assertIn("missing_required_columns", res["issues"])

    def test_4_nan_in_close_fails(self):
        """4. NaN in close -> failure."""
        from scripts.lib.vietnam_market import get_historical_data

        df = make_valid_df(25)
        df.loc[10, "close"] = None
        res = validate_ohlcv_data(df)
        self.assertEqual(res["status"], "INSUFFICIENT")
        self.assertIn("nan_values", res["issues"])
        self.assertTrue(res["clean_df"].empty)

        with patch("scripts.lib.vietnam_market.VnstockDataProvider") as mock_prov_cls:
            mock_prov_cls.return_value.fetch_ohlcv.return_value = df
            _df_res, tag, _ = get_historical_data("FPT")
            self.assertEqual(tag, "EXPLICITLY_INVALID")

    def test_5_inf_in_volume_fails(self):
        """5. Inf in volume -> failure."""
        import numpy as np
        from scripts.lib.vietnam_market import get_historical_data

        df = make_valid_df(25)
        df["volume"] = df["volume"].astype(float)
        df.loc[5, "volume"] = np.inf
        res = validate_ohlcv_data(df)
        self.assertEqual(res["status"], "INSUFFICIENT")
        self.assertIn("infinite_values", res["issues"])
        self.assertTrue(res["clean_df"].empty)

        with patch("scripts.lib.vietnam_market.VnstockDataProvider") as mock_prov_cls:
            mock_prov_cls.return_value.fetch_ohlcv.return_value = df
            _df_res, tag, _ = get_historical_data("FPT")
            self.assertEqual(tag, "EXPLICITLY_INVALID")

    def test_6_negative_price_fails(self):
        """6. Negative price -> failure."""
        from scripts.lib.vietnam_market import get_historical_data

        df = make_valid_df(25)
        df.loc[3, "open"] = -10.0
        res = validate_ohlcv_data(df)
        self.assertEqual(res["status"], "INSUFFICIENT")
        self.assertIn("non_positive_prices", res["issues"])
        self.assertTrue(res["clean_df"].empty)

        with patch("scripts.lib.vietnam_market.VnstockDataProvider") as mock_prov_cls:
            mock_prov_cls.return_value.fetch_ohlcv.return_value = df
            _df_res, tag, _ = get_historical_data("FPT")
            self.assertEqual(tag, "EXPLICITLY_INVALID")

    def test_7_negative_volume_fails(self):
        """7. Negative volume -> failure."""
        from scripts.lib.vietnam_market import get_historical_data

        df = make_valid_df(25)
        df.loc[7, "volume"] = -100
        res = validate_ohlcv_data(df)
        self.assertEqual(res["status"], "INSUFFICIENT")
        self.assertIn("negative_volume", res["issues"])
        self.assertTrue(res["clean_df"].empty)

        with patch("scripts.lib.vietnam_market.VnstockDataProvider") as mock_prov_cls:
            mock_prov_cls.return_value.fetch_ohlcv.return_value = df
            _df_res, tag, _ = get_historical_data("FPT")
            self.assertEqual(tag, "EXPLICITLY_INVALID")

    def test_8_invalid_ohlc_relationship_fails(self):
        """8. Invalid OHLC relationship -> failure."""
        from scripts.lib.vietnam_market import get_historical_data

        df = make_valid_df(25)
        df.loc[2, "high"] = 10.0
        df.loc[2, "low"] = 20.0
        res = validate_ohlcv_data(df)
        self.assertEqual(res["status"], "INSUFFICIENT")
        self.assertIn("invalid_ohlc_relationship", res["issues"])
        self.assertTrue(res["clean_df"].empty)

        with patch("scripts.lib.vietnam_market.VnstockDataProvider") as mock_prov_cls:
            mock_prov_cls.return_value.fetch_ohlcv.return_value = df
            _df_res, tag, _ = get_historical_data("FPT")
            self.assertEqual(tag, "EXPLICITLY_INVALID")

    def test_9_duplicate_dates_fail(self):
        """9. Duplicate dates -> failure."""
        from scripts.lib.vietnam_market import get_historical_data

        df = make_valid_df(25)
        df.loc[10, "time"] = df.loc[9, "time"]
        res = validate_ohlcv_data(df)
        self.assertEqual(res["status"], "INSUFFICIENT")
        self.assertIn("duplicate_dates", res["issues"])
        self.assertTrue(res["clean_df"].empty)

        with patch("scripts.lib.vietnam_market.VnstockDataProvider") as mock_prov_cls:
            mock_prov_cls.return_value.fetch_ohlcv.return_value = df
            _df_res, tag, _ = get_historical_data("FPT")
            self.assertEqual(tag, "EXPLICITLY_INVALID")

    def test_10_non_monotonic_dates_fail(self):
        """10. Non-monotonic dates -> failure."""
        from scripts.lib.vietnam_market import get_historical_data

        df = make_valid_df(25)
        tmp = df.loc[5, "time"]
        df.loc[5, "time"] = df.loc[6, "time"]
        df.loc[6, "time"] = tmp
        res = validate_ohlcv_data(df)
        self.assertEqual(res["status"], "INSUFFICIENT")
        self.assertIn("non_monotonic_dates", res["issues"])
        self.assertTrue(res["clean_df"].empty)

        with patch("scripts.lib.vietnam_market.VnstockDataProvider") as mock_prov_cls:
            mock_prov_cls.return_value.fetch_ohlcv.return_value = df
            _df_res, tag, _ = get_historical_data("FPT")
            self.assertEqual(tag, "EXPLICITLY_INVALID")

    def test_11_insufficient_history(self):
        """11. Insufficient history -> 'INSUFFICIENT_HISTORICAL_DATA'."""
        from scripts.lib.vietnam_market import get_historical_data

        short_df = make_valid_df(5)
        with patch("scripts.lib.vietnam_market.VnstockDataProvider") as mock_prov_cls:
            mock_prov_cls.return_value.fetch_ohlcv.return_value = short_df
            _df_res, tag, issues = get_historical_data("FPT")
            self.assertEqual(tag, "INSUFFICIENT_HISTORICAL_DATA")
            self.assertIn("insufficient_history", issues)

    def test_12_invalid_vnindex_fails_closed(self):
        """12. Invalid VNINDEX -> fail closed."""
        invalid_df = make_valid_df(25)
        invalid_df.loc[10, "close"] = None

        def mock_get_hist(sym, **kwargs):
            if sym == "VNINDEX":
                return invalid_df, "EXPLICITLY_INVALID", ["nan_values"]
            return make_valid_df(25), "REAL_DATA", []

        with patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist):
            with self.assertRaises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            self.assertIn("VNINDEX", str(ctx.exception))

    def test_13_invalid_vn30_fails_closed(self):
        """13. Invalid VN30 -> fail closed."""
        invalid_df = make_valid_df(25)
        invalid_df.loc[5, "volume"] = -100

        def mock_get_hist(sym, **kwargs):
            if sym == "VN30":
                return invalid_df, "EXPLICITLY_INVALID", ["negative_volume"]
            return make_valid_df(25), "REAL_DATA", []

        with patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist):
            with self.assertRaises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            self.assertIn("VN30", str(ctx.exception))

    def test_14_invalid_stock_data_existing_artifacts_unchanged(self):
        """14. Invalid stock data -> existing artifacts unchanged."""
        import json
        import tempfile
        from pathlib import Path

        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_df(25)
        invalid_stock_df = make_valid_df(25)
        invalid_stock_df.loc[8, "close"] = None

        def mock_get_hist(sym, **kwargs):
            if sym == "ACB":
                return invalid_stock_df, "EXPLICITLY_INVALID", ["nan_values"]
            return valid_df, "REAL_DATA", []

        with tempfile.TemporaryDirectory() as tmpdir:
            generated_dir = Path(tmpdir) / "generated"
            generated_dir.mkdir(parents=True, exist_ok=True)
            recs_file = generated_dir / "recommendations.json"
            initial_content = {"schema_version": "2.0", "recommendations": [{"symbol": "PREVIOUS"}]}
            recs_file.write_text(json.dumps(initial_content), encoding="utf-8")

            with (
                patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                with self.assertRaises(SystemExit) as ctx:
                    generate_report_main()

                self.assertEqual(ctx.exception.code, 1)

            saved_content = json.loads(recs_file.read_text(encoding="utf-8"))
            self.assertEqual(saved_content, initial_content)

    def test_15_valid_complete_universe_report_generated_successfully(self):
        """15. Valid complete universe -> report generated successfully."""
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock

        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_df(25)

        def mock_get_hist(sym, **kwargs):
            return valid_df, "REAL_DATA", []

        mock_mon_res = MagicMock()
        mock_mon_res.overall_status = "PASS"
        mock_mon_res.to_dict.return_value = {"overall_status": "PASS"}

        with tempfile.TemporaryDirectory() as tmpdir:
            generated_dir = Path(tmpdir) / "generated"
            generated_dir.mkdir(parents=True, exist_ok=True)

            with (
                patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                patch("scripts.generate_report.get_historical_data", side_effect=mock_get_hist),
                patch("scripts.generate_report.jsonschema.validate", return_value=None),
                patch(
                    "scripts.generate_report.evaluate_production_monitoring",
                    return_value=mock_mon_res,
                ),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                generate_report_main()

            self.assertTrue((generated_dir / "recommendations.json").exists())
            self.assertTrue((generated_dir / "market.json").exists())


if __name__ == "__main__":
    unittest.main()
