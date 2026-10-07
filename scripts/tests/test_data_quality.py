"""Comprehensive Deterministic Unit Tests for OHLCV Data Quality Gate.

Covers Tests A through M without live API dependencies.
"""

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from scripts.data.validation import get_clean_ohlcv_data, validate_ohlcv_data
from scripts.generate_report import run_pipeline
from scripts.quant.recommendation import generate_recommendation
from scripts.quant.regime import detect_market_regime


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


@pytest.mark.unit
class TestDataQualityGate:
    def test_a_empty_data(self):
        """1. Empty data DataFrame -> INSUFFICIENT."""
        res_none = validate_ohlcv_data(None)
        assert res_none["status"] == "INSUFFICIENT"
        assert "empty_dataframe" in res_none["issues"]

        res_empty = validate_ohlcv_data(pd.DataFrame())
        assert res_empty["status"] == "INSUFFICIENT"
        assert "empty_dataframe" in res_empty["issues"]

    def test_b_missing_required_column(self):
        """2. Missing required column -> INSUFFICIENT."""
        df = make_valid_df(30)
        df_no_close = df.drop(columns=["close"])
        res = validate_ohlcv_data(df_no_close)
        assert res["status"] == "INSUFFICIENT"
        assert "missing_required_columns" in res["issues"]

        df_no_date = df.drop(columns=["time"])
        res_date = validate_ohlcv_data(df_no_date)
        assert res_date["status"] == "INSUFFICIENT"
        assert "missing_date_column" in res_date["issues"]

    def test_c_invalid_numeric_value(self):
        """3. Invalid numeric value -> fail closed, clean dataset empty."""
        df = make_valid_df(30)
        df["close"] = df["close"].astype(object)
        df.loc[5, "close"] = "abc"
        res = validate_ohlcv_data(df)
        assert "non_numeric_values" in res["issues"]
        assert "nan_values" in res["issues"]
        assert res["valid_row_count"] == 0
        assert res["clean_df"].empty

    def test_d_nan(self):
        """4. NaN in OHLCV -> fail closed, clean dataset empty."""
        df = make_valid_df(30)
        df.loc[10, "volume"] = None
        res = validate_ohlcv_data(df)
        assert "nan_values" in res["issues"]
        assert res["status"] == "INSUFFICIENT"
        assert res["valid_row_count"] == 0
        assert res["clean_df"].empty

    def test_e_invalid_ohlc_relationship(self):
        """5. Invalid OHLC relationship -> fail closed, clean dataset empty."""
        df = make_valid_df(30)
        # high < close
        df.loc[8, "high"] = 20.0
        df.loc[8, "close"] = 35.0
        res = validate_ohlcv_data(df)
        assert "invalid_ohlc_relationship" in res["issues"]
        assert res["valid_row_count"] == 0
        assert res["clean_df"].empty

    def test_f_negative_volume(self):
        """6. Negative volume -> fail closed, clean dataset empty."""
        df = make_valid_df(30)
        df.loc[12, "volume"] = -500
        res = validate_ohlcv_data(df)
        assert "negative_volume" in res["issues"]
        assert res["valid_row_count"] == 0
        assert res["clean_df"].empty

    def test_g_duplicate_dates(self):
        """7. Duplicate dates -> duplicate_dates, fail closed."""
        df = make_valid_df(30)
        df.loc[15, "time"] = df.loc[14, "time"]
        res = validate_ohlcv_data(df)
        assert "duplicate_dates" in res["issues"]
        assert res["valid_row_count"] == 0
        assert res["clean_df"].empty

    def test_h_valid_dataset(self):
        """8. Valid dataset returns expected SUFFICIENT quality status."""
        df = make_valid_df(30, start_date="2026-08-01")
        res = validate_ohlcv_data(df)
        assert res["status"] == "SUFFICIENT"
        assert res["issues"] == []
        assert res["valid_row_count"] == 30
        assert res["latest_date"] == "2026-08-30"

    def test_i_partial_dataset_pipeline_behavior(self):
        """9. Dataset with invalid row fails closed under hardened validation."""
        df = make_valid_df(31, start_date="2026-08-01")
        # Introduce 1 invalid row at index 15
        df.loc[15, "close"] = -10.0

        clean_df, res = get_clean_ohlcv_data(df, "TEST")
        assert res["status"] == "INSUFFICIENT"
        assert res["valid_row_count"] == 0
        assert clean_df.empty

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
        assert rec["action"] == "AVOID"
        assert rec["data_quality"] == "INSUFFICIENT"
        assert "non_positive_prices" in rec["data_quality_issues"]
        assert rec["signal_score"] is None
        assert rec["risk_adjusted_score"] is None

    def test_j_partial_raw_insufficient_clean_rows(self):
        """10. Raw dataset with non-positive prices fails closed -> INSUFFICIENT."""
        df = make_valid_df(21)
        for idx in range(5):
            df.loc[idx, "close"] = -5.0

        res = validate_ohlcv_data(df)
        assert res["valid_row_count"] == 0
        assert res["status"] == "INSUFFICIENT"
        assert "non_positive_prices" in res["issues"]

    def test_k_no_normal_recommendation_from_insufficient_data(self):
        """11. Insufficient data produces non-actionable recommendation with null scores."""
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
        assert rec["action"] == "AVOID"
        assert rec["signal_score"] is None
        assert rec["risk_adjusted_score"] is None
        assert rec["data_quality"] == "INSUFFICIENT"

    def test_l_data_as_of_uses_latest_usable_date(self):
        """12. data_as_of remains None when market dataset has corrupted rows."""
        df = make_valid_df(30, start_date="2026-08-01")
        # Make the latest raw row invalid (e.g. close <= 0)
        df.loc[df.index[-1], "close"] = 0.0

        res = validate_ohlcv_data(df)
        assert res["latest_date"] is None
        assert res["status"] == "INSUFFICIENT"

        regime_info = {"regime": "NEUTRAL", "confidence": 0.7}
        rec = generate_recommendation(
            symbol="LATEST",
            company_name="Latest Test Co",
            sector="Energy",
            exchange="HOSE",
            df_stock=df,
            market_regime_info=regime_info,
        )
        assert rec["action"] == "AVOID"

    def test_m_raw_data_is_not_mutated(self):
        """13. Validation and cleaning never mutate the original raw DataFrame."""
        df_orig = make_valid_df(30)
        df_orig.loc[5, "close"] = -99.0
        df_orig.loc[10, "high"] = 1.0
        df_orig.loc[10, "close"] = 100.0
        df_copy = df_orig.copy(deep=True)

        _res = validate_ohlcv_data(df_orig, "MUTATE_TEST")

        pd.testing.assert_frame_equal(df_orig, df_copy)


@pytest.mark.unit
class TestMarketCleanDataBoundary:
    def test_a_invalid_latest_vnindex_row(self):
        """1. Corrupted latest VNINDEX row fails validation fail-closed."""
        df_raw = make_valid_df(30, start_date="2026-08-14")
        df_raw.loc[29, "close"] = -100.0

        clean_df, val_res = get_clean_ohlcv_data(df_raw, "VNINDEX")

        assert val_res["latest_date"] is None
        assert val_res["status"] == "INSUFFICIENT"
        assert clean_df.empty

    def test_b_duplicate_benchmark_date(self):
        """2. Duplicate benchmark date fails validation fail-closed."""
        df_raw = make_valid_df(30, start_date="2026-08-01")
        dup_date = df_raw.loc[14, "time"]
        df_raw.loc[15, "time"] = dup_date

        clean_df, val_res = get_clean_ohlcv_data(df_raw, "VNINDEX")
        assert "duplicate_dates" in val_res["issues"]
        assert val_res["status"] == "INSUFFICIENT"
        assert clean_df.empty

    def test_c_invalid_historical_row_does_not_affect_regime(self):
        """3. Invalid historical row fails validation fail-closed."""
        df_raw = make_valid_df(30, start_date="2026-08-01")
        df_raw.loc[15, "close"] = -999.0

        clean_df, val_res = get_clean_ohlcv_data(df_raw, "VNINDEX")
        assert val_res["status"] == "INSUFFICIENT"
        assert clean_df.empty

    def test_e_insufficient_clean_benchmark(self):
        """4. Insufficient clean benchmark: fixture with >=20 raw rows but corrupted rows produces INSUFFICIENT status."""
        df_raw = make_valid_df(25, start_date="2026-08-01")
        for i in range(10):
            df_raw.loc[i, "close"] = -1.0

        clean_df, val_res = get_clean_ohlcv_data(df_raw, "VNINDEX")
        assert val_res["status"] == "INSUFFICIENT"
        assert clean_df.empty

        regime = detect_market_regime(df_vnindex=clean_df)
        assert regime["regime"] == "DEFENSIVE"
        assert regime["confidence"] == 0.40
        assert regime["metrics"]["vnindex_value"] is None

    def test_f_no_mutation(self):
        """5. No mutation: Raw VNINDEX/VN30 DataFrames remain unchanged after validation and cleaning."""
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


SMALL_TEST_UNIVERSE = [
    {"symbol": "ACB", "companyName": "ACB Bank", "sector": "Banking", "exchange": "HOSE"},
    {"symbol": "FPT", "companyName": "FPT Corp", "sector": "Tech", "exchange": "HOSE"},
    {"symbol": "HPG", "companyName": "Hoa Phat", "sector": "Steel", "exchange": "HOSE"},
]


@pytest.mark.unit
class TestHardenedPerSymbolDataValidation:
    """Deterministic offline test suite for per-symbol OHLCV validation (15 required core scenarios)."""

    def setup_method(self):
        self.sleep_p1 = patch("scripts.data.acquisition.time.sleep")
        self.sleep_p2 = patch("scripts.data_provider.time.sleep")
        self.sleep_p3 = patch("scripts.pipeline.stages.time.sleep")
        self.univ_p = patch(
            "scripts.pipeline.stages.UniverseProvider._get_candidates",
            return_value=SMALL_TEST_UNIVERSE,
        )
        self.sleep_p1.start()
        self.sleep_p2.start()
        self.sleep_p3.start()
        self.univ_p.start()

    def teardown_method(self):
        patch.stopall()

    def test_1_valid_ohlcv_returns_real_data(self):
        """1. Valid OHLCV DataFrame -> 'REAL_DATA' tag."""
        from scripts.data.acquisition import get_historical_data

        df = make_valid_df(25)
        with patch("scripts.data.acquisition.VnstockDataProvider") as mock_prov_cls:
            mock_prov_cls.return_value.fetch_ohlcv.return_value = df
            _df_res, tag, issues = get_historical_data("FPT")
            assert tag == "REAL_DATA"
            assert issues == []

    def test_2_empty_dataframe_fails(self):
        """2. Empty dataframe -> failure."""
        res_none = validate_ohlcv_data(None)
        assert res_none["status"] == "INSUFFICIENT"
        assert "empty_dataframe" in res_none["issues"]

        res_empty = validate_ohlcv_data(pd.DataFrame())
        assert res_empty["status"] == "INSUFFICIENT"
        assert "empty_dataframe" in res_empty["issues"]

    def test_3_missing_required_column_fails(self):
        """3. Missing required column -> failure."""
        df = make_valid_df(25).drop(columns=["close"])
        res = validate_ohlcv_data(df)
        assert res["status"] == "INSUFFICIENT"
        assert "missing_required_columns" in res["issues"]

    def test_4_nan_in_close_fails(self):
        """4. NaN in close -> failure."""
        from scripts.data.acquisition import get_historical_data

        df = make_valid_df(25)
        df.loc[10, "close"] = None
        res = validate_ohlcv_data(df)
        assert res["status"] == "INSUFFICIENT"
        assert "nan_values" in res["issues"]
        assert res["clean_df"].empty

        with patch("scripts.data.acquisition.VnstockDataProvider") as mock_prov_cls:
            mock_prov_cls.return_value.fetch_ohlcv.return_value = df
            _df_res, tag, _ = get_historical_data("FPT")
            assert tag == "EXPLICITLY_INVALID"

    def test_5_inf_in_volume_fails(self):
        """5. Inf in volume -> failure."""
        from scripts.data.acquisition import get_historical_data

        df = make_valid_df(25)
        df["volume"] = df["volume"].astype(float)
        df.loc[5, "volume"] = np.inf
        res = validate_ohlcv_data(df)
        assert res["status"] == "INSUFFICIENT"
        assert "infinite_values" in res["issues"]
        assert res["clean_df"].empty

        with patch("scripts.data.acquisition.VnstockDataProvider") as mock_prov_cls:
            mock_prov_cls.return_value.fetch_ohlcv.return_value = df
            _df_res, tag, _ = get_historical_data("FPT")
            assert tag == "EXPLICITLY_INVALID"

    def test_6_negative_price_fails(self):
        """6. Negative price -> failure."""
        from scripts.data.acquisition import get_historical_data

        df = make_valid_df(25)
        df.loc[3, "open"] = -10.0
        res = validate_ohlcv_data(df)
        assert res["status"] == "INSUFFICIENT"
        assert "non_positive_prices" in res["issues"]
        assert res["clean_df"].empty

        with patch("scripts.data.acquisition.VnstockDataProvider") as mock_prov_cls:
            mock_prov_cls.return_value.fetch_ohlcv.return_value = df
            _df_res, tag, _ = get_historical_data("FPT")
            assert tag == "EXPLICITLY_INVALID"

    def test_7_negative_volume_fails(self):
        """7. Negative volume -> failure."""
        from scripts.data.acquisition import get_historical_data

        df = make_valid_df(25)
        df.loc[7, "volume"] = -100
        res = validate_ohlcv_data(df)
        assert res["status"] == "INSUFFICIENT"
        assert "negative_volume" in res["issues"]
        assert res["clean_df"].empty

        with patch("scripts.data.acquisition.VnstockDataProvider") as mock_prov_cls:
            mock_prov_cls.return_value.fetch_ohlcv.return_value = df
            _df_res, tag, _ = get_historical_data("FPT")
            assert tag == "EXPLICITLY_INVALID"

    def test_8_invalid_ohlc_relationship_fails(self):
        """8. Invalid OHLC relationship -> failure."""
        from scripts.data.acquisition import get_historical_data

        df = make_valid_df(25)
        df.loc[2, "high"] = 10.0
        df.loc[2, "low"] = 20.0
        res = validate_ohlcv_data(df)
        assert res["status"] == "INSUFFICIENT"
        assert "invalid_ohlc_relationship" in res["issues"]
        assert res["clean_df"].empty

        with patch("scripts.data.acquisition.VnstockDataProvider") as mock_prov_cls:
            mock_prov_cls.return_value.fetch_ohlcv.return_value = df
            _df_res, tag, _ = get_historical_data("FPT")
            assert tag == "EXPLICITLY_INVALID"

    def test_9_duplicate_dates_fail(self):
        """9. Duplicate dates -> failure."""
        from scripts.data.acquisition import get_historical_data

        df = make_valid_df(25)
        df.loc[10, "time"] = df.loc[9, "time"]
        res = validate_ohlcv_data(df)
        assert res["status"] == "INSUFFICIENT"
        assert "duplicate_dates" in res["issues"]
        assert res["clean_df"].empty

        with patch("scripts.data.acquisition.VnstockDataProvider") as mock_prov_cls:
            mock_prov_cls.return_value.fetch_ohlcv.return_value = df
            _df_res, tag, _ = get_historical_data("FPT")
            assert tag == "EXPLICITLY_INVALID"

    def test_10_non_monotonic_dates_fail(self):
        """10. Non-monotonic dates -> failure."""
        from scripts.data.acquisition import get_historical_data

        df = make_valid_df(25)
        tmp = df.loc[5, "time"]
        df.loc[5, "time"] = df.loc[6, "time"]
        df.loc[6, "time"] = tmp
        res = validate_ohlcv_data(df)
        assert res["status"] == "INSUFFICIENT"
        assert "non_monotonic_dates" in res["issues"]
        assert res["clean_df"].empty

        with patch("scripts.data.acquisition.VnstockDataProvider") as mock_prov_cls:
            mock_prov_cls.return_value.fetch_ohlcv.return_value = df
            _df_res, tag, _ = get_historical_data("FPT")
            assert tag == "EXPLICITLY_INVALID"

    def test_11_insufficient_history(self):
        """11. Insufficient history -> 'INSUFFICIENT_HISTORICAL_DATA'."""
        from scripts.data.acquisition import get_historical_data

        short_df = make_valid_df(5)
        with patch("scripts.data.acquisition.VnstockDataProvider") as mock_prov_cls:
            mock_prov_cls.return_value.fetch_ohlcv.return_value = short_df
            _df_res, tag, issues = get_historical_data("FPT")
            assert tag == "INSUFFICIENT_HISTORICAL_DATA"
            assert "insufficient_history" in issues

    def test_12_invalid_vnindex_fails_closed(self):
        """12. Invalid VNINDEX -> fail closed."""
        invalid_df = make_valid_df(25)
        invalid_df.loc[10, "close"] = None

        def mock_fetch(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == "VNINDEX":
                return invalid_df
            return make_valid_df(25)

        with patch(
            "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
            side_effect=mock_fetch,
        ):
            with pytest.raises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            assert "VNINDEX" in str(ctx.value)

    def test_13_invalid_vn30_fails_closed(self):
        """13. Invalid VN30 -> fail closed."""
        invalid_df = make_valid_df(25)
        invalid_df.loc[5, "volume"] = -100

        def mock_fetch(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == "VN30":
                return invalid_df
            return make_valid_df(25)

        with patch(
            "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
            side_effect=mock_fetch,
        ):
            with pytest.raises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            assert "VN30" in str(ctx.value)

    def test_14_invalid_stock_data_existing_artifacts_unchanged(self):
        """14. Invalid stock data -> existing artifacts unchanged."""
        import json
        import tempfile
        from pathlib import Path

        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_df(25)
        invalid_stock_df = make_valid_df(25)
        invalid_stock_df.loc[8, "close"] = None

        def mock_fetch(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == "ACB":
                return invalid_stock_df
            return valid_df

        with tempfile.TemporaryDirectory() as tmpdir:
            generated_dir = Path(tmpdir) / "generated"
            generated_dir.mkdir(parents=True, exist_ok=True)
            recs_file = generated_dir / "recommendations.json"
            initial_content = {"schema_version": "2.0", "recommendations": [{"symbol": "PREVIOUS"}]}
            recs_file.write_text(json.dumps(initial_content), encoding="utf-8")

            with (
                patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                patch(
                    "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                    side_effect=mock_fetch,
                ),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                with pytest.raises(SystemExit) as ctx:
                    generate_report_main()

                assert ctx.value.code == 1

            saved_content = json.loads(recs_file.read_text(encoding="utf-8"))
            assert saved_content == initial_content

    def test_15_valid_complete_universe_report_generated_successfully(self):
        """15. Valid complete universe -> report generated successfully."""
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock

        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_df(25)

        def mock_fetch(symbol=None, **kwargs):
            return valid_df

        mock_mon_res = MagicMock()
        mock_mon_res.overall_status = "PASS"
        mock_mon_res.to_dict.return_value = {"overall_status": "PASS"}

        with tempfile.TemporaryDirectory() as tmpdir:
            generated_dir = Path(tmpdir) / "generated"
            generated_dir.mkdir(parents=True, exist_ok=True)

            with (
                patch("scripts.generate_report.GENERATED_DIR", str(generated_dir)),
                patch(
                    "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                    side_effect=mock_fetch,
                ),
                patch("jsonschema.validate", return_value=None),
                patch(
                    "scripts.pipeline.stages.evaluate_production_monitoring",
                    return_value=mock_mon_res,
                ),
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                generate_report_main()

            assert (generated_dir / "recommendations.json").exists()
            assert (generated_dir / "market.json").exists()
