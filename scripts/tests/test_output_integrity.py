"""Deterministic offline unit and regression tests for final payload & output integrity."""

import copy
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from scripts.generate_report import (
    find_payload_integrity_issues,
    load_schema,
    main,
    validate_final_payload_integrity,
)
from scripts.lib.risk import normalize_universe_liquidity_scores


class TestOutputIntegritySuite(unittest.TestCase):
    """Test suite verifying output integrity validation, fail-closed mechanics, and liquidity normalization bounds."""

    def setUp(self):
        self.schema = load_schema()
        self.valid_payload = {
            "schema_version": "2.0",
            "signal_model_version": "2.0",
            "generated_at": "2026-09-25T14:00:00Z",
            "data_as_of": "2026-09-25",
            "source_date": "2026-09-25",
            "data_source": "kbs",
            "universe_info": {
                "universe_type": "MANDATORY_AND_CANDIDATES",
                "universe_size": 2,
            },
            "market": {
                "regime": "DEFENSIVE",
                "confidence": 0.85,
                "regime_score": 55.0,
                "metrics": {
                    "vnindex_value": 1250.5,
                    "vnindex_change_pct": 0.5,
                    "vn30_change_pct": 0.4,
                    "market_breadth_ratio": 0.6,
                    "volatility": 0.15,
                    "volume_20d_ratio": 1.1,
                },
            },
            "summary": {
                "total_scanned": 2,
                "buy_count": 1,
                "watch_count": 0,
                "hold_count": 0,
                "sell_count": 0,
                "avoid_count": 1,
            },
            "recommendations": [
                {
                    "symbol": "FPT",
                    "company_name": "FPT Corp",
                    "exchange": "HOSE",
                    "sector": "Technology",
                    "action": "BUY",
                    "model_version": "2.0",
                    "data_quality": "SUFFICIENT",
                    "data_quality_issues": [],
                    "data_as_of": "2026-09-25",
                    "data_source": "kbs",
                    "signal_score": 78.5,
                    "risk_adjusted_score": 75.0,
                    "confidence": 0.8,
                    "risk_level": "LOW",
                    "expected_return": {
                        "expected_return_5d": 1.2,
                        "expected_return_10d": 2.5,
                        "expected_return_20d": 4.0,
                    },
                    "risk_metrics": {
                        "var_t25": -0.02,
                        "es_t25": -0.03,
                        "volatility_60d": 0.18,
                        "max_drawdown": -0.05,
                        "liquidity_score": 85.0,
                        "avg_value_20d": 50.0,
                    },
                    "trade_plan": {
                        "current_price": 130000.0,
                        "entry_low": 128000.0,
                        "entry_high": 131000.0,
                        "stop_loss": 122000.0,
                        "tp1": 138000.0,
                        "tp2": 145000.0,
                        "risk_reward": 2.1,
                        "position_percent": 15.0,
                    },
                    "reasons": ["Strong trend"],
                    "warnings": [],
                    "invalidation": ["Close below stop loss"],
                },
                {
                    "symbol": "VIC",
                    "company_name": "Vingroup",
                    "exchange": "HOSE",
                    "sector": "Real Estate",
                    "action": "AVOID",
                    "model_version": "2.0",
                    "data_quality": "INSUFFICIENT",
                    "data_quality_issues": ["Insufficient history"],
                    "data_as_of": "2026-09-25",
                    "data_source": "kbs",
                    "signal_score": None,
                    "risk_adjusted_score": None,
                    "confidence": 0.1,
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
                        "position_percent": 0.0,
                    },
                    "reasons": ["Insufficient data"],
                    "warnings": ["Data missing"],
                    "invalidation": ["Need data"],
                },
            ],
        }

    def test_valid_payload_passes_integrity_validation(self):
        """Verify clean, schema-compliant valid payload passes integrity check with 0 issues."""
        issues = find_payload_integrity_issues(self.valid_payload, self.schema)
        self.assertEqual(issues, [])
        validate_final_payload_integrity(self.valid_payload, self.schema)

    def test_nan_inf_detection(self):
        """Verify float NaN, Inf, -Inf values anywhere in payload are detected."""
        payload_nan = copy.deepcopy(self.valid_payload)
        payload_nan["recommendations"][0]["risk_metrics"]["volatility_60d"] = float("nan")
        issues = find_payload_integrity_issues(payload_nan, self.schema)
        self.assertTrue(any("NaN" in iss for iss in issues))
        with self.assertRaises(ValueError):
            validate_final_payload_integrity(payload_nan, self.schema)

        payload_inf = copy.deepcopy(self.valid_payload)
        payload_inf["recommendations"][0]["trade_plan"]["risk_reward"] = float("inf")
        issues = find_payload_integrity_issues(payload_inf, self.schema)
        self.assertTrue(any("Infinity" in iss for iss in issues))
        with self.assertRaises(ValueError):
            validate_final_payload_integrity(payload_inf, self.schema)

        payload_str_nan = copy.deepcopy(self.valid_payload)
        payload_str_nan["recommendations"][0]["reasons"][0] = "NaN"
        issues = find_payload_integrity_issues(payload_str_nan, self.schema)
        self.assertTrue(any("Invalid numeric string representation" in iss for iss in issues))

    def test_non_serializable_numpy_pandas_scalars(self):
        """Verify non-native numpy/pandas scalar objects in payload are detected."""
        payload_np = copy.deepcopy(self.valid_payload)
        payload_np["recommendations"][0]["risk_metrics"]["volatility_60d"] = np.float64(0.18)
        issues = find_payload_integrity_issues(payload_np, self.schema)
        self.assertTrue(any("Non-serializable float64" in iss for iss in issues))

    def test_summary_mismatch_detection(self):
        """Verify summary action count mismatches are caught."""
        payload_mismatch = copy.deepcopy(self.valid_payload)
        payload_mismatch["summary"]["buy_count"] = 5  # Actual is 1
        issues = find_payload_integrity_issues(payload_mismatch, self.schema)
        self.assertTrue(any("Summary mismatch for 'buy_count'" in iss for iss in issues))

    def test_score_and_metric_out_of_range(self):
        """Verify score and metric range violations are caught."""
        payload_out = copy.deepcopy(self.valid_payload)
        payload_out["recommendations"][0]["signal_score"] = 150.0  # > 100
        issues = find_payload_integrity_issues(payload_out, self.schema)
        self.assertTrue(any("out of range" in iss for iss in issues))

        payload_conf = copy.deepcopy(self.valid_payload)
        payload_conf["recommendations"][0]["confidence"] = 1.5  # > 1.0
        issues = find_payload_integrity_issues(payload_conf, self.schema)
        self.assertTrue(any("out of range" in iss for iss in issues))

    def test_required_fields_none_and_schema_validation(self):
        """Verify mandatory schema fields set to None fail integrity validation."""
        payload_null = copy.deepcopy(self.valid_payload)
        payload_null["recommendations"][0]["action"] = None
        issues = find_payload_integrity_issues(payload_null, self.schema)
        self.assertTrue(len(issues) > 0)
        with self.assertRaises(ValueError):
            validate_final_payload_integrity(payload_null, self.schema)

    def test_insufficient_data_quality_invariants(self):
        """Verify symbol with INSUFFICIENT data quality having non-null score fails validation."""
        payload_inv = copy.deepcopy(self.valid_payload)
        # VIC has data_quality INSUFFICIENT
        payload_inv["recommendations"][1]["signal_score"] = 50.0
        issues = find_payload_integrity_issues(payload_inv, self.schema)
        self.assertTrue(
            any("INSUFFICIENT data quality has non-null signal_score" in iss for iss in issues)
        )

    def test_liquidity_normalization_excludes_insufficient(self):
        """Verify normalize_universe_liquidity_scores excludes INSUFFICIENT symbols from denominator."""
        recs = [
            {
                "symbol": "FPT",
                "data_quality": "SUFFICIENT",
                "signal_score": 70.0,
                "risk_metrics": {"avg_value_20d": 100.0, "liquidity_score": None},
                "risk_adjusted_score": None,
            },
            {
                "symbol": "VNM",
                "data_quality": "SUFFICIENT",
                "signal_score": 60.0,
                "risk_metrics": {"avg_value_20d": 50.0, "liquidity_score": None},
                "risk_adjusted_score": None,
            },
            {
                "symbol": "EXCLUDED",
                "data_quality": "INSUFFICIENT",
                "signal_score": None,
                "risk_metrics": {
                    "avg_value_20d": 500.0,
                    "liquidity_score": None,
                },  # Large avg_value_20d
                "risk_adjusted_score": None,
            },
        ]

        normalized = normalize_universe_liquidity_scores(recs, market_regime="BULL")
        # FPT (100) vs VNM (50) -> FPT percentile rank = 100.0, VNM percentile rank = 50.0
        fpt_rec = next(r for r in normalized if r["symbol"] == "FPT")
        vnm_rec = next(r for r in normalized if r["symbol"] == "VNM")
        ex_rec = next(r for r in normalized if r["symbol"] == "EXCLUDED")

        self.assertEqual(fpt_rec["risk_metrics"]["liquidity_score"], 100.0)
        self.assertEqual(vnm_rec["risk_metrics"]["liquidity_score"], 50.0)
        # EXCLUDED symbol must remain None and not affect rank
        self.assertIsNone(ex_rec["risk_metrics"]["liquidity_score"])
        self.assertIsNone(ex_rec["risk_adjusted_score"])

    def test_artifact_preservation_on_validation_failure(self):
        """Verify that if validation fails in main(), SystemExit(1) is raised and existing artifacts are preserved."""
        temp_dir = tempfile.mkdtemp()
        try:
            gen_dir = os.path.join(temp_dir, "generated")
            os.makedirs(gen_dir, exist_ok=True)
            recs_file = os.path.join(gen_dir, "recommendations.json")
            original_content = '{"existing": "data"}\n'
            with open(recs_file, "w", encoding="utf-8") as f:
                f.write(original_content)

            # Mock pipeline to return invalid payload with NaN
            invalid_payload = copy.deepcopy(self.valid_payload)
            invalid_payload["recommendations"][0]["risk_metrics"]["volatility_60d"] = float("nan")

            class MockPipelineRes(tuple):
                def __new__(cls, r, m, h):
                    obj = super().__new__(cls, (r, m, h))
                    obj.df_vnindex = None
                    obj.df_vn30 = None
                    return obj

            mock_res = MockPipelineRes(
                invalid_payload, invalid_payload.get("market"), invalid_payload
            )

            with (
                patch("scripts.generate_report.GENERATED_DIR", gen_dir),
                patch("scripts.generate_report.run_pipeline", return_value=mock_res),
                patch("sys.argv", ["generate_report.py"]),
            ):
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 1)

            # Ensure existing file was preserved and not overwritten by invalid pipeline output
            with open(recs_file, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertEqual(content, original_content)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_all_artifacts_preserved_when_monitoring_validation_fails(self):
        """Regression test for PR #143: Ensure no files are written/modified if monitoring validation fails."""
        temp_dir = tempfile.mkdtemp()
        try:
            gen_dir = os.path.join(temp_dir, "generated")
            hist_dir = os.path.join(gen_dir, "history")
            os.makedirs(hist_dir, exist_ok=True)

            recs_file = os.path.join(gen_dir, "recommendations.json")
            mkt_file = os.path.join(gen_dir, "market.json")
            mon_file = os.path.join(gen_dir, "monitoring.json")
            hist_file = os.path.join(hist_dir, "2026-09-25.json")
            idx_file = os.path.join(hist_dir, "index.json")

            original_contents = {
                recs_file: '{"existing_recs": true}\n',
                mkt_file: '{"existing_mkt": true}\n',
                mon_file: '{"existing_mon": true}\n',
                hist_file: '{"existing_hist": true}\n',
                idx_file: '{"existing_idx": true}\n',
            }

            for filepath, content in original_contents.items():
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(content)

            valid_p = copy.deepcopy(self.valid_payload)

            class MockPipelineRes(tuple):
                def __new__(cls, r, m, h):
                    obj = super().__new__(cls, (r, m, h))
                    obj.df_vnindex = None
                    obj.df_vn30 = None
                    return obj

            mock_res = MockPipelineRes(valid_p, valid_p.get("market"), valid_p)

            # Mock monitoring to return invalid dict containing NaN
            mock_mon_res = MagicMock()
            mock_mon_res.overall_status = "FAIL"
            mock_mon_res.to_dict.return_value = {
                "overall_status": "FAIL",
                "nan_metric": float("nan"),
            }

            with (
                patch("scripts.generate_report.GENERATED_DIR", gen_dir),
                patch("scripts.generate_report.run_pipeline", return_value=mock_res),
                patch(
                    "scripts.generate_report.evaluate_production_monitoring",
                    return_value=mock_mon_res,
                ),
                patch("sys.argv", ["generate_report.py"]),
            ):
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 1)

            # Verify every pre-existing artifact remains byte-for-byte unchanged
            for filepath, expected_content in original_contents.items():
                with open(filepath, "r", encoding="utf-8") as f:
                    actual_content = f.read()
                self.assertEqual(
                    actual_content,
                    expected_content,
                    f"File '{filepath}' was modified when monitoring validation failed!",
                )

            # Verify no partial or temporary files exist in gen_dir or hist_dir
            for root, _, files in os.walk(gen_dir):
                for file in files:
                    full_p = os.path.join(root, file)
                    self.assertIn(
                        full_p,
                        original_contents,
                        f"Unexpected file created during failed validation: '{full_p}'",
                    )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_atomic_publish_success_publishes_all_artifacts_together(self):
        """Verify that a successful pipeline run atomically publishes all expected output artifacts together."""
        temp_dir = tempfile.mkdtemp()
        try:
            gen_dir = os.path.join(temp_dir, "generated")
            os.makedirs(gen_dir, exist_ok=True)

            valid_p = copy.deepcopy(self.valid_payload)

            class MockPipelineRes(tuple):
                def __new__(cls, r, m, h):
                    obj = super().__new__(cls, (r, m, h))
                    obj.df_vnindex = None
                    obj.df_vn30 = None
                    return obj

            mock_res = MockPipelineRes(valid_p, valid_p.get("market"), valid_p)

            mock_mon_res = MagicMock()
            mock_mon_res.overall_status = "PASS"
            mock_mon_res.to_dict.return_value = {
                "overall_status": "PASS",
                "generated_at": "2026-09-25T14:00:00Z",
                "data_as_of": "2026-09-25",
                "checks": [],
                "metrics": {},
            }

            with (
                patch("scripts.generate_report.GENERATED_DIR", gen_dir),
                patch("scripts.generate_report.run_pipeline", return_value=mock_res),
                patch(
                    "scripts.generate_report.evaluate_production_monitoring",
                    return_value=mock_mon_res,
                ),
                patch("sys.argv", ["generate_report.py"]),
            ):
                main()

            # Verify all expected production artifacts exist
            expected_artifacts = [
                os.path.join(gen_dir, "recommendations.json"),
                os.path.join(gen_dir, "market.json"),
                os.path.join(gen_dir, "monitoring.json"),
                os.path.join(gen_dir, "history", "2026-09-25.json"),
                os.path.join(gen_dir, "history", "index.json"),
            ]
            for p in expected_artifacts:
                self.assertTrue(os.path.exists(p), f"Expected published artifact missing: '{p}'")

            # Verify no leftover .tmp files
            for root, _, files in os.walk(gen_dir):
                for f in files:
                    self.assertFalse(f.endswith(".tmp"), f"Leftover temporary file found: {f}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_failure_during_publish_preserves_existing_artifacts_and_cleans_up_tmp(self):
        """Verify failure during commit phase AFTER at least one artifact replacement succeeds triggers rollback, leaving ALL existing artifacts byte-for-byte unchanged."""
        temp_dir = tempfile.mkdtemp()
        try:
            gen_dir = os.path.join(temp_dir, "generated")
            hist_dir = os.path.join(gen_dir, "history")
            os.makedirs(hist_dir, exist_ok=True)

            recs_file = os.path.join(gen_dir, "recommendations.json")
            mkt_file = os.path.join(gen_dir, "market.json")
            mon_file = os.path.join(gen_dir, "monitoring.json")
            hist_file = os.path.join(hist_dir, "2026-09-25.json")
            idx_file = os.path.join(hist_dir, "index.json")

            original_contents = {
                recs_file: '{"existing_recs": "v1"}\n',
                mkt_file: '{"existing_mkt": "v1"}\n',
                mon_file: '{"existing_mon": "v1"}\n',
                hist_file: '{"existing_hist": "v1"}\n',
                idx_file: json.dumps({"dates": ["2026-09-24"], "total_reports": 1}) + "\n",
            }
            for path, content in original_contents.items():
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)

            valid_p = copy.deepcopy(self.valid_payload)

            class MockPipelineRes(tuple):
                def __new__(cls, r, m, h):
                    obj = super().__new__(cls, (r, m, h))
                    obj.df_vnindex = None
                    obj.df_vn30 = None
                    return obj

            mock_res = MockPipelineRes(valid_p, valid_p.get("market"), valid_p)

            mock_mon_res = MagicMock()
            mock_mon_res.overall_status = "PASS"
            mock_mon_res.to_dict.return_value = {
                "overall_status": "PASS",
                "generated_at": "2026-09-25T14:00:00Z",
                "data_as_of": "2026-09-25",
                "checks": [],
                "metrics": {},
            }

            real_os_replace = os.replace
            replace_count = 0

            def failing_os_replace(src, dst):
                nonlocal replace_count
                replace_count += 1
                if replace_count == 2:  # Fail on second replace call AFTER first replace succeeded
                    raise OSError("Disk failure on second artifact replacement")
                return real_os_replace(src, dst)

            with (
                patch("scripts.generate_report.GENERATED_DIR", gen_dir),
                patch("scripts.generate_report.run_pipeline", return_value=mock_res),
                patch(
                    "scripts.generate_report.evaluate_production_monitoring",
                    return_value=mock_mon_res,
                ),
                patch("os.replace", side_effect=failing_os_replace),
                patch("sys.argv", ["generate_report.py"]),
                self.assertRaises(OSError),
            ):
                main()

            # Prove that replace #1 succeeded before replace #2 failed
            self.assertGreaterEqual(replace_count, 2)

            # Verify ALL existing files are restored byte-for-byte unchanged (no mixed old/new artifacts)
            for path, expected in original_contents.items():
                with open(path, "r", encoding="utf-8") as f:
                    self.assertEqual(
                        f.read(),
                        expected,
                        f"Artifact '{path}' was modified after mid-commit rollback failure!",
                    )

            # Verify no temporary or backup files remain in gen_dir
            for root, _, files in os.walk(gen_dir):
                for f in files:
                    self.assertFalse(f.endswith(".tmp"), f"Leftover temp file: {f}")
                    self.assertFalse(f.endswith(".bak"), f"Leftover backup file: {f}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_successful_retry_after_previous_failure(self):
        """Verify that after a failure leaves artifacts unchanged, a subsequent valid run completes and publishes all new artifacts."""
        temp_dir = tempfile.mkdtemp()
        try:
            gen_dir = os.path.join(temp_dir, "generated")
            hist_dir = os.path.join(gen_dir, "history")
            os.makedirs(hist_dir, exist_ok=True)

            recs_file = os.path.join(gen_dir, "recommendations.json")
            mkt_file = os.path.join(gen_dir, "market.json")
            mon_file = os.path.join(gen_dir, "monitoring.json")
            hist_file = os.path.join(hist_dir, "2026-09-25.json")
            idx_file = os.path.join(hist_dir, "index.json")

            original_contents = {
                recs_file: '{"v": 1}\n',
                mkt_file: '{"v": 1}\n',
                mon_file: '{"v": 1}\n',
                hist_file: '{"v": 1}\n',
                idx_file: json.dumps({"dates": ["2026-09-24"], "total_reports": 1}) + "\n",
            }
            for path, content in original_contents.items():
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)

            # 1. Attempt run that fails in pipeline
            with (
                patch("scripts.generate_report.GENERATED_DIR", gen_dir),
                patch(
                    "scripts.generate_report.run_pipeline",
                    side_effect=RuntimeError("Pipeline failed"),
                ),
                patch("sys.argv", ["generate_report.py"]),
                self.assertRaises(SystemExit) as cm,
            ):
                main()
            self.assertEqual(cm.exception.code, 1)

            # Verify artifacts remain unchanged after failure
            for path, expected in original_contents.items():
                with open(path, "r", encoding="utf-8") as f:
                    self.assertEqual(f.read(), expected)

            # 2. Retry with valid pipeline output
            valid_p = copy.deepcopy(self.valid_payload)

            class MockPipelineRes(tuple):
                def __new__(cls, r, m, h):
                    obj = super().__new__(cls, (r, m, h))
                    obj.df_vnindex = None
                    obj.df_vn30 = None
                    return obj

            mock_res = MockPipelineRes(valid_p, valid_p.get("market"), valid_p)

            mock_mon_res = MagicMock()
            mock_mon_res.overall_status = "PASS"
            mock_mon_res.to_dict.return_value = {
                "overall_status": "PASS",
                "generated_at": "2026-09-25T14:00:00Z",
                "data_as_of": "2026-09-25",
                "checks": [],
                "metrics": {},
            }

            with (
                patch("scripts.generate_report.GENERATED_DIR", gen_dir),
                patch("scripts.generate_report.run_pipeline", return_value=mock_res),
                patch(
                    "scripts.generate_report.evaluate_production_monitoring",
                    return_value=mock_mon_res,
                ),
                patch("sys.argv", ["generate_report.py"]),
            ):
                main()

            # Verify all artifacts updated to v2 payload
            with open(recs_file, "r", encoding="utf-8") as f:
                recs_data = json.load(f)
            self.assertEqual(recs_data["schema_version"], "2.0")
            self.assertEqual(recs_data["data_as_of"], "2026-09-25")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
