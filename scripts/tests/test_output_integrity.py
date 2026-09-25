"""Deterministic offline unit and regression tests for final payload & output integrity."""

import copy
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
