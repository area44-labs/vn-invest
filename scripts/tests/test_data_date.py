"""Regression test suite for data-date semantics in the Python data pipeline."""

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd

from scripts.generate_report import run_pipeline
from scripts.lib.recommendation import generate_recommendation
from scripts.lib.vietnam_market import extract_latest_trading_date


class TestDataDateSemantics(unittest.TestCase):
    def test_extract_latest_trading_date(self):
        """Verify extraction of latest trading date from OHLCV DataFrames."""
        df_time = pd.DataFrame(
            {
                "time": ["2026-09-01", "2026-09-02", "2026-09-10"],
                "close": [10.0, 11.0, 12.0],
            }
        )
        self.assertEqual(extract_latest_trading_date(df_time), "2026-09-10")

        df_date = pd.DataFrame(
            {
                "date": [pd.Timestamp("2026-08-20"), pd.Timestamp("2026-08-29")],
                "close": [10.0, 11.0],
            }
        )
        self.assertEqual(extract_latest_trading_date(df_date), "2026-08-29")

        # Empty DataFrame -> None
        self.assertIsNone(extract_latest_trading_date(pd.DataFrame()))
        self.assertIsNone(extract_latest_trading_date(None))

    def test_empty_data_cannot_produce_fake_market_date(self):
        """Verify empty datasets produce None for data_as_of and source_date (never today's date)."""
        empty_df = pd.DataFrame()
        with patch("scripts.generate_report.get_historical_data") as mock_get_hist:
            mock_get_hist.return_value = (empty_df, "INSUFFICIENT_HISTORICAL_DATA", [])
            recs_payload, mkt_payload, _ = run_pipeline(update_data=False)

            self.assertIsNone(recs_payload["data_as_of"])
            self.assertIsNone(recs_payload["source_date"])
            self.assertIsNone(mkt_payload["data_as_of"])
            self.assertIsNone(mkt_payload["source_date"])

            # generated_at is still a valid current timestamp
            self.assertIsNotNone(recs_payload["generated_at"])
            parsed_gen = datetime.fromisoformat(recs_payload["generated_at"])
            self.assertEqual(parsed_gen.tzinfo, timezone.utc)

    def test_generated_at_differs_from_data_as_of(self):
        """Verify generated_at is a current execution timestamp while data_as_of reflects historical OHLCV data."""
        historical_df = pd.DataFrame(
            {
                "time": pd.date_range("2025-01-01", periods=30, freq="D"),
                "open": [10.0] * 30,
                "high": [11.0] * 30,
                "low": [9.5] * 30,
                "close": [10.5] * 30,
                "volume": [100000] * 30,
            }
        )

        with patch("scripts.generate_report.get_historical_data") as mock_get_hist:
            mock_get_hist.return_value = (historical_df, "REAL_DATA", [])
            recs_payload, _, _ = run_pipeline(update_data=False)

            self.assertEqual(recs_payload["data_as_of"], "2025-01-30")
            self.assertEqual(recs_payload["source_date"], "2025-01-30")

            # generated_at must be an ISO UTC timestamp representing today's execution time
            gen_at_str = recs_payload["generated_at"]
            self.assertTrue(
                gen_at_str.endswith("+00:00") or "Z" in gen_at_str or "+00:00" in gen_at_str
            )
            parsed_gen = datetime.fromisoformat(gen_at_str)
            self.assertNotEqual(parsed_gen.strftime("%Y-%m-%d"), "2025-01-30")

    def test_stock_level_data_as_of_preservation(self):
        """Verify individual stocks preserve their actual latest data date even if older than market date."""
        df_stock_old = pd.DataFrame(
            {
                "time": pd.date_range("2026-08-01", periods=25, freq="D"),
                "open": [10.0] * 25,
                "high": [11.0] * 25,
                "low": [9.5] * 25,
                "close": [10.5] * 25,
                "volume": [100000] * 25,
            }
        )

        rec = generate_recommendation(
            symbol="TEST",
            company_name="Test Stock",
            sector="Tech",
            exchange="HOSE",
            df_stock=df_stock_old,
            market_regime_info={"regime": "BULL"},
            data_source="REAL_DATA",
        )

        self.assertEqual(rec["data_as_of"], "2026-08-25")
        self.assertEqual(rec["data_source"], "REAL_DATA")

    def test_stale_data_is_detectable(self):
        """Verify stale data (data_as_of < current date) can be detected."""
        stale_date_str = "2020-01-01"
        data_date = datetime.strptime(stale_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        current_date = datetime.now(timezone.utc)

        days_diff = (current_date - data_date).days
        self.assertGreater(days_diff, 100)  # Clearly stale


if __name__ == "__main__":
    unittest.main()
