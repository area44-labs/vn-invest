"""Unit tests for Production Monitoring Module (scripts/lib/monitoring.py)."""

import copy
import json
import os
import tempfile
import unittest

import pandas as pd

from scripts.lib.config import SIGNAL_MODEL_VERSION
from scripts.lib.monitoring import (
    CheckResult,
    check_data_freshness,
    check_history_index_status,
    check_numeric_sanity,
    check_ohlcv_data_quality,
    check_required_artifacts,
    check_schema_validation,
    check_symbol_processing_counts,
    evaluate_production_monitoring,
    find_nan_or_inf,
    validate_monitoring_payload,
)
from scripts.lib.recommendation import generate_recommendation
from scripts.lib.regime import detect_market_regime


class TestProductionMonitoring(unittest.TestCase):
    """Test suite for production monitoring checks, fail-closed rules, and serialization."""

    def setUp(self):
        self.reference_date = "2026-09-17"
        self.healthy_market = {
            "regime": "STRONG_BULL",
            "confidence": 0.85,
            "metrics": {
                "vnindex_value": 1280.50,
                "vnindex_change_pct": 1.25,
                "vn30_change_pct": 1.10,
                "market_breadth_ratio": 0.70,
                "volatility": 0.12,
                "volume_20d_ratio": 1.15,
            },
        }
        self.healthy_summary = {
            "total_scanned": 2,
            "buy_count": 1,
            "watch_count": 1,
            "hold_count": 0,
            "sell_count": 0,
            "avoid_count": 0,
        }
        self.healthy_recommendations = [
            {
                "symbol": "FPT",
                "company_name": "FPT Corporation",
                "exchange": "HOSE",
                "sector": "Công nghệ",
                "action": "BUY",
                "data_quality": "SUFFICIENT",
                "data_quality_issues": [],
                "data_as_of": "2026-09-17",
                "data_source": "REAL_DATA",
                "signal_score": 82.5,
                "risk_adjusted_score": 78.0,
                "confidence": 0.85,
                "risk_level": "LOW",
                "expected_return": {
                    "expected_return_5d": 2.5,
                    "expected_return_10d": 4.0,
                    "expected_return_20d": 6.5,
                },
                "risk_metrics": {
                    "var_t25": -3.2,
                    "es_t25": -4.5,
                    "volatility_60d": 0.18,
                    "max_drawdown": -8.5,
                    "liquidity_score": 85.0,
                    "avg_value_20d": 120.5,
                },
                "trade_plan": {
                    "current_price": 130000.0,
                    "entry_low": 128000.0,
                    "entry_high": 130000.0,
                    "stop_loss": 122000.0,
                    "tp1": 138000.0,
                    "tp2": 145000.0,
                    "risk_reward": 2.1,
                    "position_percent": 15.0,
                },
                "reasons": ["Strong trend", "High volume"],
                "warnings": [],
                "invalidation": ["Close below stop loss"],
            },
            {
                "symbol": "MWG",
                "company_name": "Mobile World Corporation",
                "exchange": "HOSE",
                "sector": "Bán lẻ",
                "action": "WATCH",
                "data_quality": "SUFFICIENT",
                "data_quality_issues": [],
                "data_as_of": "2026-09-17",
                "data_source": "REAL_DATA",
                "signal_score": 65.0,
                "risk_adjusted_score": 62.0,
                "confidence": 0.75,
                "risk_level": "MEDIUM",
                "expected_return": {
                    "expected_return_5d": 1.5,
                    "expected_return_10d": 2.5,
                    "expected_return_20d": 4.0,
                },
                "risk_metrics": {
                    "var_t25": -4.0,
                    "es_t25": -5.5,
                    "volatility_60d": 0.22,
                    "max_drawdown": -12.0,
                    "liquidity_score": 80.0,
                    "avg_value_20d": 95.0,
                },
                "trade_plan": {
                    "current_price": 60000.0,
                    "entry_low": 58000.0,
                    "entry_high": 60000.0,
                    "stop_loss": 55000.0,
                    "tp1": 65000.0,
                    "tp2": 70000.0,
                    "risk_reward": 1.8,
                    "position_percent": 10.0,
                },
                "reasons": ["Consolidating near support"],
                "warnings": [],
                "invalidation": ["Close below support"],
            },
        ]
        self.healthy_payload = {
            "schema_version": "2.0",
            "signal_model_version": SIGNAL_MODEL_VERSION,
            "generated_at": "2026-09-17T06:00:00+00:00",
            "data_as_of": "2026-09-17",
            "source_date": "2026-09-17",
            "data_source": "REAL_DATA",
            "universe_info": {"universe_type": "TEST", "universe_size": 2},
            "market": self.healthy_market,
            "summary": self.healthy_summary,
            "recommendations": self.healthy_recommendations,
        }

    def test_healthy_production_data_passes(self):
        """Verify healthy production data produces overall status 'PASS'."""
        res = evaluate_production_monitoring(
            recommendations_payload=self.healthy_payload,
            reference_date=self.reference_date,
        )
        self.assertEqual(res.overall_status, "PASS")
        self.assertEqual(res.data_as_of, "2026-09-17")
        self.assertTrue(validate_monitoring_payload(res.to_dict()))

    def test_missing_required_artifact_fails(self):
        """Verify missing required JSON artifact causes check failure ('FAIL')."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chk = check_required_artifacts(tmpdir, data_as_of="2026-09-17")
            self.assertEqual(chk.status, "FAIL")
            self.assertIn("Missing files", chk.message)

    def test_malformed_artifact_fails(self):
        """Verify malformed non-JSON artifact causes check failure ('FAIL')."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_file = os.path.join(tmpdir, "recommendations.json")
            with open(bad_file, "w") as f:
                f.write("{ invalid json payload ...")

            chk = check_required_artifacts(tmpdir)
            self.assertEqual(chk.status, "FAIL")
            self.assertIn("Unreadable files", chk.message)

    def test_schema_invalid_artifact_fails(self):
        """Verify schema-invalid payload produces schema validation check failure ('FAIL')."""
        bad_payload = copy.deepcopy(self.healthy_payload)
        del bad_payload["schema_version"]  # Missing required top-level key

        chk = check_schema_validation(bad_payload)
        self.assertEqual(chk.status, "FAIL")
        self.assertIn("schema_version", chk.message)

    def test_summary_action_count_mismatch_fails(self):
        """Verify summary action count mismatch with actual recommendations produces status 'FAIL'."""
        bad_payload = copy.deepcopy(self.healthy_payload)
        # Summary claims 2 BUY, 0 WATCH, but recommendations has 1 BUY and 1 WATCH
        bad_payload["summary"]["buy_count"] = 2
        bad_payload["summary"]["watch_count"] = 0

        chk = check_symbol_processing_counts(bad_payload)
        self.assertEqual(chk.status, "FAIL")
        self.assertIn("buy_count", chk.message)

    def test_total_scanned_mismatch_fails(self):
        """Verify total_scanned mismatch with recommendations length produces status 'FAIL'."""
        bad_payload = copy.deepcopy(self.healthy_payload)
        bad_payload["summary"]["total_scanned"] = 5

        chk = check_symbol_processing_counts(bad_payload)
        self.assertEqual(chk.status, "FAIL")
        self.assertIn("Summary counts mismatch", chk.message)

    def test_invalid_date_string_in_history_index_fails(self):
        """Verify invalid date string in history index produces status 'FAIL'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = os.path.join(tmpdir, "history")
            os.makedirs(hist_dir, exist_ok=True)
            index_path = os.path.join(hist_dir, "index.json")

            with open(index_path, "w") as f:
                json.dump({"dates": ["2026-02-30", "2026-09-16"]}, f)  # Invalid calendar date

            chk = check_history_index_status(tmpdir)
            self.assertEqual(chk.status, "FAIL")
            self.assertIn("invalid date entries", chk.message.lower())

    def test_missing_history_file_for_index_date_fails(self):
        """Verify date in history index pointing to missing file produces status 'FAIL'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = os.path.join(tmpdir, "history")
            os.makedirs(hist_dir, exist_ok=True)
            index_path = os.path.join(hist_dir, "index.json")

            # Index lists 2026-09-17 and 2026-09-16, but 2026-09-16.json does not exist
            with open(index_path, "w") as f:
                json.dump({"dates": ["2026-09-17", "2026-09-16"]}, f)

            with open(os.path.join(hist_dir, "2026-09-17.json"), "w") as f:
                f.write("{}")

            chk = check_history_index_status(tmpdir)
            self.assertEqual(chk.status, "FAIL")
            self.assertIn("missing report files", chk.message.lower())

    def test_invalid_unsorted_duplicate_data_fails(self):
        """Verify duplicate or unsorted dates in history index fail closed ('FAIL')."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = os.path.join(tmpdir, "history")
            os.makedirs(hist_dir, exist_ok=True)
            index_path = os.path.join(hist_dir, "index.json")

            # Duplicate date entries in index
            with open(index_path, "w") as f:
                json.dump({"dates": ["2026-09-17", "2026-09-17"]}, f)

            with open(os.path.join(hist_dir, "2026-09-17.json"), "w") as f:
                f.write("{}")

            chk = check_history_index_status(tmpdir, data_as_of="2026-09-17")
            self.assertEqual(chk.status, "FAIL")
            self.assertIn("duplicate", chk.message.lower())

            # Unsorted date entries in index
            with open(index_path, "w") as f:
                json.dump({"dates": ["2026-09-16", "2026-09-17"]}, f)

            with open(os.path.join(hist_dir, "2026-09-16.json"), "w") as f:
                f.write("{}")

            chk_unsorted = check_history_index_status(tmpdir, data_as_of="2026-09-17")
            self.assertEqual(chk_unsorted.status, "FAIL")
            self.assertIn("descending", chk_unsorted.message.lower())

    def test_ohlcv_duplicate_and_unsorted_fails(self):
        """Verify duplicate or unsorted dates in OHLCV DataFrame produce check failure ('FAIL')."""
        dates = ["2026-09-17", "2026-09-16", "2026-09-15"]  # Reverse order
        df_unsorted = pd.DataFrame(
            {
                "time": dates,
                "open": [10.0, 10.0, 10.0],
                "high": [11.0, 11.0, 11.0],
                "low": [9.0, 9.0, 9.0],
                "close": [10.5, 10.5, 10.5],
                "volume": [1000, 1000, 1000],
            }
        )
        chk = check_ohlcv_data_quality(df_unsorted, "TEST_SYM")
        self.assertEqual(chk.status, "FAIL")

    def test_expected_insufficient_data_condition(self):
        """Verify expected insufficient-data condition for minority stock is tracked as PASS."""
        insufficient_rec = {
            "symbol": "ABC",
            "company_name": "ABC Corp",
            "exchange": "HOSE",
            "sector": "BĐS",
            "action": "AVOID",
            "data_quality": "INSUFFICIENT",
            "data_quality_issues": ["insufficient_history"],
            "data_as_of": "2026-09-17",
            "data_source": "REAL_DATA",
            "signal_score": None,
            "risk_adjusted_score": None,
            "confidence": 0.0,
            "risk_level": None,
            "expected_return": {
                "expected_return_5d": None,
                "expected_return_10d": None,
                "expected_return_20d": None,
            },
            "risk_metrics": {
                "var_t25": None,
                "es_t25": None,
                "volatility_60d": None,
                "max_drawdown": None,
                "liquidity_score": None,
                "avg_value_20d": None,
            },
            "trade_plan": {
                "current_price": None,
                "entry_low": None,
                "entry_high": None,
                "stop_loss": None,
                "tp1": None,
                "tp2": None,
                "risk_reward": None,
                "position_percent": None,
            },
            "reasons": [],
            "warnings": ["Insufficient historical data"],
            "invalidation": [],
        }

        # 9 out of 10 stocks processed (90% processed ratio)
        large_recs = [self.healthy_recommendations[0]] * 9 + [insufficient_rec]
        payload_large = copy.deepcopy(self.healthy_payload)
        payload_large["recommendations"] = large_recs
        payload_large["summary"] = {
            "total_scanned": 10,
            "buy_count": 9,
            "watch_count": 0,
            "hold_count": 0,
            "sell_count": 0,
            "avoid_count": 1,
        }

        chk_large = check_symbol_processing_counts(payload_large)
        self.assertEqual(chk_large.status, "PASS")
        self.assertEqual(chk_large.measured_value["processed_ratio"], 0.90)

    def test_avoid_with_sufficient_data_quality_not_counted_as_insufficient(self):
        """Verify AVOID action with SUFFICIENT data_quality is NOT counted as insufficient data."""
        avoid_sufficient_rec = copy.deepcopy(self.healthy_recommendations[0])
        avoid_sufficient_rec["symbol"] = "XYZ"
        avoid_sufficient_rec["action"] = "AVOID"
        avoid_sufficient_rec["data_quality"] = "SUFFICIENT"

        payload = copy.deepcopy(self.healthy_payload)
        payload["recommendations"].append(avoid_sufficient_rec)
        payload["summary"] = {
            "total_scanned": 3,
            "buy_count": 1,
            "watch_count": 1,
            "hold_count": 0,
            "sell_count": 0,
            "avoid_count": 1,
        }

        chk = check_symbol_processing_counts(payload)
        self.assertEqual(chk.status, "PASS")
        self.assertEqual(chk.measured_value["insufficient_count"], 0)
        self.assertEqual(chk.measured_value["processed_count"], 3)

    def test_nan_inf_in_market_payload_fails(self):
        """Verify NaN or Inf in market payload causes numeric_sanity check failure ('FAIL')."""
        bad_market = copy.deepcopy(self.healthy_market)
        bad_market["metrics"]["vnindex_value"] = float("nan")

        chk = check_numeric_sanity(self.healthy_payload, market_payload=bad_market)
        self.assertEqual(chk.status, "FAIL")
        self.assertIn("NaN", chk.message)

        bad_market_inf = copy.deepcopy(self.healthy_market)
        bad_market_inf["metrics"]["volatility"] = float("inf")

        chk_inf = check_numeric_sanity(self.healthy_payload, market_payload=bad_market_inf)
        self.assertEqual(chk_inf.status, "FAIL")
        self.assertIn("Inf", chk_inf.message)

    def test_nan_inf_detection(self):
        """Verify NaN or Inf float values in recommendations payload cause numeric_sanity check failure ('FAIL')."""
        bad_payload = copy.deepcopy(self.healthy_payload)
        bad_payload["recommendations"][0]["signal_score"] = float("nan")

        issues = find_nan_or_inf(bad_payload)
        self.assertTrue(len(issues) > 0)

        chk = check_numeric_sanity(bad_payload)
        self.assertEqual(chk.status, "FAIL")
        self.assertIn("NaN", chk.message)

        bad_payload_inf = copy.deepcopy(self.healthy_payload)
        bad_payload_inf["recommendations"][0]["risk_metrics"]["var_t25"] = float("inf")

        chk_inf = check_numeric_sanity(bad_payload_inf)
        self.assertEqual(chk_inf.status, "FAIL")
        self.assertIn("Inf", chk_inf.message)

    def test_benchmark_ohlcv_checks_executed(self):
        """Verify production monitoring executes benchmark OHLCV checks when DataFrames are passed."""
        dates = pd.date_range("2026-01-01", periods=50, freq="B").strftime("%Y-%m-%d").tolist()
        df_vnindex = pd.DataFrame(
            {
                "time": dates,
                "open": [1200.0] * 50,
                "high": [1210.0] * 50,
                "low": [1190.0] * 50,
                "close": [1205.0] * 50,
                "volume": [500000] * 50,
            }
        )
        df_vn30 = pd.DataFrame(
            {
                "time": dates,
                "open": [1300.0] * 50,
                "high": [1310.0] * 50,
                "low": [1290.0] * 50,
                "close": [1305.0] * 50,
                "volume": [300000] * 50,
            }
        )

        res = evaluate_production_monitoring(
            recommendations_payload=self.healthy_payload,
            reference_date=self.reference_date,
            df_vnindex=df_vnindex,
            df_vn30=df_vn30,
        )

        check_names = [c.check_name for c in res.checks]
        self.assertIn("ohlcv_quality_vnindex", check_names)
        self.assertIn("ohlcv_quality_vn30", check_names)

        vn_chk = next(c for c in res.checks if c.check_name == "ohlcv_quality_vnindex")
        self.assertEqual(vn_chk.status, "PASS")

    def test_warning_condition(self):
        """Verify warning condition for slightly stale data produces status 'WARNING'."""
        chk = check_data_freshness("2026-09-12", reference_date="2026-09-17")  # 5 days stale
        self.assertEqual(chk.status, "WARNING")
        self.assertIn("slightly stale", chk.message)

    def test_future_data_freshness_fails(self):
        """Verify future data_as_of relative to reference_date causes check failure ('FAIL')."""
        chk = check_data_freshness("2026-09-20", reference_date="2026-09-17")
        self.assertEqual(chk.status, "FAIL")
        self.assertIn("future", chk.message.lower())

    def test_deterministic_serialization(self):
        """Verify CheckResult and PipelineMonitoringResult produce deterministic serializable dicts."""
        chk = CheckResult(
            check_name="test_chk",
            status="PASS",
            measured_value={"score": 10.5, "bad_val": float("nan")},
            expected_condition="condition",
            message="msg",
        )
        d = chk.to_dict()
        self.assertEqual(d["measured_value"]["bad_val"], "NaN")

        res = evaluate_production_monitoring(
            recommendations_payload=self.healthy_payload,
            reference_date=self.reference_date,
        )
        res_dict1 = res.to_dict()
        res_dict2 = res.to_dict()

        json_str1 = json.dumps(res_dict1, indent=2)
        json_str2 = json.dumps(res_dict2, indent=2)

        self.assertEqual(json_str1, json_str2)

    def test_monitoring_does_not_mutate_payloads(self):
        """Verify monitoring execution does not mutate input recommendation or market payloads."""
        payload_orig = copy.deepcopy(self.healthy_payload)
        payload_copy = copy.deepcopy(self.healthy_payload)

        _res = evaluate_production_monitoring(
            recommendations_payload=payload_copy,
            reference_date=self.reference_date,
        )

        self.assertEqual(payload_copy, payload_orig)

    def test_monitoring_does_not_change_signal_or_regime_outputs(self):
        """Verify monitoring layer does not alter recommendation or market regime calculation outputs."""
        dates = pd.date_range("2026-01-01", periods=100, freq="B").strftime("%Y-%m-%d").tolist()
        df_stock = pd.DataFrame(
            {
                "time": dates,
                "open": [100.0] * 100,
                "high": [105.0] * 100,
                "low": [95.0] * 100,
                "close": [102.0] * 100,
                "volume": [10000] * 100,
            }
        )
        df_vnindex = pd.DataFrame(
            {
                "time": dates,
                "open": [1200.0] * 100,
                "high": [1210.0] * 100,
                "low": [1190.0] * 100,
                "close": [1205.0] * 100,
                "volume": [500000] * 100,
            }
        )

        regime_1 = detect_market_regime(df_vnindex=df_vnindex, breadth_ratio=0.60)
        rec_1 = generate_recommendation(
            symbol="FPT",
            company_name="FPT Corp",
            sector="Tech",
            exchange="HOSE",
            df_stock=df_stock,
            market_regime_info=regime_1,
            df_vnindex=df_vnindex,
        )

        # Run monitoring
        payload = {
            "schema_version": "2.0",
            "signal_model_version": SIGNAL_MODEL_VERSION,
            "generated_at": "2026-09-17T06:00:00+00:00",
            "data_as_of": "2026-09-17",
            "source_date": "2026-09-17",
            "data_source": "REAL_DATA",
            "universe_info": {"universe_type": "TEST", "universe_size": 1},
            "market": regime_1,
            "summary": {
                "total_scanned": 1,
                "buy_count": 1 if rec_1["action"] == "BUY" else 0,
                "watch_count": 1 if rec_1["action"] == "WATCH" else 0,
                "hold_count": 1 if rec_1["action"] == "HOLD" else 0,
                "sell_count": 1 if rec_1["action"] == "SELL" else 0,
                "avoid_count": 1 if rec_1["action"] == "AVOID" else 0,
            },
            "recommendations": [rec_1],
        }

        _mon_res = evaluate_production_monitoring(
            recommendations_payload=payload, reference_date="2026-09-17"
        )

        # Re-compute outputs to verify immutability and identity
        regime_2 = detect_market_regime(df_vnindex=df_vnindex, breadth_ratio=0.60)
        rec_2 = generate_recommendation(
            symbol="FPT",
            company_name="FPT Corp",
            sector="Tech",
            exchange="HOSE",
            df_stock=df_stock,
            market_regime_info=regime_2,
            df_vnindex=df_vnindex,
        )

        self.assertEqual(regime_1, regime_2)
        self.assertEqual(rec_1, rec_2)


if __name__ == "__main__":
    unittest.main()
