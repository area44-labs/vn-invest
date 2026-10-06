"""Deterministic offline unit tests for the extracted Performance Tracking Subsystem.

Tests PerformanceTracker, StageMetricsCollector, provider_metrics, budget evaluation,
performance regression detection, CI enforcement toggles, fail-safe isolation,
and quantitative output invariance.
"""

import os
import unittest
from unittest.mock import patch

import pandas as pd

from scripts.lib.recommendation import generate_recommendation
from scripts.performance.budget import evaluate_provider_budget
from scripts.performance.provider_metrics import (
    aggregate_provider_performance,
    detect_duplicate_operations,
)
from scripts.performance.regression import evaluate_performance_regression
from scripts.performance.stage_metrics import StageMetricsCollector
from scripts.performance.tracker import PerformanceTracker, create_default_performance_payload
from scripts.quant.regime import detect_market_regime


class TestStageMetricsCollector(unittest.TestCase):
    """Unit tests for StageMetricsCollector."""

    def setUp(self):
        self.collector = StageMetricsCollector()

    def test_record_stage(self):
        rec = self.collector.record_stage("benchmark_fetch", 1.23456, status="SUCCESS")
        self.assertEqual(rec["stage"], "benchmark_fetch")
        self.assertEqual(rec["elapsed_seconds"], 1.2346)
        self.assertEqual(rec["status"], "SUCCESS")

        stages = self.collector.get_stages()
        self.assertEqual(len(stages), 1)
        self.assertEqual(stages[0]["stage"], "benchmark_fetch")

    def test_measure_stage_success(self):
        with self.collector.measure_stage("stock_fetch"):
            pass

        stages = self.collector.get_stages()
        self.assertEqual(len(stages), 1)
        self.assertEqual(stages[0]["stage"], "stock_fetch")
        self.assertEqual(stages[0]["status"], "SUCCESS")
        self.assertGreaterEqual(stages[0]["elapsed_seconds"], 0.0)

    def test_measure_stage_exception_records_failed(self):
        with self.assertRaises(ValueError), self.collector.measure_stage("failing_stage"):
            raise ValueError("Stage execution error")

        stages = self.collector.get_stages()
        self.assertEqual(len(stages), 1)
        self.assertEqual(stages[0]["stage"], "failing_stage")
        self.assertEqual(stages[0]["status"], "FAILED")

    def test_get_slow_stages(self):
        self.collector.record_stage("fast_stage", 0.2)
        self.collector.record_stage("slow_stage", 2.5)

        slow = self.collector.get_slow_stages(threshold_seconds=1.0)
        self.assertEqual(len(slow), 1)
        self.assertEqual(slow[0]["stage"], "slow_stage")

    def test_reset(self):
        self.collector.record_stage("stage_a", 0.5)
        self.assertEqual(len(self.collector.get_stages()), 1)
        self.collector.reset()
        self.assertEqual(len(self.collector.get_stages()), 0)


class TestProviderMetrics(unittest.TestCase):
    """Unit tests for provider_metrics functions."""

    def test_aggregate_provider_performance_empty(self):
        res = aggregate_provider_performance([])
        self.assertEqual(res["total_calls"], 0)
        self.assertEqual(res["successful_calls"], 0)
        self.assertEqual(res["failed_calls"], 0)
        self.assertEqual(res["total_elapsed_seconds"], 0.0)
        self.assertEqual(res["calls_by_source"], {})

    def test_aggregate_provider_performance_mixed_calls(self):
        history = [
            {
                "provider": "vnstock",
                "source": "kbs",
                "operation": "history",
                "symbol": "FPT",
                "elapsed_seconds": 0.5,
                "success": True,
                "retry_count": 0,
            },
            {
                "provider": "vnstock",
                "source": "msn",
                "operation": "history",
                "symbol": "VNM",
                "elapsed_seconds": 0.8,
                "success": False,
                "retry_count": 1,
            },
        ]
        res = aggregate_provider_performance(history)
        self.assertEqual(res["total_calls"], 2)
        self.assertEqual(res["successful_calls"], 1)
        self.assertEqual(res["failed_calls"], 1)
        self.assertEqual(res["retry_count"], 1)
        self.assertEqual(res["total_elapsed_seconds"], 1.3)
        self.assertEqual(res["average_call_seconds"], 0.65)
        self.assertEqual(res["calls_by_source"], {"kbs": 1, "msn": 1})

    def test_detect_duplicate_operations(self):
        history = [
            {"symbol": "FPT", "success": True, "retry_count": 0},
            {"symbol": "FPT", "success": True, "retry_count": 0},
            {"symbol": "VNM", "success": True, "retry_count": 0},
        ]
        symbol_requests = {"FPT": 2, "VNM": 1, "HPG": 1}

        dups = detect_duplicate_operations(history, symbol_requests)
        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0]["symbol"], "FPT")
        self.assertEqual(dups[0]["provider_call_count"], 2)
        self.assertEqual(dups[0]["request_count"], 2)


class TestPerformanceBudget(unittest.TestCase):
    """Unit tests for performance budget evaluation and CI enforcement."""

    def test_evaluate_provider_budget_pass(self):
        payload = {
            "provider": {"total_calls": 10, "total_elapsed_seconds": 5.0},
            "duplicate_operations": [],
        }
        res = evaluate_provider_budget(payload)
        self.assertEqual(res["overall_status"], "PASS")
        self.assertEqual(len(res["violations"]), 0)

    def test_evaluate_provider_budget_violations_degraded_by_default(self):
        payload = {
            "provider": {"total_calls": 200, "total_elapsed_seconds": 100.0},
            "duplicate_operations": [{"symbol": "FPT"}] * 10,
        }
        res = evaluate_provider_budget(payload, enforce_ci_budget=False)
        self.assertEqual(res["overall_status"], "DEGRADED")
        self.assertEqual(len(res["violations"]), 3)

    def test_evaluate_provider_budget_violations_failed_when_ci_enforced(self):
        payload = {
            "provider": {"total_calls": 200, "total_elapsed_seconds": 100.0},
            "duplicate_operations": [],
        }
        res = evaluate_provider_budget(payload, enforce_ci_budget=True)
        self.assertEqual(res["overall_status"], "FAILED")
        self.assertIn("Total provider calls (200) exceeded budget (120)", res["violations"])

    def test_evaluate_provider_budget_env_var_ci_enforcement(self):
        payload = {
            "provider": {"total_calls": 150, "total_elapsed_seconds": 10.0},
            "duplicate_operations": [],
        }
        with patch.dict(os.environ, {"ENABLE_PERFORMANCE_BUDGETS": "true"}):
            res = evaluate_provider_budget(payload)
            self.assertEqual(res["overall_status"], "FAILED")

    def test_evaluate_provider_budget_custom_threshold_override(self):
        payload = {
            "provider": {"total_calls": 10, "total_elapsed_seconds": 5.0},
            "duplicate_operations": [],
        }
        override = {"max_total_calls": 5}
        res = evaluate_provider_budget(payload, budget_config_override=override)
        self.assertEqual(res["overall_status"], "DEGRADED")
        self.assertEqual(res["max_calls_budget"], 5)


class TestPerformanceRegression(unittest.TestCase):
    """Unit tests for performance regression detection."""

    def test_evaluate_performance_regression_pass(self):
        payload = {
            "stages": [
                {"stage": "benchmark_fetch", "elapsed_seconds": 0.5, "status": "SUCCESS"},
                {"stage": "stock_fetch", "elapsed_seconds": 2.0, "status": "SUCCESS"},
            ]
        }
        res = evaluate_performance_regression(payload)
        self.assertEqual(res["overall_status"], "PASS")

    def test_evaluate_performance_regression_degraded(self):
        payload = {
            "stages": [
                {"stage": "stock_fetch", "elapsed_seconds": 8.5, "status": "SUCCESS"},
            ]
        }
        res = evaluate_performance_regression(payload)
        self.assertEqual(res["overall_status"], "DEGRADED")

    def test_evaluate_performance_regression_failed(self):
        payload = {
            "stages": [
                {"stage": "stock_fetch", "elapsed_seconds": 20.0, "status": "SUCCESS"},
            ]
        }
        res = evaluate_performance_regression(payload)
        self.assertEqual(res["overall_status"], "FAILED")

    def test_evaluate_performance_regression_failed_status(self):
        payload = {
            "stages": [
                {"stage": "market_calculation", "elapsed_seconds": 0.1, "status": "FAILED"},
            ]
        }
        res = evaluate_performance_regression(payload)
        self.assertEqual(res["overall_status"], "FAILED")


class TestPerformanceTrackerSubsystem(unittest.TestCase):
    """Unit tests for PerformanceTracker and integration invariants."""

    def setUp(self):
        self.tracker = PerformanceTracker()

    def test_tracker_record_request_and_stages(self):
        self.tracker.record_request("fpt")
        self.tracker.record_request("FPT")
        self.assertEqual(self.tracker.symbol_requests["FPT"], 2)

        with self.tracker.measure_stage("benchmark_fetch"):
            pass

        self.tracker.record_stage("stock_fetch", 1.5)

        stages = self.tracker.stages
        self.assertEqual(len(stages), 2)
        self.assertEqual(stages[0]["stage"], "benchmark_fetch")
        self.assertEqual(stages[1]["stage"], "stock_fetch")

    def test_get_performance_payload_valid_structure(self):
        self.tracker.record_request("VNM")
        self.tracker.record_stage("market_calculation", 0.1)

        payload = self.tracker.get_performance_payload(pipeline_elapsed=1.0)
        self.assertIn("stages", payload)
        self.assertIn("provider", payload)
        self.assertIn("duplicate_operations", payload)
        self.assertIn("regression", payload)
        self.assertIn("budget", payload)
        self.assertEqual(payload["stages"][0]["stage"], "pipeline")

    def test_fail_safe_isolation_returns_valid_payload_on_non_critical_error(self):
        tracker = PerformanceTracker()
        tracker.record_stage("market_calculation", 0.1)

        with patch(
            "scripts.performance.tracker.aggregate_provider_performance",
            side_effect=RuntimeError("Unexpected provider aggregation error"),
        ):
            payload = tracker.get_performance_payload(pipeline_elapsed=0.5)
            self.assertIn("stages", payload)
            self.assertIn("provider", payload)
            self.assertEqual(payload["stages"][0]["stage"], "pipeline")

    def test_create_default_performance_payload(self):
        default_payload = create_default_performance_payload()
        self.assertEqual(default_payload["stages"][0]["stage"], "pipeline")
        self.assertEqual(default_payload["provider"]["total_calls"], 0)


class TestQuantitativeOutputInvariance(unittest.TestCase):
    """Verify that performance tracking instrumentation does not alter quantitative engine calculations."""

    def test_regime_and_signal_outputs_are_identical_with_and_without_tracker(self):
        # Construct synthetic clean OHLCV data
        dates = pd.date_range("2025-01-01", periods=30, freq="D")
        df_index = pd.DataFrame(
            {
                "time": dates,
                "open": [1200.0 + i for i in range(30)],
                "high": [1210.0 + i for i in range(30)],
                "low": [1190.0 + i for i in range(30)],
                "close": [1205.0 + i for i in range(30)],
                "volume": [1000000 + i * 1000 for i in range(30)],
            }
        )

        # Baseline calculation without any tracker
        res_baseline = detect_market_regime(df_index)

        # Calculation with active PerformanceTracker measuring stages
        tracker = PerformanceTracker()
        with tracker.measure_stage("regime_calculation"):
            res_instrumented = detect_market_regime(df_index)

        # Outputs must be 100% identical
        self.assertEqual(res_baseline, res_instrumented)

        # Verify Signal Recommendation output invariance
        df_stock = pd.DataFrame(
            {
                "time": dates,
                "open": [50.0 + i * 0.1 for i in range(30)],
                "high": [51.0 + i * 0.1 for i in range(30)],
                "low": [49.5 + i * 0.1 for i in range(30)],
                "close": [50.5 + i * 0.1 for i in range(30)],
                "volume": [500000 for _ in range(30)],
            }
        )

        rec_baseline = generate_recommendation(
            "FPT",
            "FPT Corp",
            "Technology",
            "HOSE",
            df_stock,
            res_baseline.market_regime,
            df_vnindex=df_index,
        )

        with tracker.measure_stage("recommendation_calculation"):
            rec_instrumented = generate_recommendation(
                "FPT",
                "FPT Corp",
                "Technology",
                "HOSE",
                df_stock,
                res_baseline.market_regime,
                df_vnindex=df_index,
            )

        self.assertEqual(rec_baseline.get("action"), rec_instrumented.get("action"))
        self.assertEqual(rec_baseline.get("signal_score"), rec_instrumented.get("signal_score"))
        self.assertEqual(rec_baseline.get("confidence"), rec_instrumented.get("confidence"))


if __name__ == "__main__":
    unittest.main()
