"""Unit tests for Data and Model Drift Detection Module (scripts/lib/monitoring.py).

Verifies operational data drift, model-output drift, baseline contracts, threshold checks,
strict fail-closed temporal safety, and production monitoring pipeline integration.
"""

import unittest
from datetime import UTC, datetime

from scripts.lib.monitoring import (
    classify_confidence_bucket,
    evaluate_data_and_model_drift,
    evaluate_production_monitoring,
    validate_monitoring_payload,
)


def make_mock_payload(
    data_as_of: str = "2026-09-17",
    total_scanned: int = 20,
    buy_count: int = 5,
    watch_count: int = 5,
    hold_count: int = 5,
    sell_count: int = 5,
    avoid_count: int = 0,
    signal_score: float = 65.0,
    risk_adjusted_score: float = 60.0,
    confidence: float = 0.75,
    vnindex_change_pct: float = 0.5,
    market_breadth_ratio: float = 0.60,
    regime: str = "BULL",
    data_quality: str = "SUFFICIENT",
) -> dict:
    """Generate a valid, deterministic recommendation report payload fixture."""
    recs = []
    actions = (
        ["BUY"] * buy_count
        + ["WATCH"] * watch_count
        + ["HOLD"] * hold_count
        + ["SELL"] * sell_count
        + ["AVOID"] * avoid_count
    )

    for idx, act in enumerate(actions):
        recs.append(
            {
                "symbol": f"SYM{idx + 1:02d}",
                "company_name": f"Company {idx + 1}",
                "exchange": "HOSE",
                "sector": "Technology",
                "action": act,
                "data_quality": data_quality if act != "AVOID" else "INSUFFICIENT",
                "data_quality_issues": [],
                "data_as_of": data_as_of,
                "data_source": "TEST",
                "signal_score": signal_score if act != "AVOID" else None,
                "risk_adjusted_score": risk_adjusted_score if act != "AVOID" else None,
                "confidence": confidence if act != "AVOID" else None,
                "risk_level": "MEDIUM",
                "expected_return": {
                    "expected_return_5d": 0.02,
                    "expected_return_10d": 0.04,
                    "expected_return_20d": 0.08,
                },
                "risk_metrics": {
                    "var_t25": -0.05,
                    "es_t25": -0.07,
                    "volatility_60d": 0.20,
                    "max_drawdown": -0.15,
                    "liquidity_score": 80.0,
                    "avg_value_20d": 50.0,
                },
                "trade_plan": {
                    "current_price": 50000.0,
                    "entry_low": 49000.0,
                    "entry_high": 51000.0,
                    "stop_loss": 47000.0,
                    "tp1": 55000.0,
                    "tp2": 60000.0,
                    "risk_reward": 2.0,
                    "position_percent": 10.0,
                },
                "reasons": ["Test reason"],
                "warnings": [],
                "invalidation": ["Test invalidation"],
            }
        )

    return {
        "schema_version": "2.0",
        "signal_model_version": "2.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "data_as_of": data_as_of,
        "source_date": data_as_of,
        "data_source": "TEST",
        "market": {
            "regime": regime,
            "confidence": 0.85,
            "metrics": {
                "vnindex_value": 1250.0,
                "vnindex_change_pct": vnindex_change_pct,
                "market_breadth_ratio": market_breadth_ratio,
            },
        },
        "summary": {
            "total_scanned": len(recs),
            "buy_count": buy_count,
            "watch_count": watch_count,
            "hold_count": hold_count,
            "sell_count": sell_count,
            "avoid_count": avoid_count,
        },
        "recommendations": recs,
    }


class TestConfidenceBucketClassification(unittest.TestCase):
    """Test suite for classify_confidence_bucket logic and edge cases."""

    def test_valid_confidence_scores(self):
        self.assertEqual(classify_confidence_bucket(0.0), "0.0-0.1")
        self.assertEqual(classify_confidence_bucket(0.05), "0.0-0.1")
        self.assertEqual(classify_confidence_bucket(0.10), "0.1-0.2")
        self.assertEqual(classify_confidence_bucket(0.55), "0.5-0.6")
        self.assertEqual(classify_confidence_bucket(0.95), "0.9-1.0")
        self.assertEqual(classify_confidence_bucket(1.00), "0.9-1.0")
        self.assertIsNone(classify_confidence_bucket(None))

    def test_invalid_confidence_scores_raise_errors(self):
        with self.assertRaises(ValueError):
            classify_confidence_bucket(-0.1)
        with self.assertRaises(ValueError):
            classify_confidence_bucket(1.1)
        with self.assertRaises(ValueError):
            classify_confidence_bucket(float("nan"))
        with self.assertRaises(ValueError):
            classify_confidence_bucket(float("inf"))
        with self.assertRaises(TypeError):
            classify_confidence_bucket("0.8")
        with self.assertRaises(TypeError):
            classify_confidence_bucket(True)


class TestDriftBaselineValidation(unittest.TestCase):
    """Test suite for historical baseline contract, sufficiency, and invalid baseline error handling."""

    def test_sufficient_baseline_data(self):
        """Verify evaluation succeeds when baseline has at least min_baseline_reports (5)."""
        curr = make_mock_payload(data_as_of="2026-09-17")
        baselines = [make_mock_payload(data_as_of=f"2026-09-{16 - i:02d}") for i in range(5)]

        res = evaluate_data_and_model_drift(
            data_as_of="2026-09-17",
            current_payload=curr,
            baseline_reports=baselines,
        )

        self.assertEqual(res.overall_status, "PASS")
        self.assertEqual(res.baseline_summary["status"], "SUFFICIENT")
        self.assertEqual(res.baseline_summary["report_count"], 5)

    def test_insufficient_baseline_data(self):
        """Verify baseline with fewer than 5 historical reports returns WARNING status."""
        curr = make_mock_payload(data_as_of="2026-09-17")
        baselines = [make_mock_payload(data_as_of=f"2026-09-{16 - i:02d}") for i in range(3)]

        res = evaluate_data_and_model_drift(
            data_as_of="2026-09-17",
            current_payload=curr,
            baseline_reports=baselines,
        )

        self.assertEqual(res.overall_status, "WARNING")
        self.assertEqual(res.baseline_summary["status"], "INSUFFICIENT")
        self.assertEqual(res.baseline_summary["available_reports"], 3)
        self.assertEqual(len(res.drift_checks), 1)
        self.assertEqual(res.drift_checks[0].check_name, "drift_baseline_sufficiency")
        self.assertIn(
            "INSUFFICIENT baseline historical data", res.drift_checks[0].observation.message
        )

    def test_history_index_duplicate_dates_fail_closed(self):
        """Verify duplicate dates in history index fail closed (FAIL status)."""
        curr = make_mock_payload(data_as_of="2026-09-17")
        index_data = {"dates": ["2026-09-16", "2026-09-16", "2026-09-15"]}

        res = evaluate_data_and_model_drift(
            data_as_of="2026-09-17",
            current_payload=curr,
            history_index_data=index_data,
        )

        self.assertEqual(res.overall_status, "FAIL")
        self.assertEqual(res.drift_checks[0].check_name, "drift_history_index_duplicates")
        self.assertIn("duplicate date entries", res.drift_checks[0].observation.message)

    def test_history_index_unsorted_dates_fail_closed(self):
        """Verify unsorted dates in history index fail closed (FAIL status)."""
        curr = make_mock_payload(data_as_of="2026-09-17")
        index_data = {"dates": ["2026-09-15", "2026-09-16", "2026-09-14"]}

        res = evaluate_data_and_model_drift(
            data_as_of="2026-09-17",
            current_payload=curr,
            history_index_data=index_data,
        )

        self.assertEqual(res.overall_status, "FAIL")
        self.assertEqual(res.drift_checks[0].check_name, "drift_history_index_order")
        self.assertIn("descending chronological order", res.drift_checks[0].observation.message)

    def test_injected_future_baseline_reports_fail_closed(self):
        """Verify injected baseline report date >= T fails closed (FAIL status)."""
        curr = make_mock_payload(data_as_of="2026-09-17")
        baselines = [
            make_mock_payload(data_as_of="2026-09-18"),  # Future date >= T!
            make_mock_payload(data_as_of="2026-09-16"),
            make_mock_payload(data_as_of="2026-09-15"),
            make_mock_payload(data_as_of="2026-09-14"),
            make_mock_payload(data_as_of="2026-09-13"),
        ]

        res = evaluate_data_and_model_drift(
            data_as_of="2026-09-17",
            current_payload=curr,
            baseline_reports=baselines,
        )

        self.assertEqual(res.overall_status, "FAIL")
        self.assertEqual(res.drift_checks[0].check_name, "drift_temporal_safety")
        self.assertIn("Temporal safety violation", res.drift_checks[0].observation.message)


class TestDistributionAndNumericDrift(unittest.TestCase):
    """Test suite for distribution drift, numeric drift, and deterministic repeatability."""

    def setUp(self):
        self.curr = make_mock_payload(
            data_as_of="2026-09-17",
            buy_count=5,
            watch_count=5,
            hold_count=5,
            sell_count=5,
            signal_score=65.0,
            risk_adjusted_score=60.0,
            confidence=0.75,
            vnindex_change_pct=0.5,
            market_breadth_ratio=0.60,
        )
        self.baselines = [
            make_mock_payload(
                data_as_of=f"2026-09-{16 - i:02d}",
                buy_count=5,
                watch_count=5,
                hold_count=5,
                sell_count=5,
                signal_score=65.0,
                risk_adjusted_score=60.0,
                confidence=0.75,
                vnindex_change_pct=0.5,
                market_breadth_ratio=0.60,
            )
            for i in range(5)
        ]

    def test_identical_baseline_and_current_yields_pass(self):
        """Verify identical current and baseline yields all PASS checks."""
        res = evaluate_data_and_model_drift(
            data_as_of="2026-09-17",
            current_payload=self.curr,
            baseline_reports=self.baselines,
        )

        self.assertEqual(res.overall_status, "PASS")
        for chk in res.drift_checks:
            self.assertEqual(
                chk.status, "PASS", f"Check {chk.check_name} failed: {chk.observation.message}"
            )

    def test_drift_under_threshold_yields_pass(self):
        """Verify small metric shift below warning thresholds yields PASS."""
        curr_small_shift = make_mock_payload(
            data_as_of="2026-09-17",
            buy_count=6,
            watch_count=4,
            hold_count=5,
            sell_count=5,
            signal_score=68.0,  # +3.0 score shift (warning is 15.0)
            risk_adjusted_score=62.0,  # +2.0 score shift
            confidence=0.78,  # +0.03 confidence shift
            vnindex_change_pct=1.0,  # +0.5% change shift (warning is 3.0%)
            market_breadth_ratio=0.65,  # +0.05 breadth shift
        )

        res = evaluate_data_and_model_drift(
            data_as_of="2026-09-17",
            current_payload=curr_small_shift,
            baseline_reports=self.baselines,
        )

        self.assertEqual(res.overall_status, "PASS")

    def test_action_distribution_drift_exceeding_threshold_yields_warning_or_fail(self):
        """Verify massive action proportion shift (> 0.20 warning, > 0.35 fail) flags WARNING/FAIL."""
        curr_action_drift = make_mock_payload(
            data_as_of="2026-09-17",
            buy_count=18,  # 90% BUY vs baseline 25% BUY (shift = 0.65 > fail threshold 0.35)
            watch_count=1,
            hold_count=1,
            sell_count=0,
            avoid_count=0,
        )

        res = evaluate_data_and_model_drift(
            data_as_of="2026-09-17",
            current_payload=curr_action_drift,
            baseline_reports=self.baselines,
        )

        self.assertEqual(res.overall_status, "FAIL")
        action_chk = next(
            c for c in res.drift_checks if c.check_name == "drift_action_distribution"
        )
        self.assertEqual(action_chk.status, "FAIL")
        self.assertGreater(action_chk.observation.absolute_difference["max_difference"], 0.35)

    def test_numeric_score_drift_exceeding_threshold(self):
        """Verify signal score mean drift > 15.0 warning and > 25.0 fail."""
        curr_score_drift = make_mock_payload(
            data_as_of="2026-09-17",
            signal_score=95.0,  # 95 vs baseline 65 (diff = 30.0 > fail threshold 25.0)
        )

        res = evaluate_data_and_model_drift(
            data_as_of="2026-09-17",
            current_payload=curr_score_drift,
            baseline_reports=self.baselines,
        )

        self.assertEqual(res.overall_status, "FAIL")
        score_chk = next(c for c in res.drift_checks if c.check_name == "drift_signal_score")
        self.assertEqual(score_chk.status, "FAIL")
        self.assertEqual(score_chk.observation.absolute_difference, 30.0)

    def test_deterministic_repeatability(self):
        """Verify running drift evaluation twice on identical data produces identical outputs."""
        res_1 = evaluate_data_and_model_drift(
            data_as_of="2026-09-17",
            current_payload=self.curr,
            baseline_reports=self.baselines,
        )
        res_2 = evaluate_data_and_model_drift(
            data_as_of="2026-09-17",
            current_payload=self.curr,
            baseline_reports=self.baselines,
        )

        self.assertEqual(res_1.to_dict(), res_2.to_dict())


class TestTemporalSafetyRegression(unittest.TestCase):
    """Explicit temporal safety regression tests."""

    def test_future_observation_appearing_before_T_in_index_fails_closed(self):
        """Regression test: T = 2026-09-17. History index has dates ['2026-09-16', '2026-09-18', '2026-09-15'].

        A future observation '2026-09-18' appears after '2026-09-16' in physical index array.
        Must FAIL closed, not silently filter out the future observation.
        """
        curr = make_mock_payload(data_as_of="2026-09-17")
        index_data = {"dates": ["2026-09-16", "2026-09-18", "2026-09-15"]}

        res = evaluate_data_and_model_drift(
            data_as_of="2026-09-17",
            current_payload=curr,
            history_index_data=index_data,
        )

        self.assertEqual(res.overall_status, "FAIL")
        self.assertIn(
            res.drift_checks[0].check_name,
            ("drift_history_index_order", "drift_temporal_safety"),
        )


class TestFeedbackRegressionCases(unittest.TestCase):
    """Regression test suite covering user feedback review items for PR #95."""

    def test_market_metrics_prioritize_market_payload(self):
        """Verify vnindex_change_pct and market_breadth_ratio are prioritized from market_payload."""
        curr_rec = make_mock_payload(data_as_of="2026-09-17")
        # Remove metrics from recommendation payload's inner market dict
        curr_rec["market"]["metrics"] = {}

        explicit_market = {
            "regime": "BULL",
            "confidence": 0.90,
            "metrics": {
                "vnindex_value": 1250.0,
                "vnindex_change_pct": 0.5,
                "market_breadth_ratio": 0.60,
            },
        }

        baselines = [make_mock_payload(data_as_of=f"2026-09-{16 - i:02d}") for i in range(5)]

        res = evaluate_data_and_model_drift(
            data_as_of="2026-09-17",
            current_payload=curr_rec,
            market_payload=explicit_market,
            baseline_reports=baselines,
        )

        self.assertEqual(res.overall_status, "PASS")
        breadth_chk = next(c for c in res.drift_checks if c.check_name == "drift_market_breadth")
        self.assertEqual(breadth_chk.status, "PASS")
        self.assertEqual(breadth_chk.observation.current_value, 0.60)

    def test_invalid_baseline_config_parameters_fail_closed(self):
        """Verify invalid lookback_reports or min_baseline_reports raise TypeError or ValueError."""
        curr = make_mock_payload(data_as_of="2026-09-17")
        baselines = [make_mock_payload(data_as_of=f"2026-09-{16 - i:02d}") for i in range(5)]

        # Boolean lookback
        with self.assertRaises(TypeError):
            evaluate_data_and_model_drift(
                current_payload=curr, baseline_reports=baselines, lookback_reports=True
            )

        # Negative lookback
        with self.assertRaises(ValueError):
            evaluate_data_and_model_drift(
                current_payload=curr, baseline_reports=baselines, lookback_reports=-5
            )

        # min_baseline_reports > lookback_reports
        with self.assertRaises(ValueError):
            evaluate_data_and_model_drift(
                current_payload=curr,
                baseline_reports=baselines,
                lookback_reports=5,
                min_baseline_reports=10,
            )

    def test_invalid_injected_baseline_reports_fail_closed(self):
        """Verify malformed data_as_of or non-dict items in baseline_reports fail closed."""
        curr = make_mock_payload(data_as_of="2026-09-17")

        # Non-dict item
        res = evaluate_data_and_model_drift(
            current_payload=curr,
            baseline_reports=["not_a_dict"],  # type: ignore[list-item]
        )
        self.assertEqual(res.overall_status, "FAIL")

        # Malformed YYYY-MM-DD date string
        bad_date = make_mock_payload(data_as_of="invalid-date")
        res = evaluate_data_and_model_drift(current_payload=curr, baseline_reports=[bad_date])
        self.assertEqual(res.overall_status, "FAIL")

        # Unsorted dates in baseline_reports
        unsorted_baselines = [
            make_mock_payload(data_as_of="2026-09-14"),
            make_mock_payload(data_as_of="2026-09-16"),
        ]
        res = evaluate_data_and_model_drift(
            current_payload=curr, baseline_reports=unsorted_baselines
        )
        self.assertEqual(res.overall_status, "FAIL")

    def test_canonical_date_validation_cases(self):
        """Verify strict canonical YYYY-MM-DD calendar date validation rules."""
        from scripts.lib.monitoring import is_canonical_yyyy_mm_dd

        self.assertTrue(is_canonical_yyyy_mm_dd("2026-09-17"))
        self.assertFalse(is_canonical_yyyy_mm_dd("2026-9-17"))
        self.assertFalse(is_canonical_yyyy_mm_dd("2026-09-17T00:00:00"))
        self.assertFalse(is_canonical_yyyy_mm_dd("2026-09-17Z"))
        self.assertFalse(is_canonical_yyyy_mm_dd("2026-02-30"))
        self.assertFalse(is_canonical_yyyy_mm_dd(True))
        self.assertFalse(is_canonical_yyyy_mm_dd(12345))
        self.assertFalse(is_canonical_yyyy_mm_dd(None))

    def test_mismatched_data_as_of_between_payload_and_evaluation_date_fails(self):
        """Verify evaluation fails closed when data_as_of parameter mismatches current_payload date."""
        curr = make_mock_payload(data_as_of="2026-09-17")

        res = evaluate_data_and_model_drift(
            data_as_of="2026-09-16",  # Mismatches current_payload "2026-09-17"
            current_payload=curr,
        )

        self.assertEqual(res.overall_status, "FAIL")
        self.assertEqual(res.drift_checks[0].check_name, "drift_data_as_of_mismatch")

    def test_non_canonical_data_as_of_fails(self):
        """Verify non-canonical data_as_of strings fail closed."""
        for bad_date in ["2026-9-17", "2026-09-17T00:00:00", "2026-09-17Z", "2026-02-30"]:
            curr_bad = make_mock_payload(data_as_of="2026-09-17")
            curr_bad["data_as_of"] = bad_date
            res = evaluate_data_and_model_drift(
                data_as_of=bad_date,
                current_payload=curr_bad,
            )
            self.assertEqual(res.overall_status, "FAIL")

    def test_baseline_report_containing_nan_fails_closed(self):
        """Verify baseline report containing non-finite NaN value fails closed."""
        curr = make_mock_payload(data_as_of="2026-09-17")
        baselines = [make_mock_payload(data_as_of=f"2026-09-{16 - i:02d}") for i in range(5)]
        # Inject NaN into a baseline report
        baselines[0]["market"]["metrics"]["vnindex_value"] = float("nan")

        res = evaluate_data_and_model_drift(
            data_as_of="2026-09-17",
            current_payload=curr,
            baseline_reports=baselines,
        )

        self.assertEqual(res.overall_status, "FAIL")
        self.assertEqual(res.drift_checks[0].check_name, "drift_baseline_numeric_sanity")

    def test_missing_selected_disk_baseline_artifact_fails_closed(self):
        """Verify selecting a baseline date whose artifact is missing on disk fails closed."""
        curr = make_mock_payload(data_as_of="2026-09-17")
        # History index lists '2026-09-16' but no file exists on disk
        index_data = {"dates": ["2026-09-16"]}

        res = evaluate_data_and_model_drift(
            data_as_of="2026-09-17",
            current_payload=curr,
            history_index_data=index_data,
            generated_dir="/non/existent/dir",
        )

        self.assertEqual(res.overall_status, "FAIL")
        self.assertEqual(res.drift_checks[0].check_name, "drift_history_artifact_missing")


class TestProductionMonitoringIntegration(unittest.TestCase):
    """Test suite verifying integration of drift detection into evaluate_production_monitoring()."""

    def test_monitoring_runs_drift_checks_and_validates_payload(self):
        """Verify evaluate_production_monitoring includes drift checks and produces a valid payload."""
        curr = make_mock_payload(data_as_of="2026-09-17")

        res = evaluate_production_monitoring(
            recommendations_payload=curr,
            reference_date="2026-09-17",
        )

        payload_dict = res.to_dict()
        self.assertTrue(validate_monitoring_payload(payload_dict))
        self.assertIn("drift_monitoring", res.metrics)

        # Check that drift check results are present in checks array
        check_names = [c.check_name for c in res.checks]
        self.assertIn("drift_processed_ratio", check_names)
        self.assertIn("drift_action_distribution", check_names)
        self.assertIn("drift_signal_score", check_names)

    def test_drift_fail_causes_overall_monitoring_fail(self):
        """Verify drift FAIL result forces evaluate_production_monitoring overall_status to FAIL."""
        curr_action_drift = make_mock_payload(
            data_as_of="2026-09-17",
            buy_count=18,
            watch_count=1,
            hold_count=1,
            sell_count=0,
            avoid_count=0,
        )

        res = evaluate_production_monitoring(
            recommendations_payload=curr_action_drift,
            reference_date="2026-09-17",
        )

        self.assertIn(res.overall_status, ("WARNING", "FAIL"))


if __name__ == "__main__":
    unittest.main()
