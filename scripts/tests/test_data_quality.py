"""Comprehensive Deterministic Unit Tests for OHLCV Data Quality Gate.

Covers Tests A through M without live API dependencies.
"""

import numpy as np
import pandas as pd
import pytest

from scripts.data.validation import get_clean_ohlcv_data, validate_ohlcv_data
from scripts.generate_report import run_pipeline
from scripts.quant.recommendation import generate_single_recommendation
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
    def test_empty_data(self):
        """Empty data DataFrame -> INSUFFICIENT."""
        res_none = validate_ohlcv_data(None)
        assert res_none["status"] == "INSUFFICIENT"
        assert "empty_dataframe" in res_none["issues"]

        res_empty = validate_ohlcv_data(pd.DataFrame())
        assert res_empty["status"] == "INSUFFICIENT"
        assert "empty_dataframe" in res_empty["issues"]

    def test_missing_required_column(self):
        """Missing required column -> INSUFFICIENT."""
        df = make_valid_df(30)
        df_no_close = df.drop(columns=["close"])
        res = validate_ohlcv_data(df_no_close)
        assert res["status"] == "INSUFFICIENT"
        assert "missing_required_columns" in res["issues"]

        df_no_date = df.drop(columns=["time"])
        res_date = validate_ohlcv_data(df_no_date)
        assert res_date["status"] == "INSUFFICIENT"
        assert "missing_date_column" in res_date["issues"]

    def test_invalid_numeric_value(self):
        """Invalid numeric value -> fail closed, clean dataset empty."""
        df = make_valid_df(30)
        df["close"] = df["close"].astype(object)
        df.loc[5, "close"] = "abc"
        res = validate_ohlcv_data(df)
        assert "non_numeric_values" in res["issues"]
        assert "nan_values" in res["issues"]
        assert res["valid_row_count"] == 0
        assert res["clean_df"].empty

    def test_nan(self):
        """NaN in OHLCV -> fail closed, clean dataset empty."""
        df = make_valid_df(30)
        df.loc[10, "volume"] = None
        res = validate_ohlcv_data(df)
        assert "nan_values" in res["issues"]
        assert res["status"] == "INSUFFICIENT"
        assert res["valid_row_count"] == 0
        assert res["clean_df"].empty

    def test_invalid_ohlc_relationship(self):
        """Invalid OHLC relationship -> fail closed, clean dataset empty."""
        df = make_valid_df(30)
        # high < close
        df.loc[8, "high"] = 20.0
        df.loc[8, "close"] = 35.0
        res = validate_ohlcv_data(df)
        assert "invalid_ohlc_relationship" in res["issues"]
        assert res["valid_row_count"] == 0
        assert res["clean_df"].empty

    def test_negative_volume(self):
        """Negative volume -> fail closed, clean dataset empty."""
        df = make_valid_df(30)
        df.loc[12, "volume"] = -500
        res = validate_ohlcv_data(df)
        assert "negative_volume" in res["issues"]
        assert res["valid_row_count"] == 0
        assert res["clean_df"].empty

    def test_duplicate_dates(self):
        """Duplicate dates -> duplicate_dates, fail closed."""
        df = make_valid_df(30)
        df.loc[15, "time"] = df.loc[14, "time"]
        res = validate_ohlcv_data(df)
        assert "duplicate_dates" in res["issues"]
        assert res["valid_row_count"] == 0
        assert res["clean_df"].empty

    def test_valid_dataset(self):
        """Valid dataset returns expected SUFFICIENT quality status."""
        df = make_valid_df(30, start_date="2026-08-01")
        res = validate_ohlcv_data(df)
        assert res["status"] == "SUFFICIENT"
        assert res["issues"] == []
        assert res["valid_row_count"] == 30
        assert res["latest_date"] == "2026-08-30"

    def test_partial_dataset_pipeline_behavior(self):
        """Dataset with invalid row fails closed under hardened validation."""
        df = make_valid_df(31, start_date="2026-08-01")
        # Introduce 1 invalid row at index 15
        df.loc[15, "close"] = -10.0

        clean_df, res = get_clean_ohlcv_data(df, "TEST")
        assert res["status"] == "INSUFFICIENT"
        assert res["valid_row_count"] == 0
        assert clean_df.empty

        # Test actual recommendation generation pipeline with this dataset
        regime_info = {"regime": "BULL", "confidence": 0.8}
        rec = generate_single_recommendation(
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

    def test_partial_raw_insufficient_clean_rows(self):
        """Raw dataset with non-positive prices fails closed -> INSUFFICIENT."""
        df = make_valid_df(21)
        for idx in range(5):
            df.loc[idx, "close"] = -5.0

        res = validate_ohlcv_data(df)
        assert res["valid_row_count"] == 0
        assert res["status"] == "INSUFFICIENT"
        assert "non_positive_prices" in res["issues"]

    def test_no_normal_recommendation_from_insufficient_data(self):
        """Insufficient data produces non-actionable recommendation with null scores."""
        df_short = make_valid_df(10)
        regime_info = {"regime": "STRONG_BULL", "confidence": 0.9}
        rec = generate_single_recommendation(
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

    def test_data_as_of_uses_latest_usable_date(self):
        """data_as_of remains None when market dataset has corrupted rows."""
        df = make_valid_df(30, start_date="2026-08-01")
        # Make the latest raw row invalid (e.g. close <= 0)
        df.loc[df.index[-1], "close"] = 0.0

        res = validate_ohlcv_data(df)
        assert res["latest_date"] is None
        assert res["status"] == "INSUFFICIENT"

        regime_info = {"regime": "NEUTRAL", "confidence": 0.7}
        rec = generate_single_recommendation(
            symbol="LATEST",
            company_name="Latest Test Co",
            sector="Energy",
            exchange="HOSE",
            df_stock=df,
            market_regime_info=regime_info,
        )
        assert rec["action"] == "AVOID"

    def test_raw_data_is_not_mutated(self):
        """Validation and cleaning never mutate the original raw DataFrame."""
        df_orig = make_valid_df(30)
        df_orig.loc[5, "close"] = -99.0
        df_orig.loc[10, "high"] = 1.0
        df_orig.loc[10, "close"] = 100.0
        df_copy = df_orig.copy(deep=True)

        _res = validate_ohlcv_data(df_orig, "MUTATE_TEST")

        pd.testing.assert_frame_equal(df_orig, df_copy)


@pytest.mark.unit
class TestMarketCleanDataBoundary:
    def test_invalid_latest_vnindex_row(self):
        """Corrupted latest VNINDEX row fails validation fail-closed."""
        df_raw = make_valid_df(30, start_date="2026-08-14")
        df_raw.loc[29, "close"] = -100.0

        clean_df, val_res = get_clean_ohlcv_data(df_raw, "VNINDEX")

        assert val_res["latest_date"] is None
        assert val_res["status"] == "INSUFFICIENT"
        assert clean_df.empty

    def test_duplicate_benchmark_date(self):
        """Duplicate benchmark date fails validation fail-closed."""
        df_raw = make_valid_df(30, start_date="2026-08-01")
        dup_date = df_raw.loc[14, "time"]
        df_raw.loc[15, "time"] = dup_date

        clean_df, val_res = get_clean_ohlcv_data(df_raw, "VNINDEX")
        assert "duplicate_dates" in val_res["issues"]
        assert val_res["status"] == "INSUFFICIENT"
        assert clean_df.empty

    def test_invalid_historical_row_does_not_affect_regime(self):
        """Invalid historical row fails validation fail-closed."""
        df_raw = make_valid_df(30, start_date="2026-08-01")
        df_raw.loc[15, "close"] = -999.0

        clean_df, val_res = get_clean_ohlcv_data(df_raw, "VNINDEX")
        assert val_res["status"] == "INSUFFICIENT"
        assert clean_df.empty

    def test_insufficient_clean_benchmark(self):
        """Insufficient clean benchmark: fixture with >=20 raw rows but corrupted rows produces INSUFFICIENT status."""
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

    def test_no_mutation(self):
        """No mutation: Raw VNINDEX/VN30 DataFrames remain unchanged after validation and cleaning."""
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

    @pytest.fixture(autouse=True)
    def _setup_patches(self, mocker):
        mocker.patch("scripts.data.acquisition.time.sleep")
        mocker.patch("scripts.data_provider.time.sleep")
        mocker.patch("scripts.pipeline.stages.time.sleep")
        mocker.patch(
            "scripts.pipeline.stages.UniverseProvider._get_candidates",
            return_value=SMALL_TEST_UNIVERSE,
        )

    def test_valid_ohlcv_returns_real_data(self, mocker):
        """Valid OHLCV DataFrame -> 'REAL_DATA' tag."""
        from scripts.data.acquisition import get_historical_data

        df = make_valid_df(25)
        mock_prov_cls = mocker.patch("scripts.data.acquisition.VnstockDataProvider")
        mock_prov_cls.return_value.fetch_ohlcv.return_value = df
        _df_res, tag, issues = get_historical_data("FPT")
        assert tag == "REAL_DATA"
        assert issues == []

    def test_nan_in_close_fails(self, mocker):
        """NaN in close -> acquisition classifies as EXPLICITLY_INVALID."""
        from scripts.data.acquisition import get_historical_data

        df = make_valid_df(25)
        df.loc[10, "close"] = None

        mock_prov_cls = mocker.patch("scripts.data.acquisition.VnstockDataProvider")
        mock_prov_cls.return_value.fetch_ohlcv.return_value = df
        _df_res, tag, _issues = get_historical_data("FPT")
        assert tag == "EXPLICITLY_INVALID"

    def test_inf_in_volume_fails(self, mocker):
        """Inf in volume -> acquisition classifies as EXPLICITLY_INVALID."""
        from scripts.data.acquisition import get_historical_data

        df = make_valid_df(25)
        df["volume"] = df["volume"].astype(float)
        df.loc[5, "volume"] = np.inf

        mock_prov_cls = mocker.patch("scripts.data.acquisition.VnstockDataProvider")
        mock_prov_cls.return_value.fetch_ohlcv.return_value = df
        _df_res, tag, _issues = get_historical_data("FPT")
        assert tag == "EXPLICITLY_INVALID"

    def test_negative_price_fails(self, mocker):
        """Negative price -> acquisition classifies as EXPLICITLY_INVALID."""
        from scripts.data.acquisition import get_historical_data

        df = make_valid_df(25)
        df.loc[3, "open"] = -10.0

        mock_prov_cls = mocker.patch("scripts.data.acquisition.VnstockDataProvider")
        mock_prov_cls.return_value.fetch_ohlcv.return_value = df
        _df_res, tag, _issues = get_historical_data("FPT")
        assert tag == "EXPLICITLY_INVALID"

    def test_negative_volume_fails(self, mocker):
        """Negative volume -> acquisition classifies as EXPLICITLY_INVALID."""
        from scripts.data.acquisition import get_historical_data

        df = make_valid_df(25)
        df.loc[7, "volume"] = -100

        mock_prov_cls = mocker.patch("scripts.data.acquisition.VnstockDataProvider")
        mock_prov_cls.return_value.fetch_ohlcv.return_value = df
        _df_res, tag, _issues = get_historical_data("FPT")
        assert tag == "EXPLICITLY_INVALID"

    def test_invalid_ohlc_relationship_fails(self, mocker):
        """Invalid OHLC relationship -> acquisition classifies as EXPLICITLY_INVALID."""
        from scripts.data.acquisition import get_historical_data

        df = make_valid_df(25)
        df.loc[2, "high"] = 10.0
        df.loc[2, "low"] = 20.0

        mock_prov_cls = mocker.patch("scripts.data.acquisition.VnstockDataProvider")
        mock_prov_cls.return_value.fetch_ohlcv.return_value = df
        _df_res, tag, _issues = get_historical_data("FPT")
        assert tag == "EXPLICITLY_INVALID"

    def test_duplicate_dates_fail(self, mocker):
        """Duplicate dates -> acquisition classifies as EXPLICITLY_INVALID."""
        from scripts.data.acquisition import get_historical_data

        df = make_valid_df(25)
        df.loc[10, "time"] = df.loc[9, "time"]

        mock_prov_cls = mocker.patch("scripts.data.acquisition.VnstockDataProvider")
        mock_prov_cls.return_value.fetch_ohlcv.return_value = df
        _df_res, tag, _issues = get_historical_data("FPT")
        assert tag == "EXPLICITLY_INVALID"

    def test_non_monotonic_dates_fail(self, mocker):
        """Non-monotonic dates -> acquisition classifies as EXPLICITLY_INVALID."""
        from scripts.data.acquisition import get_historical_data

        df = make_valid_df(25)
        tmp = df.loc[5, "time"]
        df.loc[5, "time"] = df.loc[6, "time"]
        df.loc[6, "time"] = tmp

        mock_prov_cls = mocker.patch("scripts.data.acquisition.VnstockDataProvider")
        mock_prov_cls.return_value.fetch_ohlcv.return_value = df
        _df_res, tag, _issues = get_historical_data("FPT")
        assert tag == "EXPLICITLY_INVALID"

    def test_insufficient_history(self, mocker):
        """Insufficient history -> 'INSUFFICIENT_HISTORICAL_DATA'."""
        from scripts.data.acquisition import get_historical_data

        short_df = make_valid_df(5)
        mock_prov_cls = mocker.patch("scripts.data.acquisition.VnstockDataProvider")
        mock_prov_cls.return_value.fetch_ohlcv.return_value = short_df
        _df_res, tag, issues = get_historical_data("FPT")
        assert tag == "INSUFFICIENT_HISTORICAL_DATA"
        assert "insufficient_history" in issues

    def test_invalid_vnindex_fails_closed(self, mocker):
        """Invalid VNINDEX -> fail closed."""
        invalid_df = make_valid_df(25)
        invalid_df.loc[10, "close"] = None

        def mock_fetch(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == "VNINDEX":
                return invalid_df
            return make_valid_df(25)

        mocker.patch(
            "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
            side_effect=mock_fetch,
        )
        with pytest.raises(RuntimeError) as ctx:
            run_pipeline(update_data=True)

        assert "VNINDEX" in str(ctx.value)

    def test_invalid_vn30_fails_closed(self, mocker):
        """Invalid VN30 -> fail closed."""
        invalid_df = make_valid_df(25)
        invalid_df.loc[5, "volume"] = -100

        def mock_fetch(symbol=None, **kwargs):
            sym = symbol or kwargs.get("sym")
            if sym == "VN30":
                return invalid_df
            return make_valid_df(25)

        mocker.patch(
            "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
            side_effect=mock_fetch,
        )
        with pytest.raises(RuntimeError) as ctx:
            run_pipeline(update_data=True)

        assert "VN30" in str(ctx.value)

    def test_invalid_stock_data_existing_artifacts_unchanged(self, mocker):
        """Invalid stock data -> existing artifacts unchanged."""
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

            mocker.patch("scripts.generate_report.GENERATED_DIR", str(generated_dir))
            mocker.patch(
                "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                side_effect=mock_fetch,
            )
            mocker.patch("sys.argv", ["generate_report.py", "--update"])

            with pytest.raises(SystemExit) as ctx:
                generate_report_main()

            assert ctx.value.code == 1

            saved_content = json.loads(recs_file.read_text(encoding="utf-8"))
            assert saved_content == initial_content

    def test_valid_complete_universe_report_generated_successfully(self, mocker):
        """Valid complete universe -> report generated successfully."""
        import tempfile
        from pathlib import Path

        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_df(25)

        def mock_fetch(symbol=None, **kwargs):
            return valid_df

        mock_mon_res = mocker.MagicMock()
        mock_mon_res.overall_status = "PASS"
        mock_mon_res.to_dict.return_value = {"overall_status": "PASS"}

        with tempfile.TemporaryDirectory() as tmpdir:
            generated_dir = Path(tmpdir) / "generated"
            generated_dir.mkdir(parents=True, exist_ok=True)

            mocker.patch("scripts.generate_report.GENERATED_DIR", str(generated_dir))
            mocker.patch(
                "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                side_effect=mock_fetch,
            )
            mocker.patch("jsonschema.validate", return_value=None)
            mocker.patch(
                "scripts.pipeline.stages.evaluate_production_monitoring",
                return_value=mock_mon_res,
            )
            mocker.patch("sys.argv", ["generate_report.py", "--update"])

            generate_report_main()

            assert (generated_dir / "recommendations.json").exists()
            assert (generated_dir / "market.json").exists()
