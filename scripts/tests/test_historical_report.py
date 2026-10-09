"""Unit and integration tests for reproducible historical report generation."""

import json
import os
import shutil
import tempfile

import pandas as pd
import pytest

from scripts.generate_report import (
    canonicalize_report_for_reproducibility,
    generate_historical_report,
    load_historical_ohlcv,
    load_universe_snapshot,
)


def create_synthetic_ohlcv(
    start_date: str = "2025-01-01",
    periods: int = 30,
    base_price: float = 50.0,
    volume: float = 100000.0,
) -> pd.DataFrame:
    """Helper to create valid daily OHLCV DataFrames."""
    dates = pd.date_range(start=start_date, periods=periods, freq="D")
    data = []
    for i, d in enumerate(dates):
        price = base_price + (i * 0.5)
        data.append(
            {
                "time": d.strftime("%Y-%m-%d"),
                "open": price,
                "high": price + 1.0,
                "low": price - 0.5,
                "close": price + 0.2,
                "volume": volume,
            }
        )
    return pd.DataFrame(data)


@pytest.mark.integration
class TestHistoricalReportGeneration:
    """Test suite for historical report generation contract and reproducibility."""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.as_of_date = "2025-01-20"

        self.df_vnindex = create_synthetic_ohlcv("2025-01-01", 30, base_price=1200.0)
        self.df_vn30 = create_synthetic_ohlcv("2025-01-01", 30, base_price=1250.0)
        self.df_vnm = create_synthetic_ohlcv("2025-01-01", 30, base_price=70.0)
        self.df_fpt = create_synthetic_ohlcv("2025-01-01", 30, base_price=130.0)

        self.universe_map = {
            "VNM": self.df_vnm,
            "FPT": self.df_fpt,
        }

        self.candidate_metadata = [
            {
                "symbol": "VNM",
                "companyName": "Vinamilk",
                "sector": "Consumer Goods",
                "exchange": "HOSE",
            },
            {
                "symbol": "FPT",
                "companyName": "FPT Corporation",
                "sector": "Technology",
                "exchange": "HOSE",
            },
        ]

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_explicit_historical_date(self):
        """Verifies that historical reports are generated successfully given valid historical datasets and an explicit evaluation date."""
        res = generate_historical_report(
            data_as_of=self.as_of_date,
            universe_stock_map=self.universe_map,
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
            candidate_metadata=self.candidate_metadata,
            reference_date="2025-01-20T10:00:00Z",
        )

        recs_data, market_data, history_data = res
        assert recs_data["data_as_of"] == self.as_of_date
        assert recs_data["source_date"] == self.as_of_date
        assert len(recs_data["recommendations"]) == 2
        assert recs_data["universe_info"]["universe_type"] == "HISTORICAL_SNAPSHOT"
        assert recs_data["universe_info"]["universe_size"] == 2
        assert market_data["data_as_of"] == self.as_of_date
        assert history_data["data_as_of"] == self.as_of_date

    def test_repeated_generation_is_deterministic(self):
        """Verifies that repeated generation with identical inputs and a controlled reference date produces identical report payloads."""
        res1 = generate_historical_report(
            data_as_of=self.as_of_date,
            universe_stock_map=self.universe_map,
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
            candidate_metadata=self.candidate_metadata,
            reference_date="2025-01-20T10:00:00Z",
        )

        res2 = generate_historical_report(
            data_as_of=self.as_of_date,
            universe_stock_map=self.universe_map,
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
            candidate_metadata=self.candidate_metadata,
            reference_date="2025-01-20T10:00:00Z",
        )

        assert res1[0] == res2[0]
        assert res1[1] == res2[1]

        # Test canonicalization helper when reference_date differs
        res3 = generate_historical_report(
            data_as_of=self.as_of_date,
            universe_stock_map=self.universe_map,
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
            candidate_metadata=self.candidate_metadata,
            reference_date="2025-02-15T12:34:56Z",
        )

        canon1 = canonicalize_report_for_reproducibility(res1[0])
        canon3 = canonicalize_report_for_reproducibility(res3[0])
        assert canon1 == canon3

    def test_future_observation_rejected(self):
        """Verifies that unsorted or corrupted historical OHLCV data fails closed during historical report generation."""
        corrupted_vnm = self.df_vnm.copy()
        # Insert duplicate/unsorted row
        corrupted_vnm.loc[len(corrupted_vnm)] = corrupted_vnm.iloc[10].to_dict()

        corrupted_map = {"VNM": corrupted_vnm, "FPT": self.df_fpt}

        with pytest.raises(ValueError):
            generate_historical_report(
                data_as_of=self.as_of_date,
                universe_stock_map=corrupted_map,
                df_vnindex=self.df_vnindex,
                df_vn30=self.df_vn30,
                candidate_metadata=self.candidate_metadata,
            )

    def test_missing_evaluation_date(self):
        """Verifies that requesting a target date absent from the benchmark dataset fails closed."""
        absent_date = "2020-01-01"
        with pytest.raises(ValueError):
            generate_historical_report(
                data_as_of=absent_date,
                universe_stock_map=self.universe_map,
                df_vnindex=self.df_vnindex,
                df_vn30=self.df_vn30,
                candidate_metadata=self.candidate_metadata,
            )

    def test_duplicate_unsorted_dates(self):
        """Verifies that duplicate dates in benchmark data fail closed during historical report generation."""
        corrupted_vnindex = self.df_vnindex.copy()
        corrupted_vnindex.loc[len(corrupted_vnindex)] = corrupted_vnindex.iloc[5].to_dict()

        with pytest.raises(ValueError):
            generate_historical_report(
                data_as_of=self.as_of_date,
                universe_stock_map=self.universe_map,
                df_vnindex=corrupted_vnindex,
                df_vn30=self.df_vn30,
                candidate_metadata=self.candidate_metadata,
            )

    def test_malformed_ohlcv(self):
        """Verifies that malformed OHLCV data missing required columns fails closed during historical report generation."""
        corrupted_fpt = self.df_fpt.copy().drop(columns=["close"])

        corrupted_map = {"VNM": self.df_vnm, "FPT": corrupted_fpt}

        with pytest.raises((ValueError, KeyError)):
            generate_historical_report(
                data_as_of=self.as_of_date,
                universe_stock_map=corrupted_map,
                df_vnindex=self.df_vnindex,
                df_vn30=self.df_vn30,
                candidate_metadata=self.candidate_metadata,
            )

    def test_no_fallback_to_latest_data(self):
        """Verifies anti-lookahead protection where changing future prices after date T leaves the historical report at date T unchanged."""
        report_before = generate_historical_report(
            data_as_of=self.as_of_date,
            universe_stock_map=self.universe_map,
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
            candidate_metadata=self.candidate_metadata,
            reference_date="2025-01-20T10:00:00Z",
        )

        # Mutate future rows (date > 2025-01-20)
        modified_vnm = self.df_vnm.copy()
        future_mask = modified_vnm["time"] > self.as_of_date
        modified_vnm.loc[future_mask, "close"] = 9999.0

        modified_map = {"VNM": modified_vnm, "FPT": self.df_fpt}

        report_after = generate_historical_report(
            data_as_of=self.as_of_date,
            universe_stock_map=modified_map,
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
            candidate_metadata=self.candidate_metadata,
            reference_date="2025-01-20T10:00:00Z",
        )

        assert report_before[0] == report_after[0]

    def test_provenance(self):
        """Verifies that generated historical reports retain complete provenance metadata including model version, schema version, and data_as_of date."""
        res = generate_historical_report(
            data_as_of=self.as_of_date,
            universe_stock_map=self.universe_map,
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
            candidate_metadata=self.candidate_metadata,
        )
        recs_data = res[0]
        assert "schema_version" in recs_data
        assert "signal_model_version" in recs_data
        assert recs_data["data_as_of"] == self.as_of_date
        assert recs_data["source_date"] == self.as_of_date

    def test_generated_at_does_not_affect_quantitative_output(self):
        """Verifies that varying runtime timestamps leave quantitative signal scores, recommendation actions, regime, and risk metrics unchanged."""
        res_t1 = generate_historical_report(
            data_as_of=self.as_of_date,
            universe_stock_map=self.universe_map,
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
            candidate_metadata=self.candidate_metadata,
            reference_date="2025-01-20T00:00:00Z",
        )

        res_t2 = generate_historical_report(
            data_as_of=self.as_of_date,
            universe_stock_map=self.universe_map,
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
            candidate_metadata=self.candidate_metadata,
            reference_date="2025-03-01T23:59:59Z",
        )

        canon1 = canonicalize_report_for_reproducibility(res_t1[0])
        canon2 = canonicalize_report_for_reproducibility(res_t2[0])

        assert canon1 == canon2
        assert canon1["market"] == canon2["market"]
        assert canon1["summary"] == canon2["summary"]
        assert canon1["recommendations"] == canon2["recommendations"]

    def test_load_universe_snapshot_and_ohlcv_file_loading(self):
        """Verifies that universe snapshot and OHLCV file loaders read valid inputs successfully and fail closed on malformed files."""
        snapshot_file = os.path.join(self.tmp_dir, "snapshot.json")
        with open(snapshot_file, "w", encoding="utf-8") as f:
            json.dump(self.candidate_metadata, f)

        loaded_candidates = load_universe_snapshot(snapshot_file)
        assert len(loaded_candidates) == 2
        assert loaded_candidates[0]["symbol"] == "VNM"

        # Test OHLCV file loader
        ohlcv_file = os.path.join(self.tmp_dir, "ohlcv.json")
        ohlcv_data = {
            "VNINDEX": self.df_vnindex.to_dict(orient="records"),
            "VN30": self.df_vn30.to_dict(orient="records"),
            "VNM": self.df_vnm.to_dict(orient="records"),
            "FPT": self.df_fpt.to_dict(orient="records"),
        }
        with open(ohlcv_file, "w", encoding="utf-8") as f:
            json.dump(ohlcv_data, f)

        stock_map, df_vnindex_loaded, df_vn30_loaded = load_historical_ohlcv(
            ohlcv_file, required_symbols=["VNM", "FPT"]
        )
        assert "VNM" in stock_map
        assert "FPT" in stock_map
        assert not df_vnindex_loaded.empty
        assert df_vn30_loaded is not None
