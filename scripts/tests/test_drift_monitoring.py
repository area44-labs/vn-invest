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

    def test_missing_history_index_file_fails_closed(self):
        """Verify missing history/index.json fails closed with FAIL status."""
        import tempfile

        curr = make_mock_payload(data_as_of="2026-09-17")
        with tempfile.TemporaryDirectory() as empty_dir:
            res = evaluate_data_and_model_drift(
                data_as_of="2026-09-17",
                current_payload=curr,
                generated_dir=empty_dir,
                history_index_data=None,
            )

            self.assertEqual(res.overall_status, "FAIL")
            self.assertEqual(res.baseline_summary["status"], "FAIL")
            self.assertEqual(res.drift_checks[0].check_name, "drift_history_index")

    def test_malformed_history_index_file_fails_closed(self):
        """Verify malformed JSON history/index.json fails closed with FAIL status."""
        import os
        import tempfile

        curr = make_mock_payload(data_as_of="2026-09-17")
        with tempfile.TemporaryDirectory() as tmpdir:
            history_dir = os.path.join(tmpdir, "history")
            os.makedirs(history_dir, exist_ok=True)
            with open(os.path.join(history_dir, "index.json"), "w", encoding="utf-8") as f:
                f.write("{invalid json content")

            res = evaluate_data_and_model_drift(
                data_as_of="2026-09-17",
                current_payload=curr,
                generated_dir=tmpdir,
            )

            self.assertEqual(res.overall_status, "FAIL")
            self.assertEqual(res.baseline_summary["status"], "FAIL")
            self.assertEqual(res.drift_checks[0].check_name, "drift_history_index")

    def test_injected_history_index_data_none_with_missing_disk_index_fails_closed(self):
        """Verify explicit history_index_data=None when no disk index exists fails closed with FAIL status."""
        import tempfile

        curr = make_mock_payload(data_as_of="2026-09-17")
        with tempfile.TemporaryDirectory() as empty_dir:
            res = evaluate_data_and_model_drift(
                data_as_of="2026-09-17",
                current_payload=curr,
                generated_dir=empty_dir,
                history_index_data=None,
            )

            self.assertEqual(res.overall_status, "FAIL")
            self.assertEqual(res.baseline_summary["status"], "FAIL")
            self.assertEqual(res.drift_checks[0].check_name, "drift_history_index")

    def test_valid_history_index_with_fewer_than_min_baseline_reports_yields_warning(self):
        """Verify valid history index with 1 to 4 baseline reports yields WARNING status and INSUFFICIENT baseline."""
        import json
        import os
        import tempfile

        curr = make_mock_payload(data_as_of="2026-09-17")
        with tempfile.TemporaryDirectory() as tmpdir:
            history_dir = os.path.join(tmpdir, "history")
            os.makedirs(history_dir, exist_ok=True)

            dates = ["2026-09-17", "2026-09-16", "2026-09-15", "2026-09-14"]
            with open(os.path.join(history_dir, "index.json"), "w", encoding="utf-8") as f:
                json.dump({"dates": dates}, f)

            for d in dates:
                with open(os.path.join(history_dir, f"{d}.json"), "w", encoding="utf-8") as f:
                    json.dump(make_mock_payload(data_as_of=d), f)

            res = evaluate_data_and_model_drift(
                data_as_of="2026-09-17",
                current_payload=curr,
                generated_dir=tmpdir,
            )

            self.assertEqual(res.overall_status, "WARNING")
            self.assertEqual(res.baseline_summary["status"], "INSUFFICIENT")
            self.assertEqual(res.baseline_summary["available_reports"], 3)
            self.assertEqual(res.drift_checks[0].check_name, "drift_baseline_sufficiency")

    def test_valid_history_index_with_min_baseline_reports_runs_drift_calculation(self):
        """Verify valid history index with >= min_baseline_reports executes normal drift calculation."""
        import json
        import os
        import tempfile

        curr = make_mock_payload(data_as_of="2026-09-17")
        with tempfile.TemporaryDirectory() as tmpdir:
            history_dir = os.path.join(tmpdir, "history")
            os.makedirs(history_dir, exist_ok=True)

            dates = [
                "2026-09-17",
                "2026-09-16",
                "2026-09-15",
                "2026-09-14",
                "2026-09-13",
                "2026-09-12",
            ]
            with open(os.path.join(history_dir, "index.json"), "w", encoding="utf-8") as f:
                json.dump({"dates": dates}, f)

            for d in dates:
                with open(os.path.join(history_dir, f"{d}.json"), "w", encoding="utf-8") as f:
                    json.dump(make_mock_payload(data_as_of=d), f)

            res = evaluate_data_and_model_drift(
                data_as_of="2026-09-17",
                current_payload=curr,
                generated_dir=tmpdir,
            )

            self.assertEqual(res.overall_status, "PASS")
            self.assertEqual(res.baseline_summary["status"], "SUFFICIENT")
            self.assertEqual(res.baseline_summary["report_count"], 5)

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
        self.assertEqual(res.drift_checks[0].check_name, "drift_history_index_order")


class TestFeedbackRegressionCases(unittest.TestCase):
    """Regression test suite covering user feedback review items for PR #95."""

    def test_market_metrics_prioritize_market_payload(self):
        """Verify vnindex_change_pct and market_breadth_ratio are prioritized from market_payload."""
        curr_rec = make_mock_payload(data_as_of="2026-09-17")
        # Remove metrics from recommendation payload's inner market dict
        curr_rec["market"]["metrics"] = {}

        explicit_market = {
            "data_as_of": "2026-09-17",
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

    def test_malformed_recommendation_item_fails_closed(self):
        """Verify recommendation items that are non-dict (string, None, list) fail closed."""
        for bad_item in ["string_item", None, ["list_item"]]:
            curr = make_mock_payload(data_as_of="2026-09-17")
            curr["recommendations"].append(bad_item)  # type: ignore[arg-type]

            res = evaluate_data_and_model_drift(
                data_as_of="2026-09-17",
                current_payload=curr,
            )
            self.assertEqual(res.overall_status, "FAIL")
            self.assertEqual(res.drift_checks[0].check_name, "drift_current_payload_malformed")

    def test_invalid_or_non_finite_model_metrics_fail_closed(self):
        """Verify NaN, Inf, out-of-bounds, or string metrics fail closed (FAIL status)."""
        bad_metric_cases = [
            ("confidence", float("nan")),
            ("confidence", float("inf")),
            ("confidence", -0.1),
            ("confidence", 1.5),
            ("confidence", "0.8"),
            ("confidence", True),
            ("signal_score", float("nan")),
            ("signal_score", float("inf")),
            ("signal_score", "high"),
            ("signal_score", True),
            ("risk_adjusted_score", float("nan")),
            ("risk_adjusted_score", float("inf")),
            ("risk_adjusted_score", "medium"),
            ("risk_adjusted_score", True),
        ]

        for field, bad_val in bad_metric_cases:
            curr = make_mock_payload(data_as_of="2026-09-17")
            curr["recommendations"][0][field] = bad_val

            res = evaluate_data_and_model_drift(
                data_as_of="2026-09-17",
                current_payload=curr,
            )
            self.assertEqual(
                res.overall_status,
                "FAIL",
                f"Failed to fail-closed on {field}={bad_val} (got {res.overall_status})",
            )
            self.assertEqual(res.drift_checks[0].check_name, "drift_current_payload_malformed")

    def test_summary_inconsistencies_fail_closed(self):
        """Verify malformed or inconsistent payload summary fails closed with FAIL status."""
        # Case 1: Negative total_scanned
        curr1 = make_mock_payload(data_as_of="2026-09-17")
        curr1["summary"]["total_scanned"] = -10
        res1 = evaluate_data_and_model_drift(current_payload=curr1)
        self.assertEqual(res1.overall_status, "FAIL")
        self.assertEqual(res1.drift_checks[0].check_name, "drift_current_payload_malformed")

        # Case 2: Negative action count
        curr2 = make_mock_payload(data_as_of="2026-09-17")
        curr2["summary"]["buy_count"] = -1
        res2 = evaluate_data_and_model_drift(current_payload=curr2)
        self.assertEqual(res2.overall_status, "FAIL")

        # Case 3: Action count sum > total_scanned
        curr3 = make_mock_payload(data_as_of="2026-09-17")
        curr3["summary"]["total_scanned"] = 10
        curr3["summary"]["buy_count"] = 10
        curr3["summary"]["watch_count"] = 5  # sum = 15 > total_scanned 10
        res3 = evaluate_data_and_model_drift(current_payload=curr3)
        self.assertEqual(res3.overall_status, "FAIL")

        # Case 4: total_scanned != len(recommendations)
        curr4 = make_mock_payload(data_as_of="2026-09-17")
        curr4["summary"]["total_scanned"] = 30  # len(recs) is 20
        res4 = evaluate_data_and_model_drift(current_payload=curr4)
        self.assertEqual(res4.overall_status, "FAIL")

        # Case 5: Summary action count does not match actual recommendation actions
        curr5 = make_mock_payload(data_as_of="2026-09-17")
        curr5["summary"]["buy_count"] = 10  # Actual BUY is 5
        curr5["summary"]["watch_count"] = 0
        res5 = evaluate_data_and_model_drift(current_payload=curr5)
        self.assertEqual(res5.overall_status, "FAIL")

        # Case 6: Sum of action counts < total_scanned
        curr6 = make_mock_payload(data_as_of="2026-09-17")
        curr6["summary"]["total_scanned"] = 20
        curr6["summary"]["buy_count"] = 0  # Sum = 15 < 20
        res6 = evaluate_data_and_model_drift(current_payload=curr6)
        self.assertEqual(res6.overall_status, "FAIL")

        # Case 7: Non-integer action count
        curr7 = make_mock_payload(data_as_of="2026-09-17")
        curr7["summary"]["buy_count"] = 5.5  # type: ignore[typeddict-item]
        res7 = evaluate_data_and_model_drift(current_payload=curr7)
        self.assertEqual(res7.overall_status, "FAIL")

        # Case 8: Bool count
        curr8 = make_mock_payload(data_as_of="2026-09-17")
        curr8["summary"]["buy_count"] = True  # type: ignore[typeddict-item]
        res8 = evaluate_data_and_model_drift(current_payload=curr8)
        self.assertEqual(res8.overall_status, "FAIL")

    def test_invalid_recommendation_action_value_fails_closed(self):
        """Verify missing, invalid, or non-canonical action values fail closed."""
        baselines = [make_mock_payload(data_as_of=f"2026-09-{16 - i:02d}") for i in range(5)]
        for bad_action in [None, "BUY_NOW", 123, True, "buy", "WATCHING"]:
            curr = make_mock_payload(data_as_of="2026-09-17")
            curr["recommendations"][0]["action"] = bad_action

            res = evaluate_data_and_model_drift(current_payload=curr, baseline_reports=baselines)
            self.assertEqual(
                res.overall_status,
                "FAIL",
                f"Failed to fail-closed on action={bad_action}",
            )
            self.assertEqual(res.drift_checks[0].check_name, "drift_current_payload_malformed")

    def test_invalid_market_metrics_fail_closed(self):
        """Verify string, bool, NaN, Inf, or out-of-range market metrics fail closed."""
        # 1. Invalid market_breadth_ratio
        for bad_breadth in ["0.6", True, float("nan"), float("inf"), -0.1, 1.5]:
            curr = make_mock_payload(data_as_of="2026-09-17")
            curr["market"]["metrics"]["market_breadth_ratio"] = bad_breadth

            res = evaluate_data_and_model_drift(current_payload=curr)
            self.assertEqual(
                res.overall_status,
                "FAIL",
                f"Failed to fail-closed on market_breadth_ratio={bad_breadth}",
            )

        # 2. Invalid vnindex_change_pct
        for bad_pct in ["0.5%", True, float("nan"), float("inf")]:
            curr = make_mock_payload(data_as_of="2026-09-17")
            curr["market"]["metrics"]["vnindex_change_pct"] = bad_pct

            res = evaluate_data_and_model_drift(current_payload=curr)
            self.assertEqual(
                res.overall_status,
                "FAIL",
                f"Failed to fail-closed on vnindex_change_pct={bad_pct}",
            )

    def test_invalid_threshold_configuration_fails_closed(self):
        """Verify invalid threshold configuration tuples raise ValueError."""
        curr = make_mock_payload(data_as_of="2026-09-17")
        baselines = [make_mock_payload(data_as_of=f"2026-09-{16 - i:02d}") for i in range(5)]

        import scripts.lib.monitoring as mon

        # Test warn < 0
        orig_proc_thresh = mon.DRIFT_THRESHOLD_PROCESSED_RATIO
        try:
            mon.DRIFT_THRESHOLD_PROCESSED_RATIO = (-0.1, 0.2)  # type: ignore[assignment]
            with self.assertRaises(ValueError):
                evaluate_data_and_model_drift(current_payload=curr, baseline_reports=baselines)
        finally:
            mon.DRIFT_THRESHOLD_PROCESSED_RATIO = orig_proc_thresh

        # Test fail < warn
        orig_signal_thresh = mon.DRIFT_THRESHOLD_SIGNAL_SCORE_MEAN
        try:
            mon.DRIFT_THRESHOLD_SIGNAL_SCORE_MEAN = (20.0, 10.0)  # type: ignore[assignment]
            with self.assertRaises(ValueError):
                evaluate_data_and_model_drift(current_payload=curr, baseline_reports=baselines)
        finally:
            mon.DRIFT_THRESHOLD_SIGNAL_SCORE_MEAN = orig_signal_thresh

    def test_baseline_artifact_missing_data_as_of_with_source_date_fails_closed(self):
        """Verify baseline report having source_date but missing data_as_of fails closed with FAIL status."""
        curr = make_mock_payload(data_as_of="2026-09-17")
        b_bad = make_mock_payload(data_as_of="2026-09-16")
        del b_bad["data_as_of"]  # Has source_date="2026-09-16" but missing data_as_of!

        res = evaluate_data_and_model_drift(
            data_as_of="2026-09-17",
            current_payload=curr,
            baseline_reports=[b_bad],
        )

        self.assertEqual(res.overall_status, "FAIL")
        self.assertEqual(res.drift_checks[0].check_name, "drift_baseline_reports_injected")

    def test_market_payload_temporal_consistency(self):
        """Verify strict temporal consistency check for explicit market_payload."""
        curr = make_mock_payload(data_as_of="2026-09-17")

        # 1. Market payload same date T -> PASS (with valid baselines)
        baselines = [make_mock_payload(data_as_of=f"2026-09-{16 - i:02d}") for i in range(5)]
        m_valid = {
            "data_as_of": "2026-09-17",
            "regime": "BULL",
            "confidence": 0.85,
            "metrics": {
                "vnindex_value": 1250.0,
                "vnindex_change_pct": 0.5,
                "market_breadth_ratio": 0.60,
            },
        }
        res1 = evaluate_data_and_model_drift(
            data_as_of="2026-09-17",
            current_payload=curr,
            market_payload=m_valid,
            baseline_reports=baselines,
        )
        self.assertEqual(res1.overall_status, "PASS")

        # 2. Market payload with date < T -> FAIL
        m_past = dict(m_valid, data_as_of="2026-09-16")
        res2 = evaluate_data_and_model_drift(
            data_as_of="2026-09-17",
            current_payload=curr,
            market_payload=m_past,
        )
        self.assertEqual(res2.overall_status, "FAIL")
        self.assertEqual(res2.drift_checks[0].check_name, "drift_market_payload_temporal_safety")

        # 3. Market payload with date > T -> FAIL
        m_future = dict(m_valid, data_as_of="2026-09-18")
        res3 = evaluate_data_and_model_drift(
            data_as_of="2026-09-17",
            current_payload=curr,
            market_payload=m_future,
        )
        self.assertEqual(res3.overall_status, "FAIL")

        # 4. Malformed/non-canonical date -> FAIL
        m_bad_date = dict(m_valid, data_as_of="2026-9-17")
        res4 = evaluate_data_and_model_drift(
            data_as_of="2026-09-17",
            current_payload=curr,
            market_payload=m_bad_date,
        )
        self.assertEqual(res4.overall_status, "FAIL")

        # 5. Market payload missing data_as_of -> FAIL
        m_no_date = {
            "regime": "BULL",
            "confidence": 0.85,
            "metrics": {
                "vnindex_value": 1250.0,
                "vnindex_change_pct": 0.5,
                "market_breadth_ratio": 0.60,
            },
        }
        res5 = evaluate_data_and_model_drift(
            data_as_of="2026-09-17",
            current_payload=curr,
            market_payload=m_no_date,
        )
        self.assertEqual(res5.overall_status, "FAIL")


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
        """Verify drift FAIL result forces evaluate_production_monitoring overall_status to FAIL.

        Demonstrates exact chain: action distribution drift -> drift check FAIL -> drift_monitoring FAIL -> production monitoring FAIL.
        """
        import json
        import os
        import tempfile

        curr_action_drift = make_mock_payload(
            data_as_of="2026-09-17",
            buy_count=18,
            watch_count=1,
            hold_count=1,
            sell_count=0,
            avoid_count=0,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            history_dir = os.path.join(tmpdir, "history")
            os.makedirs(history_dir, exist_ok=True)

            index_dates = [
                "2026-09-17",
                "2026-09-16",
                "2026-09-15",
                "2026-09-14",
                "2026-09-13",
                "2026-09-12",
            ]
            with open(os.path.join(tmpdir, "recommendations.json"), "w", encoding="utf-8") as f:
                json.dump(curr_action_drift, f)

            with open(os.path.join(tmpdir, "market.json"), "w", encoding="utf-8") as f:
                json.dump(curr_action_drift["market"], f)

            with open(os.path.join(history_dir, "index.json"), "w", encoding="utf-8") as f:
                json.dump({"dates": index_dates}, f)

            with open(os.path.join(history_dir, "2026-09-17.json"), "w", encoding="utf-8") as f:
                json.dump(curr_action_drift, f)

            for d in index_dates[1:]:
                baseline_p = make_mock_payload(
                    data_as_of=d,
                    buy_count=5,
                    watch_count=5,
                    hold_count=5,
                    sell_count=5,
                    avoid_count=0,
                )
                with open(os.path.join(history_dir, f"{d}.json"), "w", encoding="utf-8") as f:
                    json.dump(baseline_p, f)

            res = evaluate_production_monitoring(
                generated_dir=tmpdir,
                recommendations_payload=curr_action_drift,
                reference_date="2026-09-17",
            )

            self.assertEqual(res.metrics["drift_monitoring"]["overall_status"], "FAIL")
            drift_action_chk = next(
                c for c in res.checks if c.check_name == "drift_action_distribution"
            )
            self.assertEqual(drift_action_chk.status, "FAIL")
            self.assertEqual(res.overall_status, "FAIL")


class TestBaselineAggregationSemantics(unittest.TestCase):
    """Test suite verifying pooled recommendation observation aggregation vs report-level market metrics aggregation."""

    def test_pooled_baseline_aggregation_with_unequal_recommendation_counts(self):
        """Verify recommendation metrics use pooled observation totals while market metrics use daily/report-level mean."""
        # Baseline A: 10 recommendations (5 BUY, 5 WATCH), total_scanned=10
        base_a = make_mock_payload(
            data_as_of="2026-09-16",
            total_scanned=10,
            buy_count=5,
            watch_count=5,
            hold_count=0,
            sell_count=0,
            avoid_count=0,
            signal_score=80.0,
            risk_adjusted_score=75.0,
            confidence=0.85,
            market_breadth_ratio=0.40,
            vnindex_change_pct=1.0,
        )

        # Baseline B: 100 recommendations (10 BUY, 90 WATCH), total_scanned=100
        base_b = make_mock_payload(
            data_as_of="2026-09-15",
            total_scanned=100,
            buy_count=10,
            watch_count=90,
            hold_count=0,
            sell_count=0,
            avoid_count=0,
            signal_score=50.0,
            risk_adjusted_score=45.0,
            confidence=0.55,
            market_breadth_ratio=0.80,
            vnindex_change_pct=3.0,
        )

        # Extra 3 baselines: each has 10 recs (2 BUY, 2 WATCH, 2 HOLD, 2 SELL, 2 AVOID)
        extra_baselines = [
            make_mock_payload(
                data_as_of=f"2026-09-{14 - i:02d}",
                total_scanned=10,
                buy_count=2,
                watch_count=2,
                hold_count=2,
                sell_count=2,
                avoid_count=2,
                signal_score=60.0,
                risk_adjusted_score=55.0,
                confidence=0.65,
                market_breadth_ratio=0.60,
                vnindex_change_pct=2.0,
            )
            for i in range(3)
        ]

        baselines = [base_a, base_b] + extra_baselines

        curr = make_mock_payload(data_as_of="2026-09-17")

        res = evaluate_data_and_model_drift(
            data_as_of="2026-09-17",
            current_payload=curr,
            baseline_reports=baselines,
        )

        b_metrics = res.baseline_summary["baseline_metrics"]

        # Action distribution from pooled counts: 21 BUY / 140 pooled scanned = 0.15
        self.assertEqual(b_metrics["action_proportions"]["BUY"], round(21 / 140, 6))

        # Processed ratio: 134 processed / 140 scanned
        self.assertEqual(b_metrics["processed_ratio"], round(134 / 140, 6))

        # Confidence bucket distribution
        self.assertEqual(b_metrics["confidence_bucket_proportions"]["0.8-0.9"], round(10 / 134, 6))
        self.assertEqual(b_metrics["confidence_bucket_proportions"]["0.5-0.6"], round(100 / 134, 6))
        self.assertEqual(b_metrics["confidence_bucket_proportions"]["0.6-0.7"], round(24 / 134, 6))

        # Pooled numeric means across 134 valid observations
        self.assertEqual(b_metrics["signal_score_mean"], round(7240.0 / 134, 4))
        self.assertEqual(b_metrics["risk_adjusted_score_mean"], round(6570.0 / 134, 4))
        self.assertEqual(b_metrics["confidence_mean"], round(79.1 / 134, 4))

        # Market metrics remain daily/report-level mean across 5 reports
        self.assertEqual(b_metrics["market_breadth_ratio"], 0.600000)
        self.assertEqual(b_metrics["vnindex_change_pct"], 2.0000)


if __name__ == "__main__":
    unittest.main()
