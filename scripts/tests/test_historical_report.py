"""Unit and integration tests for reproducible historical report generation in scripts/generate_report.py."""

import sys
import unittest
from unittest.mock import MagicMock, patch

import jsonschema
import numpy as np
import pandas as pd

from scripts.generate_report import (
    canonicalize_report_for_reproducibility,
    generate_historical_report,
    load_schema,
    main,
    run_pipeline,
)


def make_synthetic_ohlcv(
    start_date: str = "2025-01-01",
    num_sessions: int = 60,
    base_price: float = 20000.0,
    trend: float = 100.0,
    volume: int = 500000,
) -> pd.DataFrame:
    """Helper to generate clean, valid canonical OHLCV DataFrame."""
    dates = pd.date_range(start_date, periods=num_sessions, freq="D")
    prices = np.linspace(base_price, base_price + (trend * num_sessions), num_sessions)
    return pd.DataFrame(
        {
            "time": dates,
            "open": prices - 50.0,
            "high": prices + 150.0,
            "low": prices - 150.0,
            "close": prices,
            "volume": [volume] * num_sessions,
        }
    )


class TestHistoricalReportGeneration(unittest.TestCase):
    def setUp(self):
        self.num_sessions = 60
        self.start_date = "2025-01-01"
        self.stock_df = make_synthetic_ohlcv(
            start_date=self.start_date, num_sessions=self.num_sessions, base_price=20000.0
        )
        self.vnindex_df = make_synthetic_ohlcv(
            start_date=self.start_date, num_sessions=self.num_sessions, base_price=1200.0, trend=2.0
        )
        self.vn30_df = make_synthetic_ohlcv(
            start_date=self.start_date, num_sessions=self.num_sessions, base_price=1400.0, trend=2.5
        )

        # Target date exists in history
        self.target_date = self.stock_df["time"].iloc[40].strftime("%Y-%m-%d")
        self.universe_map = {"FPT": self.stock_df}
        self.candidate_meta = [
            {"symbol": "FPT", "companyName": "FPT Corp", "sector": "Technology", "exchange": "HOSE"}
        ]
        self.schema = load_schema()

    def test_01_explicit_historical_date(self):
        """Test 1 — Given valid historical input and T = YYYY-MM-DD, historical report generates successfully."""
        res = generate_historical_report(
            data_as_of=self.target_date,
            universe_stock_map=self.universe_map,
            df_vnindex=self.vnindex_df,
            candidate_metadata=self.candidate_meta,
            df_vn30=self.vn30_df,
            data_source="test_historical",
        )

        recs_payload = res[0]
        self.assertEqual(recs_payload["data_as_of"], self.target_date)
        self.assertEqual(recs_payload["schema_version"], "2.0")
        self.assertEqual(recs_payload["summary"]["total_scanned"], 1)

        # Schema validation
        jsonschema.validate(instance=recs_payload, schema=self.schema)

    def test_02_repeated_generation_is_deterministic(self):
        """Test 2 — Repeated generation from identical historical inputs produces identical quantitative output."""
        res1 = generate_historical_report(
            data_as_of=self.target_date,
            universe_stock_map=self.universe_map,
            df_vnindex=self.vnindex_df,
            candidate_metadata=self.candidate_meta,
            df_vn30=self.vn30_df,
        )

        res2 = generate_historical_report(
            data_as_of=self.target_date,
            universe_stock_map=self.universe_map,
            df_vnindex=self.vnindex_df,
            candidate_metadata=self.candidate_meta,
            df_vn30=self.vn30_df,
        )

        canon1 = canonicalize_report_for_reproducibility(res1[0])
        canon2 = canonicalize_report_for_reproducibility(res2[0])

        self.assertEqual(canon1, canon2)

    def test_03_future_observation_rejected(self):
        """Test 3 — Future observation physically placed prior to data_as_of fails closed."""
        corrupted_df = self.stock_df.copy()
        # Physically insert a future row before target_date index
        future_row = pd.DataFrame(
            {
                "time": [pd.Timestamp("2026-12-31")],
                "open": [50000.0],
                "high": [51000.0],
                "low": [49000.0],
                "close": [50000.0],
                "volume": [1000000],
            }
        )
        corrupted_df = pd.concat(
            [corrupted_df.iloc[:20], future_row, corrupted_df.iloc[20:]], ignore_index=True
        )

        with self.assertRaises(ValueError):
            generate_historical_report(
                data_as_of=self.target_date,
                universe_stock_map={"FPT": corrupted_df},
                df_vnindex=self.vnindex_df,
                candidate_metadata=self.candidate_meta,
                df_vn30=self.vn30_df,
            )

    def test_04_missing_evaluation_date(self):
        """Test 4 — Requesting a date not present in historical price history fails closed."""
        missing_date = "2020-01-01"
        with self.assertRaises(ValueError):
            generate_historical_report(
                data_as_of=missing_date,
                universe_stock_map=self.universe_map,
                df_vnindex=self.vnindex_df,
                candidate_metadata=self.candidate_meta,
                df_vn30=self.vn30_df,
            )

    def test_05_duplicate_unsorted_dates(self):
        """Test 5 — Providing duplicate or unsorted historical observations fails closed."""
        # Unsorted dates
        unsorted_df = self.stock_df.sample(frac=1.0, random_state=42)
        with self.assertRaises(ValueError):
            generate_historical_report(
                data_as_of=self.target_date,
                universe_stock_map={"FPT": unsorted_df},
                df_vnindex=self.vnindex_df,
                candidate_metadata=self.candidate_meta,
                df_vn30=self.vn30_df,
            )

        # Duplicate dates
        dup_df = pd.concat([self.stock_df.iloc[:20], self.stock_df.iloc[19:]], ignore_index=True)
        with self.assertRaises(ValueError):
            generate_historical_report(
                data_as_of=self.target_date,
                universe_stock_map={"FPT": dup_df},
                df_vnindex=self.vnindex_df,
                candidate_metadata=self.candidate_meta,
                df_vn30=self.vn30_df,
            )

    def test_06_malformed_ohlcv(self):
        """Test 6 — Providing invalid OHLCV data fails closed."""
        # Negative volume
        bad_vol_df = self.stock_df.copy()
        bad_vol_df.loc[10, "volume"] = -100

        with self.assertRaises(ValueError):
            generate_historical_report(
                data_as_of=self.target_date,
                universe_stock_map={"FPT": bad_vol_df},
                df_vnindex=self.vnindex_df,
                candidate_metadata=self.candidate_meta,
                df_vn30=self.vn30_df,
            )

        # Invalid OHLC (high < low)
        bad_ohlc_df = self.stock_df.copy()
        bad_ohlc_df.loc[10, "high"] = 100.0
        bad_ohlc_df.loc[10, "low"] = 200.0

        with self.assertRaises(ValueError):
            generate_historical_report(
                data_as_of=self.target_date,
                universe_stock_map={"FPT": bad_ohlc_df},
                df_vnindex=self.vnindex_df,
                candidate_metadata=self.candidate_meta,
                df_vn30=self.vn30_df,
            )

    def test_07_no_fallback_to_latest_data(self):
        """Test 7 — Older historical report uses historical snapshot only, unaffected by future data after T."""
        target_idx = 35
        eval_date = self.stock_df["time"].iloc[target_idx].strftime("%Y-%m-%d")

        # Dataset A: sliced strictly at target_idx
        df_stock_a = self.stock_df.iloc[: target_idx + 1].copy()
        df_vnindex_a = self.vnindex_df.iloc[: target_idx + 1].copy()

        # Dataset B: full history with extreme future price spike at index 50
        df_stock_b = self.stock_df.copy()
        df_stock_b.loc[50:, "close"] = 999999.0

        df_vnindex_b = self.vnindex_df.copy()
        df_vnindex_b.loc[50:, "close"] = 9999.0

        res_a = generate_historical_report(
            data_as_of=eval_date,
            universe_stock_map={"FPT": df_stock_a},
            df_vnindex=df_vnindex_a,
            candidate_metadata=self.candidate_meta,
        )

        res_b = generate_historical_report(
            data_as_of=eval_date,
            universe_stock_map={"FPT": df_stock_b},
            df_vnindex=df_vnindex_b,
            candidate_metadata=self.candidate_meta,
        )

        canon_a = canonicalize_report_for_reproducibility(res_a[0])
        canon_b = canonicalize_report_for_reproducibility(res_b[0])

        self.assertEqual(
            canon_a,
            canon_b,
            "Historical report at T changed when future data after T was altered!",
        )

    def test_08_provenance_metadata(self):
        """Test 8 — Historical report contains expected provenance and metadata fields."""
        res = generate_historical_report(
            data_as_of=self.target_date,
            universe_stock_map=self.universe_map,
            df_vnindex=self.vnindex_df,
            candidate_metadata=self.candidate_meta,
            df_vn30=self.vn30_df,
            data_source="audit_reproduction",
        )

        payload = res[0]
        self.assertEqual(payload["data_as_of"], self.target_date)
        self.assertEqual(payload["source_date"], self.target_date)
        self.assertEqual(payload["schema_version"], "2.0")
        self.assertEqual(payload["data_source"], "audit_reproduction")
        self.assertIn("signal_model_version", payload)
        self.assertIn("universe_info", payload)

    def test_09_generated_at_does_not_affect_quantitative_output(self):
        """Test 9 — Changing runtime generated_at timestamp does not alter quantitative signal outputs."""
        res1 = generate_historical_report(
            data_as_of=self.target_date,
            universe_stock_map=self.universe_map,
            df_vnindex=self.vnindex_df,
            candidate_metadata=self.candidate_meta,
            df_vn30=self.vn30_df,
            generated_at="2020-01-01T00:00:00+00:00",
        )

        res2 = generate_historical_report(
            data_as_of=self.target_date,
            universe_stock_map=self.universe_map,
            df_vnindex=self.vnindex_df,
            candidate_metadata=self.candidate_meta,
            df_vn30=self.vn30_df,
            generated_at="2030-12-31T23:59:59+00:00",
        )

        # Quantitative fields must match
        canon1 = canonicalize_report_for_reproducibility(res1[0])
        canon2 = canonicalize_report_for_reproducibility(res2[0])
        self.assertEqual(canon1, canon2)

        # Raw payloads differ ONLY in generated_at
        self.assertNotEqual(res1[0]["generated_at"], res2[0]["generated_at"])
        self.assertEqual(
            res1[0]["recommendations"][0]["signal_score"],
            res2[0]["recommendations"][0]["signal_score"],
        )

    @patch("scripts.generate_report.get_historical_data")
    def test_10_existing_production_generation_remains_unchanged(self, mock_get_hist):
        """Test 10 — Existing production generation path (run_pipeline) continues to work without behavior change."""
        mock_get_hist.return_value = (self.stock_df, "OK", [])

        res = run_pipeline(update_data=False)
        self.assertIsNotNone(res)
        self.assertIn("recommendations", res[0])
        self.assertIn("market", res[1])

        # Validate schema
        jsonschema.validate(instance=res[0], schema=self.schema)

    @patch("scripts.generate_report.UniverseProvider")
    @patch("scripts.generate_report.open")
    def test_11_cli_as_of_mode_fails_closed_without_circular_dependency(
        self, mock_open_fn, mock_provider_cls
    ):
        """Regression Test — Historical '--as-of' CLI mode fails closed when no independent historical universe source exists, without reading history reports or calling UniverseProvider."""
        test_args = ["scripts/generate_report.py", "--as-of", self.target_date]
        with patch.object(sys, "argv", test_args):
            with self.assertRaises(ValueError) as ctx:
                main()
            self.assertIn(
                "contains no independent historical universe snapshot source", str(ctx.exception)
            )

        # Must NOT call current UniverseProvider
        mock_provider_cls.assert_not_called()
        # Must NOT attempt to open output history files as input
        mock_open_fn.assert_not_called()

    @patch("scripts.generate_report.save_json_files")
    @patch("scripts.generate_report.update_history_index")
    @patch("scripts.generate_report.evaluate_production_monitoring")
    @patch("scripts.generate_report.get_historical_data")
    def test_12_normal_production_cli_mode_saves_all_artifacts_and_runs_monitoring(
        self, mock_get_hist, mock_eval_mon, mock_update_idx, mock_save_json
    ):
        """Regression Test — Normal production CLI mode continues to save recommendations, market, history, and monitoring artifacts."""
        mock_get_hist.return_value = (self.stock_df, "OK", [])
        mock_mon_result = MagicMock()
        mock_mon_result.to_dict.return_value = {"overall_status": "PASS"}
        mock_eval_mon.return_value = mock_mon_result

        test_args = ["scripts/generate_report.py"]
        with patch.object(sys, "argv", test_args):
            main()

        # Production monitoring MUST be called in normal production mode
        mock_eval_mon.assert_called_once()

        saved_files = [call[0][0] for call in mock_save_json.call_args_list]

        # MUST save recommendations.json, market.json, monitoring.json
        self.assertIn("recommendations.json", saved_files)
        self.assertIn("market.json", saved_files)
        self.assertIn("monitoring.json", saved_files)

    def test_13_missing_candidate_metadata_raises_error(self):
        """Regression Test — Missing or empty candidate_metadata fails closed without silent fallback."""
        with self.assertRaises(ValueError):
            generate_historical_report(
                data_as_of=self.target_date,
                universe_stock_map=self.universe_map,
                df_vnindex=self.vnindex_df,
                candidate_metadata=None,
            )

        with self.assertRaises(ValueError):
            generate_historical_report(
                data_as_of=self.target_date,
                universe_stock_map=self.universe_map,
                df_vnindex=self.vnindex_df,
                candidate_metadata=[],
            )

    def test_14_malformed_and_duplicate_candidate_metadata_raises_error(self):
        """Regression Test — Malformed items, duplicate symbols, or universe mismatches in candidate_metadata fail closed."""
        # Non-dict item
        with self.assertRaises(TypeError):
            generate_historical_report(
                data_as_of=self.target_date,
                universe_stock_map=self.universe_map,
                df_vnindex=self.vnindex_df,
                candidate_metadata=["not_a_dict"],
            )

        # Missing required keys
        with self.assertRaises(ValueError):
            generate_historical_report(
                data_as_of=self.target_date,
                universe_stock_map=self.universe_map,
                df_vnindex=self.vnindex_df,
                candidate_metadata=[{"symbol": "FPT"}],
            )

        # Duplicate symbol
        dup_meta = [
            {"symbol": "FPT", "companyName": "FPT Corp", "sector": "Technology"},
            {"symbol": "FPT", "companyName": "FPT Duplicate", "sector": "Technology"},
        ]
        with self.assertRaises(ValueError):
            generate_historical_report(
                data_as_of=self.target_date,
                universe_stock_map=self.universe_map,
                df_vnindex=self.vnindex_df,
                candidate_metadata=dup_meta,
            )

        # Mismatch with universe_stock_map
        mismatch_meta = [{"symbol": "VCB", "companyName": "Vietcombank", "sector": "Banking"}]
        with self.assertRaises(ValueError):
            generate_historical_report(
                data_as_of=self.target_date,
                universe_stock_map=self.universe_map,
                df_vnindex=self.vnindex_df,
                candidate_metadata=mismatch_meta,
            )

    @patch("scripts.generate_report.UniverseProvider")
    def test_15_changing_current_universe_provider_state_does_not_affect_historical_report(
        self, mock_provider_cls
    ):
        """Regression Test — Historical report uses explicit candidate metadata only, completely ignoring UniverseProvider state changes."""
        mock_provider_instance = MagicMock()
        mock_provider_instance.candidates = [
            {"symbol": "XYZ", "companyName": "XYZ Corp", "sector": "Other"}
        ]
        mock_provider_cls.return_value = mock_provider_instance

        res = generate_historical_report(
            data_as_of=self.target_date,
            universe_stock_map=self.universe_map,
            df_vnindex=self.vnindex_df,
            candidate_metadata=self.candidate_meta,
        )

        rec = res[0]["recommendations"][0]
        self.assertEqual(rec["symbol"], "FPT")
        self.assertEqual(rec["company_name"], "FPT Corp")
        self.assertEqual(rec["sector"], "Technology")
        self.assertNotEqual(rec["company_name"], "XYZ Corp")

    def test_16_no_unknown_metadata_fallback(self):
        """Regression Test — Historical mode never silently defaults to 'Unknown' metadata."""
        res = generate_historical_report(
            data_as_of=self.target_date,
            universe_stock_map=self.universe_map,
            df_vnindex=self.vnindex_df,
            candidate_metadata=self.candidate_meta,
        )

        rec = res[0]["recommendations"][0]
        self.assertNotEqual(rec["company_name"], "Unknown")
        self.assertNotEqual(rec["sector"], "Unknown")


if __name__ == "__main__":
    unittest.main()
