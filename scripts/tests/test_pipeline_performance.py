"""Deterministic offline unit tests for production pipeline performance profiling.

Tests performance timing instrumentation, stage ordering, provider timing aggregation,
duplicate work detection, fail-closed guarantees, and output invariance without live network access.
"""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from scripts.data_provider import (
    ProviderRateLimitError,
    VnstockDataProvider,
    aggregate_provider_performance,
    detect_duplicate_operations,
    reset_circuit_breaker,
    reset_rate_limit_recovery_count,
)
from scripts.generate_report import (
    PerformanceTracker,
    PipelineResult,
    run_pipeline,
    validate_performance_payload,
)
from scripts.generate_report import (
    main as generate_report_main,
)
from scripts.lib.config import PERFORMANCE_STAGE_BASELINES
from scripts.lib.monitoring import (
    evaluate_performance_regression,
    evaluate_production_monitoring,
    evaluate_provider_budget,
)


def make_valid_performance_payload():
    """Construct a valid canonical performance payload for schema testing."""
    return {
        "stages": [
            {
                "stage": "pipeline",
                "elapsed_seconds": 1.234,
                "status": "SUCCESS",
            },
            {
                "stage": "benchmark_fetch",
                "elapsed_seconds": 0.5,
                "status": "SUCCESS",
            },
        ],
        "provider": {
            "total_calls": 2,
            "successful_calls": 2,
            "failed_calls": 0,
            "retry_count": 0,
            "total_elapsed_seconds": 0.5,
            "average_call_seconds": 0.25,
            "calls_by_source": {"kbs": 2},
        },
        "duplicate_operations": [
            {
                "symbol": "FPT",
                "provider_call_count": 2,
                "request_count": 2,
                "successful_calls": 1,
                "failed_calls": 1,
                "retry_count": 0,
            }
        ],
    }


def make_valid_canonical_df(num_rows: int = 25, start_date: str = "2026-08-01") -> pd.DataFrame:
    """Construct a valid canonical EOD OHLCV DataFrame."""
    dates = pd.date_range(start=start_date, periods=num_rows, freq="D").strftime("%Y-%m-%d")
    data = []
    base_price = 50000.0
    for i, d in enumerate(dates):
        p = base_price + (i * 100.0)
        data.append(
            {
                "time": d,
                "open": p,
                "high": p + 500.0,
                "low": p - 500.0,
                "close": p + 200.0,
                "volume": 100000 + (i * 1000),
            }
        )
    return pd.DataFrame(data)


class TestPipelinePerformanceProfiling(unittest.TestCase):
    def setUp(self):
        reset_circuit_breaker()
        reset_rate_limit_recovery_count()
        VnstockDataProvider.reset_global_call_history()

    def tearDown(self):
        reset_circuit_breaker()
        reset_rate_limit_recovery_count()
        VnstockDataProvider.reset_global_call_history()

    @patch("scripts.generate_report.time.perf_counter")
    @patch("scripts.generate_report.get_historical_data")
    def test_1_every_required_pipeline_stage_produces_timing_record(self, mock_get_hist, mock_perf):
        """1. Every required pipeline stage produces a timing record with stable fields in main flow."""

        valid_df = make_valid_canonical_df(25, start_date="2026-09-01")
        mock_get_hist.return_value = (valid_df, "REAL_DATA", [])
        mock_perf.side_effect = [10.0 + (i * 0.1) for i in range(200)]

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch("scripts.generate_report.GENERATED_DIR", f"{tmpdir}/generated"),
            patch("sys.argv", ["generate_report.py"]),
        ):
            gen_dir = Path(tmpdir) / "generated"
            gen_dir.mkdir(parents=True, exist_ok=True)
            hist_dir = gen_dir / "history"
            hist_dir.mkdir(parents=True, exist_ok=True)
            (hist_dir / "index.json").write_text(json.dumps({"dates": []}), encoding="utf-8")
            try:
                generate_report_main()
            except SystemExit:
                pass

            mon_file = gen_dir / "monitoring.json"
            self.assertTrue(mon_file.exists())
            mon_data = json.loads(mon_file.read_text(encoding="utf-8"))
            perf = mon_data["metrics"]["performance"]

            stage_names = [s["stage"] for s in perf["stages"]]
            required_stages = [
                "pipeline",
                "benchmark_fetch",
                "stock_fetch",
                "temporal_validation",
                "market_calculation",
                "regime_calculation",
                "risk_calculation",
                "recommendation_calculation",
                "monitoring",
                "payload_validation",
            ]

            for req in required_stages:
                self.assertIn(req, stage_names, f"Missing required stage timing record for '{req}'")

            for record in perf["stages"]:
                self.assertIn("stage", record)
                self.assertIn("elapsed_seconds", record)
                self.assertIn("status", record)
                self.assertIsInstance(record["elapsed_seconds"], (int, float))
                self.assertIn(record["status"], ("SUCCESS", "FAILED"))

    @patch("scripts.generate_report.time.perf_counter")
    @patch("scripts.generate_report.get_historical_data")
    def test_2_stage_ordering_is_deterministic(self, mock_get_hist, mock_perf):
        """2. Stage ordering in performance payload is strictly deterministic."""

        valid_df = make_valid_canonical_df(25, start_date="2026-09-01")
        mock_get_hist.return_value = (valid_df, "REAL_DATA", [])
        mock_perf.side_effect = [1.0 + (i * 0.05) for i in range(200)]

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch("scripts.generate_report.GENERATED_DIR", f"{tmpdir}/generated"),
            patch("sys.argv", ["generate_report.py"]),
        ):
            gen_dir = Path(tmpdir) / "generated"
            gen_dir.mkdir(parents=True, exist_ok=True)
            hist_dir = gen_dir / "history"
            hist_dir.mkdir(parents=True, exist_ok=True)
            (hist_dir / "index.json").write_text(json.dumps({"dates": []}), encoding="utf-8")
            try:
                generate_report_main()
            except SystemExit:
                pass

            mon_data = json.loads((gen_dir / "monitoring.json").read_text(encoding="utf-8"))
            stages1 = [s["stage"] for s in mon_data["metrics"]["performance"]["stages"]]

        expected_order = [
            "pipeline",
            "benchmark_fetch",
            "stock_fetch",
            "temporal_validation",
            "market_calculation",
            "regime_calculation",
            "recommendation_calculation",
            "risk_calculation",
            "monitoring",
            "payload_validation",
        ]
        self.assertEqual(stages1, expected_order)

    def test_3_provider_timing_from_pr155_aggregated_correctly(self):
        """3. Provider call timing history is aggregated correctly."""
        call_history = [
            {
                "provider": "vnstock",
                "source": "kbs",
                "operation": "history",
                "symbol": "VNINDEX",
                "elapsed_seconds": 0.1234,
                "success": True,
                "retry_count": 0,
                "error": None,
            },
            {
                "provider": "vnstock",
                "source": "kbs",
                "operation": "history",
                "symbol": "FPT",
                "elapsed_seconds": 0.5000,
                "success": False,
                "retry_count": 0,
                "error": "Timeout",
            },
            {
                "provider": "vnstock",
                "source": "msn",
                "operation": "history",
                "symbol": "FPT",
                "elapsed_seconds": 0.2500,
                "success": True,
                "retry_count": 1,
                "error": None,
            },
        ]

        summary = aggregate_provider_performance(call_history)
        self.assertEqual(summary["total_calls"], 3)
        self.assertEqual(summary["successful_calls"], 2)
        self.assertEqual(summary["failed_calls"], 1)
        self.assertEqual(summary["retry_count"], 1)
        self.assertEqual(summary["total_elapsed_seconds"], 0.8734)
        self.assertEqual(summary["average_call_seconds"], 0.2911)
        self.assertEqual(summary["calls_by_source"], {"kbs": 2, "msn": 1})

    def test_4_successful_provider_call_count_accuracy(self):
        """4. Successful provider call count accuracy in performance payload."""
        call_history = [
            {
                "source": "kbs",
                "symbol": "ACB",
                "elapsed_seconds": 0.1,
                "success": True,
                "retry_count": 0,
            },
            {
                "source": "kbs",
                "symbol": "VCB",
                "elapsed_seconds": 0.1,
                "success": True,
                "retry_count": 0,
            },
            {
                "source": "msn",
                "symbol": "HPG",
                "elapsed_seconds": 0.1,
                "success": False,
                "retry_count": 0,
            },
        ]

        summary = aggregate_provider_performance(call_history)
        self.assertEqual(summary["successful_calls"], 2)
        self.assertEqual(summary["total_calls"], 3)

    def test_5_failed_provider_call_count_accuracy(self):
        """5. Failed provider call count accuracy in performance payload."""
        call_history = [
            {
                "source": "kbs",
                "symbol": "ACB",
                "elapsed_seconds": 0.1,
                "success": False,
                "retry_count": 0,
            },
            {
                "source": "msn",
                "symbol": "ACB",
                "elapsed_seconds": 0.1,
                "success": False,
                "retry_count": 1,
            },
        ]

        summary = aggregate_provider_performance(call_history)
        self.assertEqual(summary["failed_calls"], 2)
        self.assertEqual(summary["successful_calls"], 0)

    def test_6_retry_and_fallback_calls_represented_correctly(self):
        """6. Retry and source fallback calls are represented accurately."""
        call_history = [
            {
                "source": "kbs",
                "symbol": "FPT",
                "elapsed_seconds": 0.2,
                "success": False,
                "retry_count": 0,
            },
            {
                "source": "msn",
                "symbol": "FPT",
                "elapsed_seconds": 0.3,
                "success": True,
                "retry_count": 0,
            },
        ]

        summary = aggregate_provider_performance(call_history)
        self.assertEqual(summary["total_calls"], 2)
        self.assertEqual(summary["successful_calls"], 1)
        self.assertEqual(summary["failed_calls"], 1)
        self.assertEqual(summary["calls_by_source"]["kbs"], 1)
        self.assertEqual(summary["calls_by_source"]["msn"], 1)

    def test_7_duplicate_symbol_detection(self):
        """7. Duplicate symbol requests or repeated calls are detected correctly."""
        call_history = [
            {"symbol": "FPT", "elapsed_seconds": 0.1, "success": False, "retry_count": 0},
            {"symbol": "FPT", "elapsed_seconds": 0.1, "success": True, "retry_count": 1},
            {"symbol": "VCB", "elapsed_seconds": 0.1, "success": True, "retry_count": 0},
        ]

        symbol_requests = {"FPT": 2, "VCB": 1}
        duplicates = detect_duplicate_operations(call_history, symbol_requests)

        self.assertEqual(len(duplicates), 1)
        dup = duplicates[0]
        self.assertEqual(dup["symbol"], "FPT")
        self.assertEqual(dup["provider_call_count"], 2)
        self.assertEqual(dup["request_count"], 2)

    def test_8_duplicate_work_diagnostics(self):
        """8. Duplicate work diagnostics expose provider call count details."""
        call_history = [
            {"symbol": "FPT", "elapsed_seconds": 0.1, "success": True, "retry_count": 0},
            {"symbol": "FPT", "elapsed_seconds": 0.1, "success": True, "retry_count": 0},
        ]

        duplicates = detect_duplicate_operations(call_history)
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0]["symbol"], "FPT")
        self.assertEqual(duplicates[0]["provider_call_count"], 2)
        self.assertEqual(duplicates[0]["successful_calls"], 2)
        self.assertEqual(duplicates[0]["failed_calls"], 0)

    @patch("scripts.generate_report.get_historical_data")
    def test_9_instrumentation_does_not_change_pipeline_output(self, mock_get_hist):
        """9. Performance instrumentation produces identical quantitative report structure."""
        valid_df = make_valid_canonical_df(25)
        mock_get_hist.return_value = (valid_df, "REAL_DATA", [])

        res_uninstrumented = run_pipeline(update_data=False)
        res_instrumented = run_pipeline(update_data=False, tracker=PerformanceTracker())

        recs1, market1, _history1 = res_uninstrumented
        recs2, market2, _history2 = res_instrumented

        self.assertEqual(recs1["summary"], recs2["summary"])
        self.assertEqual(market1["market"]["regime"], market2["market"]["regime"])
        self.assertEqual(len(recs1["recommendations"]), len(recs2["recommendations"]))

    @patch("scripts.generate_report.get_historical_data")
    def test_10_instrumentation_does_not_alter_recommendation_results(self, mock_get_hist):
        """10. Recommendations and signals are 100% identical with instrumentation."""
        valid_df = make_valid_canonical_df(25)
        mock_get_hist.return_value = (valid_df, "REAL_DATA", [])

        res1 = run_pipeline(update_data=False)
        res2 = run_pipeline(update_data=False, tracker=PerformanceTracker())

        recs1 = res1[0]["recommendations"]
        recs2 = res2[0]["recommendations"]

        for r1, r2 in zip(recs1, recs2, strict=True):
            self.assertEqual(r1["symbol"], r2["symbol"])
            self.assertEqual(r1["action"], r2["action"])
            self.assertEqual(r1.get("signal_score"), r2.get("signal_score"))
            self.assertEqual(r1.get("risk_adjusted_score"), r2.get("risk_adjusted_score"))

    @patch("scripts.generate_report.get_historical_data")
    def test_11_instrumentation_does_not_alter_monitoring_status(self, mock_get_hist):
        """11. Production monitoring status is unchanged by performance tracking."""
        from scripts.lib.monitoring import evaluate_production_monitoring

        valid_df = make_valid_canonical_df(25)
        mock_get_hist.return_value = (valid_df, "REAL_DATA", [])

        res = run_pipeline(update_data=False)

        with tempfile.TemporaryDirectory() as tmpdir:
            gen_dir = Path(tmpdir)
            history_dir = gen_dir / "history"
            history_dir.mkdir(parents=True, exist_ok=True)
            as_of = res[0]["data_as_of"]

            (gen_dir / "recommendations.json").write_text(json.dumps(res[0]), encoding="utf-8")
            (gen_dir / "market.json").write_text(json.dumps(res[1]), encoding="utf-8")

            index_data = {
                "last_updated": "2026-08-25T00:00:00Z",
                "total_reports": 1,
                "dates": [as_of],
            }
            (history_dir / "index.json").write_text(json.dumps(index_data), encoding="utf-8")
            (history_dir / f"{as_of}.json").write_text(json.dumps(res[0]), encoding="utf-8")

            mon_res = evaluate_production_monitoring(
                generated_dir=tmpdir,
                recommendations_payload=res[0],
                market_payload=res[1],
                reference_date=as_of,
                df_vnindex=res.df_vnindex,
                df_vn30=res.df_vn30,
                universe_audit=res.universe_audit,
            )

            self.assertIn(mon_res.overall_status, ("PASS", "WARNING"))
            mon_dict = mon_res.to_dict()
            self.assertIn("performance", mon_dict["metrics"])

    @patch("scripts.generate_report.get_historical_data")
    def test_12_provider_failure_remains_fail_closed(self, mock_get_hist):
        """12. Provider failure remains fail-closed and attaches performance diagnostics."""
        mock_get_hist.side_effect = RuntimeError("Provider offline")

        tracker = PerformanceTracker()
        with self.assertRaises(RuntimeError) as ctx:
            run_pipeline(update_data=True, tracker=tracker)

        self.assertIn("Incomplete universe scan in update mode", str(ctx.exception))
        audit = getattr(ctx.exception, "universe_audit", None)
        self.assertIsNotNone(audit)
        self.assertIn("performance", audit)

        failed_stages = [s for s in audit["performance"]["stages"] if s["status"] == "FAILED"]
        self.assertGreater(len(failed_stages), 0)

    @patch("scripts.generate_report.get_historical_data")
    def test_13_rate_limit_behavior_remains_unchanged(self, mock_get_hist):
        """13. Rate limit handling remains unchanged and raises ProviderRateLimitError loudly."""
        mock_get_hist.side_effect = ProviderRateLimitError(
            "Quota exceeded for FPT", cooldown_seconds=30, symbol="FPT"
        )

        tracker = PerformanceTracker()
        with self.assertRaises(ProviderRateLimitError) as ctx:
            run_pipeline(update_data=True, tracker=tracker)

        self.assertEqual(ctx.exception.symbol, "FPT")
        audit = getattr(ctx.exception, "universe_audit", None)
        self.assertIsNotNone(audit)
        self.assertIn("performance", audit)

    @patch("scripts.generate_report.get_historical_data")
    def test_14_canonical_date_freshness_remains_enforced(self, mock_get_hist):
        """14. Temporal integrity / canonical date freshness rules remain strictly enforced."""
        vnindex_df = make_valid_canonical_df(25, start_date="2026-08-01")
        stale_df = make_valid_canonical_df(10, start_date="2026-08-01")  # Stale relative to VNINDEX

        def side_effect(symbol, **kwargs):
            if symbol == "VNINDEX" or symbol == "VN30":
                return vnindex_df, "REAL_DATA", []
            return stale_df, "REAL_DATA", []

        mock_get_hist.side_effect = side_effect

        with self.assertRaises(RuntimeError) as ctx:
            run_pipeline(update_data=True)

        self.assertIn("Incomplete universe scan in update mode", str(ctx.exception))

    def test_15_output_artifacts_remain_protected_on_failure(self):
        """15. Output artifacts in generated/ remain protected and untouched on failure."""

        with tempfile.TemporaryDirectory() as tmpdir:
            gen_dir = Path(tmpdir) / "generated"
            gen_dir.mkdir(parents=True, exist_ok=True)

            recs_file = gen_dir / "recommendations.json"
            initial_content = {
                "schema_version": "2.0",
                "recommendations": [{"symbol": "PRESERVED"}],
            }
            recs_file.write_text(json.dumps(initial_content), encoding="utf-8")

            with (
                patch("scripts.generate_report.GENERATED_DIR", str(gen_dir)),
                patch(
                    "scripts.generate_report.run_pipeline",
                    side_effect=RuntimeError("Pipeline benchmark failure"),
                ),
                patch("sys.argv", ["generate_report.py", "--update"]),
                self.assertRaises(SystemExit) as ctx,
            ):
                generate_report_main()

                self.assertEqual(ctx.exception.code, 1)

            # Artifact file preserved on disk
            saved_content = json.loads(recs_file.read_text(encoding="utf-8"))
            self.assertEqual(saved_content, initial_content)

    @patch("scripts.generate_report.evaluate_production_monitoring")
    @patch("scripts.generate_report.time.perf_counter")
    @patch("scripts.generate_report.get_historical_data")
    def test_16_monitoring_elapsed_time_corresponds_to_mocked_execution(
        self, mock_get_hist, mock_perf, mock_eval_mon
    ):
        """16. Monitoring elapsed time corresponds to actual evaluate_production_monitoring() execution."""
        from unittest.mock import MagicMock

        valid_df = make_valid_canonical_df(25)
        mock_get_hist.return_value = (valid_df, "REAL_DATA", [])

        mock_mon_result = MagicMock()
        mock_mon_result.overall_status = "PASS"
        mock_mon_result.to_dict.return_value = {
            "overall_status": "PASS",
            "metrics": {},
        }

        counter_state = {"current": 10.0}

        def perf_side_effect():
            return counter_state["current"]

        def eval_mon_side_effect(*args, **kwargs):
            counter_state["current"] += 2.5000
            return mock_mon_result

        mock_perf.side_effect = perf_side_effect
        mock_eval_mon.side_effect = eval_mon_side_effect

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch("scripts.generate_report.GENERATED_DIR", f"{tmpdir}/generated"),
            patch("sys.argv", ["generate_report.py"]),
        ):
            gen_dir = Path(tmpdir) / "generated"
            gen_dir.mkdir(parents=True, exist_ok=True)
            generate_report_main()

            mon_file = gen_dir / "monitoring.json"
            mon_data = json.loads(mon_file.read_text(encoding="utf-8"))
            stages = mon_data["metrics"]["performance"]["stages"]
            mon_stage = next(s for s in stages if s["stage"] == "monitoring")
            self.assertEqual(mon_stage["status"], "SUCCESS")
            self.assertEqual(mon_stage["elapsed_seconds"], 2.5000)

    def test_17_monitoring_failure_produces_failed_stage_status(self):
        """17. Exception during monitoring stage records status 'FAILED' in performance tracker."""
        tracker = PerformanceTracker()
        with self.assertRaises(RuntimeError), tracker.measure_stage("monitoring"):
            raise RuntimeError("Monitoring system crash")

        payload = tracker.get_performance_payload()
        mon_stage = next(s for s in payload["stages"] if s["stage"] == "monitoring")
        self.assertEqual(mon_stage["status"], "FAILED")

    def test_18_payload_validation_with_injected_failure_produces_failed(self):
        """18. Injected integrity failure in payload_validation stage records status 'FAILED'."""
        from scripts.generate_report import validate_final_payload_integrity

        tracker = PerformanceTracker()
        invalid_payload = {"data_as_of": "INVALID_DATE"}

        with self.assertRaises(ValueError), tracker.measure_stage("payload_validation"):
            validate_final_payload_integrity(invalid_payload, schema=None)

        payload = tracker.get_performance_payload()
        val_stage = next(s for s in payload["stages"] if s["stage"] == "payload_validation")
        self.assertEqual(val_stage["status"], "FAILED")

    def test_19_successful_payload_validation_produces_success(self):
        """19. Successful payload validation records stage status 'SUCCESS'."""
        from scripts.generate_report import validate_final_payload_integrity

        tracker = PerformanceTracker()
        valid_payload = {
            "schema_version": "2.0",
            "generated_at": "2026-08-25T00:00:00Z",
            "data_as_of": "2026-08-25",
            "source_date": "2026-08-25",
            "summary": {
                "total_scanned": 0,
                "buy_count": 0,
                "watch_count": 0,
                "hold_count": 0,
                "sell_count": 0,
                "avoid_count": 0,
            },
            "recommendations": [],
        }

        with tracker.measure_stage("payload_validation"):
            validate_final_payload_integrity(valid_payload, schema=None)

        payload = tracker.get_performance_payload()
        val_stage = next(s for s in payload["stages"] if s["stage"] == "payload_validation")
        self.assertEqual(val_stage["status"], "SUCCESS")

    def test_20_historical_path_does_not_contain_monitoring_measurement(self):
        """20. Historical report generation path does NOT contain a fake/pass monitoring stage."""
        from scripts.generate_report import generate_historical_report

        df_index = make_valid_canonical_df(25, start_date="2026-08-01")
        canonical_as_of = df_index["time"].iloc[-1]
        metadata = [{"symbol": "FPT", "companyName": "FPT Corp", "sector": "Tech"}]
        stock_map = {"FPT": make_valid_canonical_df(25, start_date="2026-08-01")}

        pipeline_res = generate_historical_report(
            data_as_of=canonical_as_of,
            universe_stock_map=stock_map,
            df_vnindex=df_index,
            candidate_metadata=metadata,
        )

        stages = [s["stage"] for s in pipeline_res.universe_audit["performance"]["stages"]]
        self.assertNotIn("monitoring", stages)
        self.assertIn("payload_validation", stages)

    @patch("scripts.generate_report.time.perf_counter")
    @patch("scripts.generate_report.get_historical_data")
    def test_21_stage_ordering_in_main_flow_remains_unchanged(self, mock_get_hist, mock_perf):
        """21. Main pipeline stage ordering matches expected canonical order strictly."""

        valid_df = make_valid_canonical_df(25, start_date="2026-09-01")
        mock_get_hist.return_value = (valid_df, "REAL_DATA", [])
        mock_perf.side_effect = [1.0 + (i * 0.05) for i in range(200)]

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch("scripts.generate_report.GENERATED_DIR", f"{tmpdir}/generated"),
            patch("sys.argv", ["generate_report.py"]),
        ):
            gen_dir = Path(tmpdir) / "generated"
            gen_dir.mkdir(parents=True, exist_ok=True)
            hist_dir = gen_dir / "history"
            hist_dir.mkdir(parents=True, exist_ok=True)
            (hist_dir / "index.json").write_text(json.dumps({"dates": []}), encoding="utf-8")
            try:
                generate_report_main()
            except SystemExit:
                pass

            mon_data = json.loads((gen_dir / "monitoring.json").read_text(encoding="utf-8"))
            stages = [s["stage"] for s in mon_data["metrics"]["performance"]["stages"]]

        expected_order = [
            "pipeline",
            "benchmark_fetch",
            "stock_fetch",
            "temporal_validation",
            "market_calculation",
            "regime_calculation",
            "recommendation_calculation",
            "risk_calculation",
            "monitoring",
            "payload_validation",
        ]
        self.assertEqual(stages, expected_order)


class TestPerformanceSchemaValidation(unittest.TestCase):
    def test_valid_performance_payload_passes_validation(self):
        payload = make_valid_performance_payload()
        validate_performance_payload(payload)

    @patch(
        "scripts.generate_report.PERFORMANCE_SCHEMA_PATH",
        "/non/existent/path/performance.schema.json",
    )
    def test_missing_performance_schema_file_fails_closed(self):
        payload = make_valid_performance_payload()
        with self.assertRaises(FileNotFoundError):
            validate_performance_payload(payload)

    def test_missing_required_fields_fail_schema_validation(self):
        import jsonschema

        for req_field in ["stages", "provider", "duplicate_operations"]:
            payload = make_valid_performance_payload()
            del payload[req_field]
            with self.assertRaises(jsonschema.ValidationError):
                validate_performance_payload(payload)

    def test_invalid_stage_name_fails_schema_validation(self):
        import jsonschema

        payload = make_valid_performance_payload()
        payload["stages"][0]["stage"] = "invalid_stage_name"
        with self.assertRaises(jsonschema.ValidationError):
            validate_performance_payload(payload)

    def test_invalid_stage_status_fails_schema_validation(self):
        import jsonschema

        payload = make_valid_performance_payload()
        payload["stages"][0]["status"] = "PENDING"
        with self.assertRaises(jsonschema.ValidationError):
            validate_performance_payload(payload)

    def test_invalid_numeric_values_fail_schema_validation(self):
        import jsonschema

        # Negative elapsed seconds
        payload = make_valid_performance_payload()
        payload["stages"][0]["elapsed_seconds"] = -1.0
        with self.assertRaises(jsonschema.ValidationError):
            validate_performance_payload(payload)

        # Non-numeric string for elapsed seconds
        payload = make_valid_performance_payload()
        payload["stages"][0]["elapsed_seconds"] = "1.234"
        with self.assertRaises(jsonschema.ValidationError):
            validate_performance_payload(payload)

    def test_malformed_provider_metrics_fail_schema_validation(self):
        import jsonschema

        payload = make_valid_performance_payload()
        payload["provider"]["total_calls"] = -5
        with self.assertRaises(jsonschema.ValidationError):
            validate_performance_payload(payload)

        payload = make_valid_performance_payload()
        payload["provider"]["calls_by_source"]["kbs"] = "two"
        with self.assertRaises(jsonschema.ValidationError):
            validate_performance_payload(payload)

    def test_malformed_duplicate_operations_fail_schema_validation(self):
        import jsonschema

        payload = make_valid_performance_payload()
        payload["duplicate_operations"][0]["symbol"] = ""
        with self.assertRaises(jsonschema.ValidationError):
            validate_performance_payload(payload)

        payload = make_valid_performance_payload()
        payload["duplicate_operations"][0]["provider_call_count"] = -1
        with self.assertRaises(jsonschema.ValidationError):
            validate_performance_payload(payload)

    @patch("scripts.generate_report.get_historical_data")
    def test_audit_and_monitoring_metrics_expose_same_canonical_performance_object(
        self, mock_get_hist
    ):
        from scripts.lib.monitoring import evaluate_production_monitoring

        valid_df = make_valid_canonical_df(25)
        mock_get_hist.return_value = (valid_df, "REAL_DATA", [])

        res = run_pipeline(update_data=False)
        audit_perf = res.universe_audit.get("performance")
        self.assertIsNotNone(audit_perf)

        with tempfile.TemporaryDirectory() as tmpdir:
            gen_dir = Path(tmpdir)
            history_dir = gen_dir / "history"
            history_dir.mkdir(parents=True, exist_ok=True)
            as_of = res[0]["data_as_of"]

            (gen_dir / "recommendations.json").write_text(json.dumps(res[0]), encoding="utf-8")
            (gen_dir / "market.json").write_text(json.dumps(res[1]), encoding="utf-8")

            index_data = {
                "last_updated": "2026-08-25T00:00:00Z",
                "total_reports": 1,
                "dates": [as_of],
            }
            (history_dir / "index.json").write_text(json.dumps(index_data), encoding="utf-8")
            (history_dir / f"{as_of}.json").write_text(json.dumps(res[0]), encoding="utf-8")

            mon_res = evaluate_production_monitoring(
                generated_dir=tmpdir,
                recommendations_payload=res[0],
                market_payload=res[1],
                reference_date=as_of,
                df_vnindex=res.df_vnindex,
                df_vn30=res.df_vn30,
                universe_audit=res.universe_audit,
            )

            mon_perf = mon_res.metrics.get("performance")
            self.assertEqual(audit_perf, mon_perf)


class TestPerformanceRegressionAndBudget(unittest.TestCase):
    """Deterministic offline unit tests for performance regression detection and provider budget enforcement."""

    def test_baseline_calculation(self):
        """Verify performance regression evaluates actual durations against centralized stage baselines."""
        performance_payload = {
            "stages": [
                {"stage": "pipeline", "elapsed_seconds": 5.0, "status": "SUCCESS"},
                {"stage": "stock_fetch", "elapsed_seconds": 2.5, "status": "SUCCESS"},
            ],
            "provider": {
                "total_calls": 10,
                "successful_calls": 10,
                "failed_calls": 0,
                "retry_count": 0,
                "total_elapsed_seconds": 2.5,
                "average_call_seconds": 0.25,
                "calls_by_source": {"kbs": 10},
            },
            "duplicate_operations": [],
        }

        res = evaluate_performance_regression(performance_payload)
        self.assertEqual(res["overall_status"], "PASS")
        evals = {e["stage"]: e for e in res["stage_evaluations"]}

        self.assertIn("pipeline", evals)
        self.assertEqual(
            evals["pipeline"]["baseline_seconds"],
            PERFORMANCE_STAGE_BASELINES["pipeline"],
        )
        self.assertEqual(evals["pipeline"]["actual_seconds"], 5.0)
        self.assertEqual(evals["pipeline"]["exceeded_ratio"], 0.5)
        self.assertEqual(evals["pipeline"]["status"], "PASS")

        self.assertIn("stock_fetch", evals)
        self.assertEqual(
            evals["stock_fetch"]["baseline_seconds"],
            PERFORMANCE_STAGE_BASELINES["stock_fetch"],
        )
        self.assertEqual(evals["stock_fetch"]["actual_seconds"], 2.5)
        self.assertEqual(evals["stock_fetch"]["exceeded_ratio"], 0.5)
        self.assertEqual(evals["stock_fetch"]["status"], "PASS")

    def test_threshold_pass(self):
        """Verify durations within baseline thresholds produce status 'PASS'."""
        performance_payload = {
            "stages": [
                {"stage": "pipeline", "elapsed_seconds": 8.0, "status": "SUCCESS"},
                {
                    "stage": "benchmark_fetch",
                    "elapsed_seconds": 0.5,
                    "status": "SUCCESS",
                },
                {"stage": "stock_fetch", "elapsed_seconds": 4.0, "status": "SUCCESS"},
            ],
            "provider": {
                "total_calls": 10,
                "successful_calls": 10,
                "failed_calls": 0,
                "retry_count": 0,
                "total_elapsed_seconds": 4.0,
                "average_call_seconds": 0.4,
                "calls_by_source": {"kbs": 10},
            },
            "duplicate_operations": [],
        }

        res = evaluate_performance_regression(performance_payload)
        self.assertEqual(res["overall_status"], "PASS")
        for stage_eval in res["stage_evaluations"]:
            self.assertEqual(stage_eval["status"], "PASS")

    def test_threshold_degraded(self):
        """Verify duration exceeding degraded threshold but below failed threshold produces 'DEGRADED' status."""
        performance_payload = {
            "stages": [
                {
                    "stage": "benchmark_fetch",
                    "elapsed_seconds": 2.5,
                    "status": "SUCCESS",
                },
            ],
            "provider": {
                "total_calls": 1,
                "successful_calls": 1,
                "failed_calls": 0,
                "retry_count": 0,
                "total_elapsed_seconds": 2.5,
                "average_call_seconds": 2.5,
                "calls_by_source": {"kbs": 1},
            },
            "duplicate_operations": [],
        }

        res = evaluate_performance_regression(performance_payload)
        self.assertEqual(res["overall_status"], "DEGRADED")
        eval_b = res["stage_evaluations"][0]
        self.assertEqual(eval_b["stage"], "benchmark_fetch")
        self.assertEqual(eval_b["status"], "DEGRADED")
        self.assertIn("exceeded DEGRADED threshold", eval_b["message"])

    def test_stage_degraded_status_preserved(self):
        """Verify stage with execution status DEGRADED preserves status DEGRADED even with low duration."""
        performance_payload = {
            "stages": [
                {
                    "stage": "benchmark_fetch",
                    "elapsed_seconds": 0.1,  # Below degraded duration threshold
                    "status": "DEGRADED",
                },
            ],
            "provider": {
                "total_calls": 1,
                "successful_calls": 1,
                "failed_calls": 0,
                "retry_count": 0,
                "total_elapsed_seconds": 0.1,
                "average_call_seconds": 0.1,
                "calls_by_source": {"kbs": 1},
            },
            "duplicate_operations": [],
        }

        res = evaluate_performance_regression(performance_payload)
        self.assertEqual(res["overall_status"], "DEGRADED")
        eval_b = res["stage_evaluations"][0]
        self.assertEqual(eval_b["stage"], "benchmark_fetch")
        self.assertEqual(eval_b["status"], "DEGRADED")
        self.assertIn("marked DEGRADED during execution", eval_b["message"])

    def test_stage_failed_status_handling(self):
        """Verify stage with execution status FAILED produces status FAILED."""
        performance_payload = {
            "stages": [
                {
                    "stage": "stock_fetch",
                    "elapsed_seconds": 0.5,
                    "status": "FAILED",
                },
            ],
            "provider": {
                "total_calls": 1,
                "successful_calls": 0,
                "failed_calls": 1,
                "retry_count": 0,
                "total_elapsed_seconds": 0.5,
                "average_call_seconds": 0.5,
                "calls_by_source": {"kbs": 1},
            },
            "duplicate_operations": [],
        }

        res = evaluate_performance_regression(performance_payload)
        self.assertEqual(res["overall_status"], "FAILED")
        eval_s = res["stage_evaluations"][0]
        self.assertEqual(eval_s["stage"], "stock_fetch")
        self.assertEqual(eval_s["status"], "FAILED")

    def test_mixed_stages_priority_evaluation(self):
        """Verify overall status evaluates correctly according to priority: FAILED > DEGRADED > PASS."""
        performance_payload = {
            "stages": [
                {"stage": "pipeline", "elapsed_seconds": 1.0, "status": "SUCCESS"},  # PASS
                {
                    "stage": "benchmark_fetch",
                    "elapsed_seconds": 0.1,
                    "status": "DEGRADED",
                },  # DEGRADED
                {"stage": "stock_fetch", "elapsed_seconds": 0.5, "status": "FAILED"},  # FAILED
            ],
            "provider": {
                "total_calls": 2,
                "successful_calls": 1,
                "failed_calls": 1,
                "retry_count": 0,
                "total_elapsed_seconds": 1.0,
                "average_call_seconds": 0.5,
                "calls_by_source": {"kbs": 2},
            },
            "duplicate_operations": [],
        }

        res = evaluate_performance_regression(performance_payload)
        self.assertEqual(res["overall_status"], "FAILED")

        # Mixed PASS and DEGRADED without FAILED evaluates to DEGRADED
        performance_payload_deg = {
            "stages": [
                {"stage": "pipeline", "elapsed_seconds": 1.0, "status": "SUCCESS"},  # PASS
                {
                    "stage": "benchmark_fetch",
                    "elapsed_seconds": 0.1,
                    "status": "DEGRADED",
                },  # DEGRADED
            ],
            "provider": {
                "total_calls": 1,
                "successful_calls": 1,
                "failed_calls": 0,
                "retry_count": 0,
                "total_elapsed_seconds": 1.0,
                "average_call_seconds": 1.0,
                "calls_by_source": {"kbs": 1},
            },
            "duplicate_operations": [],
        }
        res_deg = evaluate_performance_regression(performance_payload_deg)
        self.assertEqual(res_deg["overall_status"], "DEGRADED")

    def test_threshold_duration_exceeded_produces_degraded(self):
        """Verify duration exceeding threshold produces status 'DEGRADED'."""
        performance_payload = {
            "stages": [
                {
                    "stage": "benchmark_fetch",
                    "elapsed_seconds": 10.0,
                    "status": "SUCCESS",
                },
            ],
            "provider": {
                "total_calls": 1,
                "successful_calls": 1,
                "failed_calls": 0,
                "retry_count": 0,
                "total_elapsed_seconds": 10.0,
                "average_call_seconds": 10.0,
                "calls_by_source": {"kbs": 1},
            },
            "duplicate_operations": [],
        }

        res = evaluate_performance_regression(performance_payload)
        self.assertEqual(res["overall_status"], "DEGRADED")
        eval_b = res["stage_evaluations"][0]
        self.assertEqual(eval_b["stage"], "benchmark_fetch")
        self.assertEqual(eval_b["status"], "DEGRADED")
        self.assertIn("exceeded FAILED threshold", eval_b["message"])

    def test_provider_budget_exceeded(self):
        """Verify provider budget checks set status DEGRADED and report violations when limits are exceeded."""
        # 1. Total calls exceeded
        payload_calls = {
            "stages": [],
            "provider": {
                "total_calls": 150,
                "successful_calls": 150,
                "failed_calls": 0,
                "retry_count": 0,
                "total_elapsed_seconds": 10.0,
                "average_call_seconds": 0.06,
                "calls_by_source": {"kbs": 150},
            },
            "duplicate_operations": [],
        }
        res_calls = evaluate_provider_budget(payload_calls)
        self.assertEqual(res_calls["overall_status"], "DEGRADED")
        self.assertTrue(any("Total provider calls" in v for v in res_calls["violations"]))

        # 2. Duplicate operations exceeded
        payload_dups = {
            "stages": [],
            "provider": {
                "total_calls": 20,
                "successful_calls": 20,
                "failed_calls": 0,
                "retry_count": 0,
                "total_elapsed_seconds": 5.0,
                "average_call_seconds": 0.25,
                "calls_by_source": {"kbs": 20},
            },
            "duplicate_operations": [
                {
                    "symbol": f"SYM_{i}",
                    "provider_call_count": 2,
                    "request_count": 2,
                    "successful_calls": 2,
                    "failed_calls": 0,
                    "retry_count": 0,
                }
                for i in range(6)
            ],
        }
        res_dups = evaluate_provider_budget(payload_dups)
        self.assertEqual(res_dups["overall_status"], "DEGRADED")
        self.assertTrue(any("Duplicate operations count" in v for v in res_dups["violations"]))

        # 3. Elapsed time exceeded
        payload_time = {
            "stages": [],
            "provider": {
                "total_calls": 10,
                "successful_calls": 10,
                "failed_calls": 0,
                "retry_count": 0,
                "total_elapsed_seconds": 75.0,
                "average_call_seconds": 7.5,
                "calls_by_source": {"kbs": 10},
            },
            "duplicate_operations": [],
        }
        res_time = evaluate_provider_budget(payload_time)
        self.assertEqual(res_time["overall_status"], "DEGRADED")
        self.assertTrue(any("Total provider elapsed time" in v for v in res_time["violations"]))

    def test_duplicate_provider_operations(self):
        """Verify duplicate provider operations are accurately detected and reported."""
        call_history = [
            {
                "provider": "vnstock",
                "source": "kbs",
                "operation": "history",
                "symbol": "FPT",
                "elapsed_seconds": 0.1,
                "success": True,
                "retry_count": 0,
            },
            {
                "provider": "vnstock",
                "source": "msn",
                "operation": "history",
                "symbol": "FPT",
                "elapsed_seconds": 0.2,
                "success": True,
                "retry_count": 0,
            },
            {
                "provider": "vnstock",
                "source": "kbs",
                "operation": "history",
                "symbol": "VCB",
                "elapsed_seconds": 0.1,
                "success": True,
                "retry_count": 0,
            },
        ]
        symbol_requests = {"FPT": 2, "VCB": 1}

        dups = detect_duplicate_operations(call_history, symbol_requests)
        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0]["symbol"], "FPT")
        self.assertEqual(dups[0]["provider_call_count"], 2)
        self.assertEqual(dups[0]["successful_calls"], 2)

    def make_sample_report_payload(self):
        return {
            "schema_version": "2.0",
            "signal_model_version": "2.0",
            "generated_at": "2026-09-17T06:00:00+00:00",
            "data_as_of": "2026-09-17",
            "source_date": "2026-09-17",
            "data_source": "REAL_DATA",
            "universe_info": {"universe_type": "TEST", "universe_size": 1},
            "market": {
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
            },
            "summary": {
                "total_scanned": 1,
                "buy_count": 1,
                "watch_count": 0,
                "hold_count": 0,
                "sell_count": 0,
                "avoid_count": 0,
            },
            "recommendations": [
                {
                    "symbol": "FPT",
                    "company_name": "FPT Corp",
                    "exchange": "HOSE",
                    "sector": "Tech",
                    "action": "BUY",
                    "data_quality": "SUFFICIENT",
                    "data_quality_issues": [],
                    "data_as_of": "2026-09-17",
                    "data_source": "REAL_DATA",
                    "signal_score": 80.0,
                    "risk_adjusted_score": 75.0,
                    "confidence": 0.8,
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
                    "reasons": ["Strong trend"],
                    "warnings": [],
                    "invalidation": ["Close below stop loss"],
                }
            ],
        }

    def test_performance_regression_degraded_allows_publishing(self):
        """Verify that stage duration exceeding threshold produces DEGRADED status (WARNING) and publishing is allowed."""
        valid_payload = self.make_sample_report_payload()
        audit_degraded = {
            "expected_symbols": ["VNINDEX", "VN30", "FPT"],
            "processed_symbols": ["VNINDEX", "VN30", "FPT"],
            "invalid_symbols": [],
            "insufficient_history_symbols": [],
            "failed_symbols": [],
            "missing_symbols": [],
            "counts": {
                "expected_count": 3,
                "processed_count": 3,
                "invalid_count": 0,
                "insufficient_history_count": 0,
                "failed_count": 0,
                "missing_count": 0,
            },
            "exclusions": [],
            "performance": {
                "stages": [
                    {"stage": "pipeline", "elapsed_seconds": 2.0, "status": "SUCCESS"},
                    {
                        "stage": "stock_fetch",
                        "elapsed_seconds": 30.0,
                        "status": "SUCCESS",
                    },  # Exceeds threshold -> DEGRADED
                ],
                "provider": {
                    "total_calls": 3,
                    "successful_calls": 3,
                    "failed_calls": 0,
                    "retry_count": 0,
                    "total_elapsed_seconds": 1.0,
                    "average_call_seconds": 0.3333,
                    "calls_by_source": {"kbs": 3},
                },
                "duplicate_operations": [],
            },
        }

        df_vnindex = make_valid_canonical_df(25, start_date="2026-08-01")
        df_vn30 = make_valid_canonical_df(25, start_date="2026-08-01")

        mock_pipeline_res = PipelineResult(
            valid_payload,
            valid_payload["market"],
            valid_payload,
            df_vnindex=df_vnindex,
            df_vn30=df_vn30,
            universe_audit=audit_degraded,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            gen_dir = Path(tmpdir) / "generated"
            gen_dir.mkdir(parents=True, exist_ok=True)
            hist_dir = gen_dir / "history"
            hist_dir.mkdir(parents=True, exist_ok=True)
            (hist_dir / "index.json").write_text(json.dumps({"dates": []}), encoding="utf-8")

            with (
                patch("scripts.generate_report.GENERATED_DIR", str(gen_dir)),
                patch(
                    "scripts.generate_report.run_pipeline", return_value=mock_pipeline_res
                ) as mock_run,
                patch("scripts.generate_report.publish_artifacts_atomically") as mock_publish,
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                generate_report_main()

            mock_run.assert_called_once_with(update_data=True, tracker=unittest.mock.ANY)
            mock_publish.assert_called_once()
            published_args = mock_publish.call_args[0][0]
            self.assertIn("monitoring.json", published_args)
            mon_data = published_args["monitoring.json"]
            self.assertEqual(mon_data["overall_status"], "WARNING")
            reg_check = next(
                c for c in mon_data["checks"] if c["check_name"] == "performance_regression"
            )
            self.assertEqual(reg_check["status"], "WARNING")

    def test_performance_stage_failed_blocks_publishing(self):
        """Verify that an explicit stage execution failure (status='FAILED') produces FAIL status and blocks publishing."""
        valid_payload = self.make_sample_report_payload()
        audit_failed = {
            "expected_symbols": ["VNINDEX", "VN30", "FPT"],
            "processed_symbols": ["VNINDEX", "VN30", "FPT"],
            "invalid_symbols": [],
            "insufficient_history_symbols": [],
            "failed_symbols": [],
            "missing_symbols": [],
            "counts": {
                "expected_count": 3,
                "processed_count": 3,
                "invalid_count": 0,
                "insufficient_history_count": 0,
                "failed_count": 0,
                "missing_count": 0,
            },
            "exclusions": [],
            "performance": {
                "stages": [
                    {"stage": "pipeline", "elapsed_seconds": 2.0, "status": "SUCCESS"},
                    {
                        "stage": "stock_fetch",
                        "elapsed_seconds": 1.0,
                        "status": "FAILED",
                    },  # Stage status FAILED
                ],
                "provider": {
                    "total_calls": 3,
                    "successful_calls": 2,
                    "failed_calls": 1,
                    "retry_count": 0,
                    "total_elapsed_seconds": 1.0,
                    "average_call_seconds": 0.3333,
                    "calls_by_source": {"kbs": 3},
                },
                "duplicate_operations": [],
            },
        }

        df_vnindex = make_valid_canonical_df(25, start_date="2026-08-01")
        df_vn30 = make_valid_canonical_df(25, start_date="2026-08-01")

        mock_pipeline_res = PipelineResult(
            valid_payload,
            valid_payload["market"],
            valid_payload,
            df_vnindex=df_vnindex,
            df_vn30=df_vn30,
            universe_audit=audit_failed,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            gen_dir = Path(tmpdir) / "generated"
            gen_dir.mkdir(parents=True, exist_ok=True)
            hist_dir = gen_dir / "history"
            hist_dir.mkdir(parents=True, exist_ok=True)

            sentinel_recs = b'{"sentinel": "recommendations_unmodified"}'
            sentinel_market = b'{"sentinel": "market_unmodified"}'
            sentinel_monitoring = b'{"sentinel": "monitoring_unmodified"}'
            sentinel_index = b'{"sentinel": "index_unmodified"}'
            sentinel_hist = b'{"sentinel": "history_2026_09_17_unmodified"}'

            recs_file = gen_dir / "recommendations.json"
            market_file = gen_dir / "market.json"
            monitoring_file = gen_dir / "monitoring.json"
            index_file = hist_dir / "index.json"
            hist_file = hist_dir / "2026-09-17.json"

            recs_file.write_bytes(sentinel_recs)
            market_file.write_bytes(sentinel_market)
            monitoring_file.write_bytes(sentinel_monitoring)
            index_file.write_bytes(sentinel_index)
            hist_file.write_bytes(sentinel_hist)

            with (
                patch("scripts.generate_report.GENERATED_DIR", str(gen_dir)),
                patch(
                    "scripts.generate_report.run_pipeline", return_value=mock_pipeline_res
                ) as mock_run,
                patch("scripts.generate_report.publish_artifacts_atomically") as mock_publish,
                patch("sys.argv", ["generate_report.py", "--update"]),
                self.assertRaises(SystemExit) as ctx,
            ):
                generate_report_main()

            self.assertEqual(ctx.exception.code, 1)
            mock_run.assert_called_once_with(update_data=True, tracker=unittest.mock.ANY)
            mock_publish.assert_not_called()

            # Verify existing artifact files on disk remain 100% byte-for-byte untouched
            self.assertEqual(recs_file.read_bytes(), sentinel_recs)
            self.assertEqual(market_file.read_bytes(), sentinel_market)
            self.assertEqual(monitoring_file.read_bytes(), sentinel_monitoring)
            self.assertEqual(index_file.read_bytes(), sentinel_index)
            self.assertEqual(hist_file.read_bytes(), sentinel_hist)

    def test_provider_budget_exceeded_allows_publishing_and_records_warning(self):
        """Verify that provider budget violations produce WARNING status and allow publishing with violation diagnostics."""
        valid_payload = self.make_sample_report_payload()
        audit_budget_exceeded = {
            "expected_symbols": ["VNINDEX", "VN30", "FPT"],
            "processed_symbols": ["VNINDEX", "VN30", "FPT"],
            "invalid_symbols": [],
            "insufficient_history_symbols": [],
            "failed_symbols": [],
            "missing_symbols": [],
            "counts": {
                "expected_count": 3,
                "processed_count": 3,
                "invalid_count": 0,
                "insufficient_history_count": 0,
                "failed_count": 0,
                "missing_count": 0,
            },
            "exclusions": [],
            "performance": {
                "stages": [
                    {"stage": "pipeline", "elapsed_seconds": 2.0, "status": "SUCCESS"},
                ],
                "provider": {
                    "total_calls": 200,  # Exceeds max_total_calls (120)
                    "successful_calls": 200,
                    "failed_calls": 0,
                    "retry_count": 0,
                    "total_elapsed_seconds": 10.0,
                    "average_call_seconds": 0.05,
                    "calls_by_source": {"kbs": 200},
                },
                "duplicate_operations": [],
            },
        }

        df_vnindex = make_valid_canonical_df(25, start_date="2026-08-01")
        df_vn30 = make_valid_canonical_df(25, start_date="2026-08-01")

        mock_pipeline_res = PipelineResult(
            valid_payload,
            valid_payload["market"],
            valid_payload,
            df_vnindex=df_vnindex,
            df_vn30=df_vn30,
            universe_audit=audit_budget_exceeded,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            gen_dir = Path(tmpdir) / "generated"
            gen_dir.mkdir(parents=True, exist_ok=True)
            hist_dir = gen_dir / "history"
            hist_dir.mkdir(parents=True, exist_ok=True)
            (hist_dir / "index.json").write_text(json.dumps({"dates": []}), encoding="utf-8")

            with (
                patch("scripts.generate_report.GENERATED_DIR", str(gen_dir)),
                patch(
                    "scripts.generate_report.run_pipeline", return_value=mock_pipeline_res
                ) as mock_run,
                patch("scripts.generate_report.publish_artifacts_atomically") as mock_publish,
                patch("sys.argv", ["generate_report.py", "--update"]),
            ):
                generate_report_main()

            mock_run.assert_called_once_with(update_data=True, tracker=unittest.mock.ANY)
            mock_publish.assert_called_once()
            published_args = mock_publish.call_args[0][0]
            self.assertIn("monitoring.json", published_args)
            mon_data = published_args["monitoring.json"]
            self.assertEqual(mon_data["overall_status"], "WARNING")
            bud_check = next(c for c in mon_data["checks"] if c["check_name"] == "provider_budget")
            self.assertEqual(bud_check["status"], "WARNING")
            self.assertIn("Total provider calls (200) exceeded budget", bud_check["message"])

    def test_deterministic_ci_regression(self):
        """Verify deterministic CI regression evaluation logic for healthy and degraded pipelines."""
        valid_payload = self.make_sample_report_payload()

        # Stage duration well within thresholds -> PASS
        healthy_audit = {
            "expected_symbols": ["VNINDEX", "VN30", "FPT"],
            "processed_symbols": ["VNINDEX", "VN30", "FPT"],
            "invalid_symbols": [],
            "insufficient_history_symbols": [],
            "failed_symbols": [],
            "missing_symbols": [],
            "counts": {
                "expected_count": 3,
                "processed_count": 3,
                "invalid_count": 0,
                "insufficient_history_count": 0,
                "failed_count": 0,
                "missing_count": 0,
            },
            "exclusions": [],
            "performance": {
                "stages": [
                    {"stage": "pipeline", "elapsed_seconds": 2.0, "status": "SUCCESS"},
                    {
                        "stage": "stock_fetch",
                        "elapsed_seconds": 1.0,
                        "status": "SUCCESS",
                    },
                ],
                "provider": {
                    "total_calls": 3,
                    "successful_calls": 3,
                    "failed_calls": 0,
                    "retry_count": 0,
                    "total_elapsed_seconds": 1.0,
                    "average_call_seconds": 0.3333,
                    "calls_by_source": {"kbs": 3},
                },
                "duplicate_operations": [],
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = Path(tmpdir) / "history"
            hist_dir.mkdir(parents=True, exist_ok=True)
            (hist_dir / "index.json").write_text(
                json.dumps({"dates": ["2026-09-17"]}), encoding="utf-8"
            )
            (hist_dir / "2026-09-17.json").write_text(json.dumps(valid_payload), encoding="utf-8")
            (Path(tmpdir) / "recommendations.json").write_text(
                json.dumps(valid_payload), encoding="utf-8"
            )
            (Path(tmpdir) / "market.json").write_text(
                json.dumps(valid_payload["market"]), encoding="utf-8"
            )

            res_pass = evaluate_production_monitoring(
                generated_dir=tmpdir,
                recommendations_payload=valid_payload,
                market_payload=valid_payload["market"],
                reference_date="2026-09-17",
                universe_audit=healthy_audit,
            )
            reg_pass_chk = next(
                c for c in res_pass.checks if c.check_name == "performance_regression"
            )
            self.assertEqual(reg_pass_chk.status, "PASS")
            self.assertIn(res_pass.overall_status, ("PASS", "WARNING"))

        # Stage duration exceeding threshold -> DEGRADED & overall_status WARNING
        regression_audit = copy.deepcopy(healthy_audit)
        regression_audit["performance"]["stages"].append(
            {"stage": "stock_fetch", "elapsed_seconds": 25.0, "status": "SUCCESS"}
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = Path(tmpdir) / "history"
            hist_dir.mkdir(parents=True, exist_ok=True)
            (hist_dir / "index.json").write_text(
                json.dumps({"dates": ["2026-09-17"]}), encoding="utf-8"
            )
            (hist_dir / "2026-09-17.json").write_text(json.dumps(valid_payload), encoding="utf-8")
            (Path(tmpdir) / "recommendations.json").write_text(
                json.dumps(valid_payload), encoding="utf-8"
            )
            (Path(tmpdir) / "market.json").write_text(
                json.dumps(valid_payload["market"]), encoding="utf-8"
            )

            res_warn = evaluate_production_monitoring(
                generated_dir=tmpdir,
                recommendations_payload=valid_payload,
                market_payload=valid_payload["market"],
                reference_date="2026-09-17",
                universe_audit=regression_audit,
            )
            self.assertEqual(res_warn.overall_status, "WARNING")
            reg_chk = next(c for c in res_warn.checks if c.check_name == "performance_regression")
            self.assertEqual(reg_chk.status, "WARNING")

    def test_malformed_and_missing_performance_data(self):
        """Verify missing or malformed performance payloads fail closed in production monitoring."""
        valid_payload = {
            "schema_version": "2.0",
            "signal_model_version": "2.0",
            "generated_at": "2026-09-17T06:00:00+00:00",
            "data_as_of": "2026-09-17",
            "source_date": "2026-09-17",
            "data_source": "REAL_DATA",
            "universe_info": {"universe_type": "TEST", "universe_size": 1},
            "market": {
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
            },
            "summary": {
                "total_scanned": 1,
                "buy_count": 1,
                "watch_count": 0,
                "hold_count": 0,
                "sell_count": 0,
                "avoid_count": 0,
            },
            "recommendations": [
                {
                    "symbol": "FPT",
                    "company_name": "FPT Corp",
                    "exchange": "HOSE",
                    "sector": "Tech",
                    "action": "BUY",
                    "data_quality": "SUFFICIENT",
                    "data_quality_issues": [],
                    "data_as_of": "2026-09-17",
                    "data_source": "REAL_DATA",
                    "signal_score": 80.0,
                    "risk_adjusted_score": 75.0,
                    "confidence": 0.8,
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
                    "reasons": ["Strong trend"],
                    "warnings": [],
                    "invalidation": ["Close below stop loss"],
                }
            ],
        }

        base_audit = {
            "expected_symbols": ["VNINDEX", "VN30", "FPT"],
            "processed_symbols": ["VNINDEX", "VN30", "FPT"],
            "invalid_symbols": [],
            "insufficient_history_symbols": [],
            "failed_symbols": [],
            "missing_symbols": [],
            "counts": {
                "expected_count": 3,
                "processed_count": 3,
                "invalid_count": 0,
                "insufficient_history_count": 0,
                "failed_count": 0,
                "missing_count": 0,
            },
            "exclusions": [],
        }

        # 1. Performance payload explicitly None
        missing_audit = copy.deepcopy(base_audit)
        missing_audit["performance"] = None

        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = Path(tmpdir) / "history"
            hist_dir.mkdir(parents=True, exist_ok=True)
            (hist_dir / "index.json").write_text(
                json.dumps({"dates": ["2026-09-17"]}), encoding="utf-8"
            )
            (hist_dir / "2026-09-17.json").write_text(json.dumps(valid_payload), encoding="utf-8")
            (Path(tmpdir) / "recommendations.json").write_text(
                json.dumps(valid_payload), encoding="utf-8"
            )
            (Path(tmpdir) / "market.json").write_text(
                json.dumps(valid_payload["market"]), encoding="utf-8"
            )

            res_missing = evaluate_production_monitoring(
                generated_dir=tmpdir,
                recommendations_payload=valid_payload,
                market_payload=valid_payload["market"],
                reference_date="2026-09-17",
                universe_audit=missing_audit,
            )
            self.assertEqual(res_missing.overall_status, "FAIL")
            integ_chk = next(
                c for c in res_missing.checks if c.check_name == "performance_payload_integrity"
            )
            self.assertEqual(integ_chk.status, "FAIL")

        # 1b. Performance key completely absent from universe_audit even if recommendations_payload contains performance
        absent_audit = copy.deepcopy(base_audit)
        self.assertNotIn("performance", absent_audit)

        payload_with_perf = copy.deepcopy(valid_payload)
        payload_with_perf["performance"] = make_valid_performance_payload()

        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = Path(tmpdir) / "history"
            hist_dir.mkdir(parents=True, exist_ok=True)
            (hist_dir / "index.json").write_text(
                json.dumps({"dates": ["2026-09-17"]}), encoding="utf-8"
            )
            (hist_dir / "2026-09-17.json").write_text(
                json.dumps(payload_with_perf), encoding="utf-8"
            )
            (Path(tmpdir) / "recommendations.json").write_text(
                json.dumps(payload_with_perf), encoding="utf-8"
            )
            (Path(tmpdir) / "market.json").write_text(
                json.dumps(payload_with_perf["market"]), encoding="utf-8"
            )

            res_absent = evaluate_production_monitoring(
                generated_dir=tmpdir,
                recommendations_payload=payload_with_perf,
                market_payload=payload_with_perf["market"],
                reference_date="2026-09-17",
                universe_audit=absent_audit,
            )
            self.assertEqual(res_absent.overall_status, "FAIL")

            checks_map = {c.check_name: c.status for c in res_absent.checks}
            self.assertEqual(checks_map.get("performance_payload_integrity"), "FAIL")
            self.assertEqual(checks_map.get("performance_regression"), "FAIL")
            self.assertEqual(checks_map.get("provider_budget"), "FAIL")

        # 2. Performance payload malformed (invalid structure)
        malformed_audit = copy.deepcopy(base_audit)
        malformed_audit["performance"] = {"stages": "not_a_list"}

        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = Path(tmpdir) / "history"
            hist_dir.mkdir(parents=True, exist_ok=True)
            (hist_dir / "index.json").write_text(
                json.dumps({"dates": ["2026-09-17"]}), encoding="utf-8"
            )
            (hist_dir / "2026-09-17.json").write_text(json.dumps(valid_payload), encoding="utf-8")
            (Path(tmpdir) / "recommendations.json").write_text(
                json.dumps(valid_payload), encoding="utf-8"
            )
            (Path(tmpdir) / "market.json").write_text(
                json.dumps(valid_payload["market"]), encoding="utf-8"
            )

            res_malformed = evaluate_production_monitoring(
                generated_dir=tmpdir,
                recommendations_payload=valid_payload,
                market_payload=valid_payload["market"],
                reference_date="2026-09-17",
                universe_audit=malformed_audit,
            )
            self.assertEqual(res_malformed.overall_status, "FAIL")
            integ_chk = next(
                c for c in res_malformed.checks if c.check_name == "performance_payload_integrity"
            )
            self.assertEqual(integ_chk.status, "FAIL")


if __name__ == "__main__":
    unittest.main()
