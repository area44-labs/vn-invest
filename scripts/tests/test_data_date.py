"""Regression test suite for data-date semantics in the Python data pipeline."""

import unittest
from datetime import UTC, datetime
from unittest.mock import patch

import jsonschema
import pandas as pd

from scripts.generate_report import load_schema, run_pipeline
from scripts.generate_report import main as generate_report_main
from scripts.lib.recommendation import SIGNAL_MODEL_VERSION, generate_recommendation
from scripts.lib.vietnam_market import extract_latest_trading_date


class TestDataDateSemantics(unittest.TestCase):
    def test_extract_latest_trading_date_unsorted_and_invalid(self):
        """Test C: extract_latest_trading_date parses valid dates, ignores invalid/nulls, and returns max date."""
        df_unsorted = pd.DataFrame(
            {
                "time": ["2026-09-10", "2026-09-12", "2026-09-11", "invalid-date", None],
                "close": [10.0, 11.0, 12.0, 13.0, 14.0],
            }
        )
        self.assertEqual(extract_latest_trading_date(df_unsorted), "2026-09-12")

        df_all_invalid = pd.DataFrame({"time": ["not-a-date", "foo", None]})
        self.assertIsNone(extract_latest_trading_date(df_all_invalid))

        # Empty DataFrame -> None
        self.assertIsNone(extract_latest_trading_date(pd.DataFrame()))
        self.assertIsNone(extract_latest_trading_date(None))

    def test_market_date_independent_from_stock_date(self):
        """Test A: market.data_as_of is derived from VNINDEX and independent from stock-level dates."""
        df_vnindex = pd.DataFrame(
            {
                "time": pd.date_range("2026-09-01", periods=11, freq="D"),
                "open": [1000.0] * 11,
                "high": [1010.0] * 11,
                "low": [990.0] * 11,
                "close": [1000.0] * 11,
                "volume": [1000000] * 11,
            }
        )  # latest date = 2026-09-11

        df_stock_later = pd.DataFrame(
            {
                "time": pd.date_range("2026-09-01", periods=12, freq="D"),
                "open": [10.0] * 12,
                "high": [11.0] * 12,
                "low": [9.5] * 12,
                "close": [10.5] * 12,
                "volume": [100000] * 12,
            }
        )  # latest date = 2026-09-12

        def side_effect(symbol, **kwargs):
            if symbol == "VNINDEX":
                return df_vnindex, "REAL_DATA", []
            return df_stock_later, "REAL_DATA", []

        with patch("scripts.generate_report.get_historical_data", side_effect=side_effect):
            recs_payload, mkt_payload, _ = run_pipeline(update_data=False)

            self.assertEqual(mkt_payload["data_as_of"], "2026-09-11")
            self.assertEqual(recs_payload["data_as_of"], "2026-09-11")

            fpt_rec = next(r for r in recs_payload["recommendations"] if r["symbol"] == "FPT")
            self.assertEqual(fpt_rec["data_as_of"], "2026-09-12")

    def test_no_history_artifact_when_data_as_of_is_none(self):
        """Test B: When data_as_of is None, no history JSON artifact is created and index is not updated."""
        empty_df = pd.DataFrame()
        with (
            patch("scripts.generate_report.get_historical_data") as mock_get_hist,
            patch("scripts.generate_report.save_json_files") as mock_save,
            patch("scripts.generate_report.update_history_index") as mock_update_index,
        ):
            mock_get_hist.return_value = (empty_df, "INSUFFICIENT_HISTORICAL_DATA", [])

            recs_payload, mkt_payload, _ = run_pipeline(update_data=False)
            self.assertIsNone(recs_payload["data_as_of"])
            self.assertIsNone(recs_payload["source_date"])
            self.assertIsNone(mkt_payload["data_as_of"])
            self.assertIsNone(mkt_payload["source_date"])

            # Run main pipeline execution
            with patch("sys.argv", ["generate_report.py"]):
                generate_report_main()

            mock_update_index.assert_not_called()

            # Ensure save_json_files was called only for recommendations.json and market.json, NOT for history/YYYY-MM-DD.json
            saved_paths = [call.args[0] for call in mock_save.call_args_list]
            self.assertIn("recommendations.json", saved_paths)
            self.assertIn("market.json", saved_paths)
            for p in saved_paths:
                self.assertFalse(p.startswith("history/"))

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
        data_date = datetime.strptime(stale_date_str, "%Y-%m-%d").replace(tzinfo=UTC)
        current_date = datetime.now(UTC)

        days_diff = (current_date - data_date).days
        self.assertGreater(days_diff, 100)  # Clearly stale


class TestReportProvenanceMetadata(unittest.TestCase):
    def test_top_level_provenance_metadata_presence(self):
        """Verify report payload contains all required provenance metadata fields."""
        df_vnindex = pd.DataFrame(
            {
                "time": pd.date_range("2026-09-01", periods=20, freq="D"),
                "open": [1000.0] * 20,
                "high": [1010.0] * 20,
                "low": [990.0] * 20,
                "close": [1000.0] * 20,
                "volume": [1000000] * 20,
            }
        )

        with patch("scripts.generate_report.get_historical_data") as mock_get_hist:
            mock_get_hist.return_value = (df_vnindex, "REAL_DATA", [])
            recs_payload, _mkt_payload, history_payload = run_pipeline(update_data=False)

            required_provenance_fields = [
                "schema_version",
                "signal_model_version",
                "generated_at",
                "data_as_of",
                "source_date",
                "data_source",
            ]
            for field in required_provenance_fields:
                self.assertIn(field, recs_payload, f"Missing required provenance field: {field}")
                self.assertIn(
                    field, history_payload, f"Missing required provenance field in history: {field}"
                )

    def test_generated_at_is_valid_utc_timestamp(self):
        """Verify generated_at is a valid ISO 8601 UTC timestamp."""
        df_vnindex = pd.DataFrame(
            {
                "time": pd.date_range("2026-09-01", periods=20, freq="D"),
                "open": [1000.0] * 20,
                "high": [1010.0] * 20,
                "low": [990.0] * 20,
                "close": [1000.0] * 20,
                "volume": [1000000] * 20,
            }
        )

        with patch("scripts.generate_report.get_historical_data") as mock_get_hist:
            mock_get_hist.return_value = (df_vnindex, "REAL_DATA", [])
            recs_payload, _, _ = run_pipeline(update_data=False)

            gen_at_str = recs_payload["generated_at"]
            self.assertIsInstance(gen_at_str, str)
            dt = datetime.fromisoformat(gen_at_str)
            self.assertIsNotNone(dt.tzinfo)
            self.assertEqual(dt.utcoffset().total_seconds(), 0)

    def test_schema_and_signal_model_versions(self):
        """Verify schema_version is '2.0' and signal_model_version matches SIGNAL_MODEL_VERSION."""
        df_vnindex = pd.DataFrame(
            {
                "time": pd.date_range("2026-09-01", periods=20, freq="D"),
                "open": [1000.0] * 20,
                "high": [1010.0] * 20,
                "low": [990.0] * 20,
                "close": [1000.0] * 20,
                "volume": [1000000] * 20,
            }
        )

        with patch("scripts.generate_report.get_historical_data") as mock_get_hist:
            mock_get_hist.return_value = (df_vnindex, "REAL_DATA", [])
            recs_payload, _, _ = run_pipeline(update_data=False)

            self.assertEqual(recs_payload["schema_version"], "2.0")
            self.assertEqual(recs_payload["signal_model_version"], SIGNAL_MODEL_VERSION)
            self.assertEqual(SIGNAL_MODEL_VERSION, "2.0")

    def test_data_as_of_and_source_date_reflect_pipeline_data(self):
        """Verify data_as_of and source_date reflect actual latest trading date from pipeline."""
        df_vnindex = pd.DataFrame(
            {
                "time": pd.date_range("2026-09-01", periods=20, freq="D"),
                "open": [1000.0] * 20,
                "high": [1010.0] * 20,
                "low": [990.0] * 20,
                "close": [1000.0] * 20,
                "volume": [1000000] * 20,
            }
        )

        with patch("scripts.generate_report.get_historical_data") as mock_get_hist:
            mock_get_hist.return_value = (df_vnindex, "REAL_DATA", [])
            recs_payload, _, _ = run_pipeline(update_data=False)

            self.assertEqual(recs_payload["data_as_of"], "2026-09-20")
            self.assertEqual(recs_payload["source_date"], "2026-09-20")

    def test_provider_metadata_is_not_fabricated(self):
        """Verify provider metadata (data_source) reflects actual provider boundary result."""
        empty_df = pd.DataFrame()

        with patch("scripts.generate_report.get_historical_data") as mock_get_hist:
            mock_get_hist.return_value = (empty_df, "INSUFFICIENT_HISTORICAL_DATA", [])
            recs_payload, _, _ = run_pipeline(update_data=False)

            self.assertIsNone(recs_payload["data_source"])

    def test_schema_validation_passes_with_provenance_metadata(self):
        """Verify recommendations payload with provenance metadata validates against JSON schema."""
        df_vnindex = pd.DataFrame(
            {
                "time": pd.date_range("2026-09-01", periods=20, freq="D"),
                "open": [1000.0] * 20,
                "high": [1010.0] * 20,
                "low": [990.0] * 20,
                "close": [1000.0] * 20,
                "volume": [1000000] * 20,
            }
        )

        with patch("scripts.generate_report.get_historical_data") as mock_get_hist:
            mock_get_hist.return_value = (df_vnindex, "REAL_DATA", [])
            recs_payload, _, _ = run_pipeline(update_data=False)

            schema = load_schema()
            jsonschema.validate(instance=recs_payload, schema=schema)


if __name__ == "__main__":
    unittest.main()
