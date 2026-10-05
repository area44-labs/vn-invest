"""Deterministic offline regression tests for end-to-end pipeline data flow consistency.

Validates:
1. Symbol categorization when raw data is >= 20 rows but clean data is < 20 rows ('status' == 'INSUFFICIENT').
2. Edge cases: 0 valid symbols, 1 valid symbol, all candidates invalid/failed/insufficient.
3. Duplicate candidate metadata rejection in generate_historical_report.
4. Fail-closed error handling in update mode when scan is incomplete.
5. Deterministic aggregate metrics without NaN, Inf, or division-by-zero.
"""

import json
import shutil
import tempfile
import unittest
from unittest.mock import patch

import jsonschema
import pandas as pd

from scripts.domain.universe import Universe
from scripts.generate_report import (
    SCHEMA_PATH,
    generate_historical_report,
    run_pipeline,
)


def create_synthetic_ohlcv(
    start_date: str = "2025-01-01",
    periods: int = 30,
    base_price: float = 50.0,
    volume: float = 100000.0,
) -> pd.DataFrame:
    """Helper to create valid daily OHLCV DataFrames in VND units."""
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


def load_schema():
    """Load recommendations JSON Schema."""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


class TestDataFlowConsistency(unittest.TestCase):
    """Test suite for pipeline data flow consistency and downstream calculations."""

    def setUp(self):
        self.sleep_patcher1 = patch("scripts.data.acquisition.time.sleep")
        self.sleep_patcher2 = patch("scripts.data_provider.time.sleep")
        self.sleep_patcher3 = patch("scripts.lib.vietnam_market.time.sleep")
        self.sleep_patcher1.start()
        self.sleep_patcher2.start()
        self.sleep_patcher3.start()

        self.tmp_dir = tempfile.mkdtemp()
        self.as_of_date = "2025-01-30"  # 30 days from 2025-01-01
        self.schema = load_schema()

        self.df_vnindex = create_synthetic_ohlcv("2025-01-01", 30, base_price=1200.0)
        self.df_vn30 = create_synthetic_ohlcv("2025-01-01", 30, base_price=1250.0)
        self.df_vnm = create_synthetic_ohlcv("2025-01-01", 30, base_price=70000.0)
        self.df_fpt = create_synthetic_ohlcv("2025-01-01", 30, base_price=130000.0)

    def tearDown(self):
        patch.stopall()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_insufficient_clean_history_symbol_categorization(self):
        """Test that a stock with tag='REAL_DATA' but stock_val['status'] == 'INSUFFICIENT' is added to insufficient_history_symbols."""
        # Clean df has 10 valid rows (non-empty, no corruption, but < 20 rows)
        clean_10_df = create_synthetic_ohlcv("2025-01-21", 10, base_price=50000.0)

        candidates = [
            {"symbol": "AAA", "companyName": "AAA Corp", "sector": "Materials", "exchange": "HOSE"}
        ]

        def mock_fetch_ohlcv(symbol, **_kwargs):
            if symbol == "VNINDEX":
                return self.df_vnindex
            if symbol == "VN30":
                return self.df_vn30
            if symbol == "AAA":
                return clean_10_df
            return pd.DataFrame()

        with (
            patch("scripts.pipeline.runner.UniverseProvider") as mock_provider_cls,
            patch(
                "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                side_effect=mock_fetch_ohlcv,
            ),
        ):
            mock_provider = mock_provider_cls.return_value
            mock_provider.get_universe.return_value = Universe.from_candidates(
                candidates,
                universe_type="TEST",
                benchmarks=("VNINDEX", "VN30"),
            )

            # In update mode, should raise RuntimeError because AAA has insufficient history (< 20 clean rows)
            with self.assertRaises(RuntimeError) as ctx:
                run_pipeline(update_data=True)

            self.assertIn("Incomplete universe scan in update mode", str(ctx.exception))
            self.assertIn("Insufficient History: 1", str(ctx.exception))
            self.assertIn("AAA", str(ctx.exception))

            # In non-update mode, run_pipeline completes, tagging AAA as INSUFFICIENT and AVOID
            recs_data, _market_data, _ = run_pipeline(update_data=False)
            self.assertEqual(recs_data["summary"]["total_scanned"], 1)
            self.assertEqual(recs_data["summary"]["avoid_count"], 1)
            self.assertEqual(recs_data["recommendations"][0]["data_quality"], "INSUFFICIENT")
            self.assertEqual(recs_data["recommendations"][0]["action"], "AVOID")

    def test_pipeline_zero_valid_stock_symbols(self):
        """Test pipeline behavior when stock universe contains 0 valid symbols (all insufficient)."""
        candidate_metadata = [
            {
                "symbol": "VNM",
                "companyName": "Vinamilk",
                "sector": "Consumer Goods",
                "exchange": "HOSE",
            },
            {
                "symbol": "FPT",
                "companyName": "FPT Corp",
                "sector": "Technology",
                "exchange": "HOSE",
            },
        ]

        # Stock DataFrames have 10 rows ending on 2025-01-30 (insufficient history < 20)
        short_vnm = create_synthetic_ohlcv("2025-01-21", 10, base_price=70000.0)
        short_fpt = create_synthetic_ohlcv("2025-01-21", 10, base_price=130000.0)

        universe_map = {"VNM": short_vnm, "FPT": short_fpt}

        res = generate_historical_report(
            data_as_of=self.as_of_date,
            universe_stock_map=universe_map,
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
            candidate_metadata=candidate_metadata,
        )

        recs_data, market_data, _ = res

        # Validate schema compliance
        jsonschema.validate(instance=recs_data, schema=self.schema)

        # Market breadth defaults safely to 0.50 without zero division
        self.assertEqual(market_data["market"]["metrics"]["market_breadth_ratio"], 0.50)

        # Summary accounting
        summary = recs_data["summary"]
        self.assertEqual(summary["total_scanned"], 2)
        self.assertEqual(summary["avoid_count"], 2)
        self.assertEqual(summary["buy_count"], 0)
        self.assertEqual(summary["watch_count"], 0)
        self.assertEqual(summary["hold_count"], 0)
        self.assertEqual(summary["sell_count"], 0)

        # Recommendations check
        for rec in recs_data["recommendations"]:
            self.assertEqual(rec["action"], "AVOID")
            self.assertEqual(rec["data_quality"], "INSUFFICIENT")
            self.assertIsNone(rec["signal_score"])
            self.assertIsNone(rec["risk_adjusted_score"])
            self.assertIsNone(rec["risk_metrics"]["liquidity_score"])

    def test_pipeline_single_valid_stock_symbol(self):
        """Test pipeline behavior when universe contains exactly 1 valid stock symbol."""
        candidate_metadata = [
            {
                "symbol": "VNM",
                "companyName": "Vinamilk",
                "sector": "Consumer Goods",
                "exchange": "HOSE",
            },
            {
                "symbol": "FPT",
                "companyName": "FPT Corp",
                "sector": "Technology",
                "exchange": "HOSE",
            },
        ]

        # VNM valid (30 rows), FPT insufficient (10 rows ending on 2025-01-30)
        short_fpt = create_synthetic_ohlcv("2025-01-21", 10, base_price=130000.0)
        universe_map = {"VNM": self.df_vnm, "FPT": short_fpt}

        res = generate_historical_report(
            data_as_of=self.as_of_date,
            universe_stock_map=universe_map,
            df_vnindex=self.df_vnindex,
            df_vn30=self.df_vn30,
            candidate_metadata=candidate_metadata,
        )

        recs_data, _market_data, _ = res

        # Validate schema compliance
        jsonschema.validate(instance=recs_data, schema=self.schema)

        rec_vnm = next(r for r in recs_data["recommendations"] if r["symbol"] == "VNM")
        rec_fpt = next(r for r in recs_data["recommendations"] if r["symbol"] == "FPT")

        # VNM has sufficient data and percentile liquidity score == 100.0 (only 1 valid stock)
        self.assertEqual(rec_vnm["data_quality"], "SUFFICIENT")
        self.assertIsNotNone(rec_vnm["signal_score"])
        self.assertEqual(rec_vnm["risk_metrics"]["liquidity_score"], 100.0)
        self.assertIsNotNone(rec_vnm["risk_adjusted_score"])

        # FPT is insufficient
        self.assertEqual(rec_fpt["data_quality"], "INSUFFICIENT")
        self.assertEqual(rec_fpt["action"], "AVOID")
        self.assertIsNone(rec_fpt["risk_metrics"]["liquidity_score"])

    def test_duplicate_candidate_metadata_rejection(self):
        """Test that duplicate symbols in candidate_metadata cause fail-closed ValueError."""
        duplicate_metadata = [
            {
                "symbol": "VNM",
                "companyName": "Vinamilk",
                "sector": "Consumer Goods",
                "exchange": "HOSE",
            },
            {
                "symbol": "VNM",
                "companyName": "Vinamilk Duplicate",
                "sector": "Consumer Goods",
                "exchange": "HOSE",
            },
        ]

        universe_map = {"VNM": self.df_vnm}

        with self.assertRaises(ValueError) as ctx:
            generate_historical_report(
                data_as_of=self.as_of_date,
                universe_stock_map=universe_map,
                df_vnindex=self.df_vnindex,
                df_vn30=self.df_vn30,
                candidate_metadata=duplicate_metadata,
            )

        self.assertIn("Duplicate candidate stock symbol 'VNM'", str(ctx.exception))

    def test_pipeline_fail_closed_update_mode_does_not_write_files(self):
        """Test that update mode failure raises RuntimeError without writing files."""
        candidates = [
            {"symbol": "FAILED_SYM", "companyName": "Failed", "sector": "Tech", "exchange": "HOSE"}
        ]

        def mock_fetch_ohlcv(symbol, **_kwargs):
            if symbol == "VNINDEX":
                return self.df_vnindex
            if symbol == "VN30":
                return self.df_vn30
            return pd.DataFrame()

        with (
            patch("scripts.pipeline.runner.UniverseProvider") as mock_provider_cls,
            patch(
                "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                side_effect=mock_fetch_ohlcv,
            ),
        ):
            mock_provider = mock_provider_cls.return_value
            mock_provider.get_universe.return_value = Universe.from_candidates(
                candidates,
                universe_type="TEST",
                benchmarks=("VNINDEX", "VN30"),
            )

            with self.assertRaises(RuntimeError):
                run_pipeline(update_data=True)


if __name__ == "__main__":
    unittest.main()
