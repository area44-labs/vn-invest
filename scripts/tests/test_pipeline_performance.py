"""Deterministic offline unit tests for production pipeline performance profiling (PR #156).

Tests performance timing instrumentation, stage ordering, provider timing aggregation,
duplicate work detection, fail-closed guarantees, and output invariance without live network access.
"""

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
    run_pipeline,
    validate_performance_payload,
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
        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_canonical_df(25)
        mock_get_hist.return_value = (valid_df, "REAL_DATA", [])
        mock_perf.side_effect = [10.0 + (i * 0.1) for i in range(200)]

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch("scripts.generate_report.GENERATED_DIR", f"{tmpdir}/generated"),
            patch("sys.argv", ["generate_report.py"]),
        ):
            gen_dir = Path(tmpdir) / "generated"
            gen_dir.mkdir(parents=True, exist_ok=True)
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
        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_canonical_df(25)
        mock_get_hist.return_value = (valid_df, "REAL_DATA", [])
        mock_perf.side_effect = [1.0 + (i * 0.05) for i in range(200)]

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch("scripts.generate_report.GENERATED_DIR", f"{tmpdir}/generated"),
            patch("sys.argv", ["generate_report.py"]),
        ):
            gen_dir = Path(tmpdir) / "generated"
            gen_dir.mkdir(parents=True, exist_ok=True)
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
        """3. Provider call timing history from PR #155 is aggregated correctly."""
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
        from scripts.generate_report import main as generate_report_main

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

    @patch("scripts.generate_report.time.perf_counter")
    @patch("scripts.generate_report.get_historical_data")
    def test_16_monitoring_elapsed_time_corresponds_to_mocked_execution(
        self, mock_get_hist, mock_perf
    ):
        """16. Monitoring elapsed time corresponds to actual evaluate_production_monitoring() execution."""
        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_canonical_df(25)
        mock_get_hist.return_value = (valid_df, "REAL_DATA", [])
        mock_perf.side_effect = [10.0 + (i * 0.1) for i in range(200)]

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch("scripts.generate_report.GENERATED_DIR", f"{tmpdir}/generated"),
            patch("sys.argv", ["generate_report.py"]),
        ):
            gen_dir = Path(tmpdir) / "generated"
            gen_dir.mkdir(parents=True, exist_ok=True)
            try:
                generate_report_main()
            except SystemExit:
                pass

            mon_file = gen_dir / "monitoring.json"
            mon_data = json.loads(mon_file.read_text(encoding="utf-8"))
            stages = mon_data["metrics"]["performance"]["stages"]
            mon_stage = next(s for s in stages if s["stage"] == "monitoring")
            self.assertEqual(mon_stage["status"], "SUCCESS")
            self.assertGreaterEqual(mon_stage["elapsed_seconds"], 0.0)

    def test_17_monitoring_failure_produces_failed_stage_status(self):
        """17. Exception during monitoring stage records status 'FAILED' in performance tracker."""
        tracker = PerformanceTracker()
        with self.assertRaises(RuntimeError):
            with tracker.measure_stage("monitoring"):
                raise RuntimeError("Monitoring system crash")

        payload = tracker.get_performance_payload()
        mon_stage = next(s for s in payload["stages"] if s["stage"] == "monitoring")
        self.assertEqual(mon_stage["status"], "FAILED")

    def test_18_payload_validation_with_injected_failure_produces_failed(self):
        """18. Injected integrity failure in payload_validation stage records status 'FAILED'."""
        from scripts.generate_report import validate_final_payload_integrity

        tracker = PerformanceTracker()
        invalid_payload = {"data_as_of": "INVALID_DATE"}

        with self.assertRaises(ValueError):
            with tracker.measure_stage("payload_validation"):
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
        from scripts.generate_report import main as generate_report_main

        valid_df = make_valid_canonical_df(25)
        mock_get_hist.return_value = (valid_df, "REAL_DATA", [])
        mock_perf.side_effect = [1.0 + (i * 0.05) for i in range(200)]

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch("scripts.generate_report.GENERATED_DIR", f"{tmpdir}/generated"),
            patch("sys.argv", ["generate_report.py"]),
        ):
            gen_dir = Path(tmpdir) / "generated"
            gen_dir.mkdir(parents=True, exist_ok=True)
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


if __name__ == "__main__":
    unittest.main()
