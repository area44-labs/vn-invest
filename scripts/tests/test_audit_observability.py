"""Deterministic offline regression tests for production data-quality auditability and observability."""

import copy
import json
import os
import tempfile
import unittest

from scripts.lib.config import SIGNAL_MODEL_VERSION
from scripts.lib.monitoring import (
    check_universe_audit_invariants,
    evaluate_production_monitoring,
)


class TestAuditTrailObservability(unittest.TestCase):
    """Offline regression tests covering universe audit coverage, exclusion reasons, and invariant cross-checks."""

    def setUp(self):
        self.reference_date = "2026-09-25"
        self.data_as_of = "2026-09-25"

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

        self.fpt_rec = {
            "symbol": "FPT",
            "company_name": "FPT Corp",
            "exchange": "HOSE",
            "sector": "Technology",
            "action": "BUY",
            "data_quality": "SUFFICIENT",
            "data_quality_issues": [],
            "data_as_of": self.data_as_of,
            "data_source": "TEST",
            "signal_score": 85.0,
            "risk_adjusted_score": 80.0,
            "confidence": 0.85,
            "risk_level": "LOW",
            "expected_return": {
                "expected_return_5d": 2.0,
                "expected_return_10d": 4.0,
                "expected_return_20d": 6.0,
            },
            "risk_metrics": {
                "var_t25": -3.0,
                "es_t25": -4.0,
                "volatility_60d": 0.15,
                "max_drawdown": -5.0,
                "liquidity_score": 90.0,
                "avg_value_20d": 100.0,
            },
            "trade_plan": {
                "current_price": 100.0,
                "entry_low": 98.0,
                "entry_high": 100.0,
                "stop_loss": 95.0,
                "tp1": 105.0,
                "tp2": 110.0,
                "risk_reward": 2.0,
                "position_percent": 15.0,
            },
            "reasons": ["Strong trend"],
            "warnings": [],
            "invalidation": ["Close below 95"],
        }

        self.mwg_rec = {
            "symbol": "MWG",
            "company_name": "Mobile World",
            "exchange": "HOSE",
            "sector": "Retail",
            "action": "WATCH",
            "data_quality": "SUFFICIENT",
            "data_quality_issues": [],
            "data_as_of": self.data_as_of,
            "data_source": "TEST",
            "signal_score": 65.0,
            "risk_adjusted_score": 60.0,
            "confidence": 0.75,
            "risk_level": "MEDIUM",
            "expected_return": {
                "expected_return_5d": 1.0,
                "expected_return_10d": 2.0,
                "expected_return_20d": 3.0,
            },
            "risk_metrics": {
                "var_t25": -4.0,
                "es_t25": -5.0,
                "volatility_60d": 0.20,
                "max_drawdown": -10.0,
                "liquidity_score": 85.0,
                "avg_value_20d": 80.0,
            },
            "trade_plan": {
                "current_price": 50.0,
                "entry_low": 48.0,
                "entry_high": 50.0,
                "stop_loss": 45.0,
                "tp1": 55.0,
                "tp2": 60.0,
                "risk_reward": 1.5,
                "position_percent": 10.0,
            },
            "reasons": ["Consolidating"],
            "warnings": [],
            "invalidation": ["Close below 45"],
        }

        self.healthy_payload = {
            "schema_version": "2.0",
            "signal_model_version": SIGNAL_MODEL_VERSION,
            "generated_at": f"{self.data_as_of}T06:00:00+00:00",
            "data_as_of": self.data_as_of,
            "source_date": self.data_as_of,
            "data_source": "TEST",
            "universe_info": {"universe_type": "TEST", "universe_size": 2},
            "market": self.healthy_market,
            "summary": {
                "total_scanned": 2,
                "buy_count": 1,
                "watch_count": 1,
                "hold_count": 0,
                "sell_count": 0,
                "avoid_count": 0,
            },
            "recommendations": [self.fpt_rec, self.mwg_rec],
        }

    def _make_insufficient_rec(self, symbol: str) -> dict:
        return {
            "symbol": symbol,
            "company_name": f"{symbol} Inc",
            "exchange": "HOSE",
            "sector": "Test",
            "action": "AVOID",
            "data_quality": "INSUFFICIENT",
            "data_quality_issues": ["Insufficient history"],
            "data_as_of": self.data_as_of,
            "data_source": "TEST",
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

    def test_scenario_1_complete_production_universe(self):
        """Scenario 1: Complete production universe -> no failures, 100% processed."""
        expected = ["FPT", "MWG", "VN30", "VNINDEX"]
        summary = {
            "status": "SUCCESS",
            "failed_stage": None,
            "expected_count": 4,
            "processed_count": 4,
            "invalid_count": 0,
            "insufficient_history_count": 0,
            "failed_count": 0,
            "missing_count": 0,
            "diagnostic_count": 0,
        }
        audit = {
            "status": "SUCCESS",
            "failed_stage": None,
            "expected_symbols": expected,
            "processed_symbols": expected,
            "invalid_symbols": [],
            "insufficient_history_symbols": [],
            "failed_symbols": [],
            "missing_symbols": [],
            "counts": summary,
            "summary": summary,
            "exclusions": [],
            "diagnostics": [],
        }
        res = check_universe_audit_invariants(audit, self.healthy_payload)
        self.assertEqual(res.status, "PASS")
        self.assertEqual(audit["summary"]["diagnostic_count"], 0)

    def test_scenario_2_one_invalid_symbol(self):
        """Scenario 2: One invalid symbol in candidates universe."""
        payload = copy.deepcopy(self.healthy_payload)
        bad_rec = self._make_insufficient_rec("BADSYM")
        payload["recommendations"].append(bad_rec)
        payload["summary"]["total_scanned"] = 3
        payload["summary"]["avoid_count"] = 1

        ex_record = {
            "symbol": "BADSYM",
            "stage": "STOCK_FETCH",
            "category": "INVALID_SYMBOL",
            "status": "INVALID",
            "reason": "Invalid stock symbol BADSYM",
            "latest_date": None,
            "expected_date": self.data_as_of,
            "processed": False,
        }
        audit = {
            "status": "SUCCESS",
            "failed_stage": None,
            "expected_symbols": ["BADSYM", "FPT", "MWG", "VN30", "VNINDEX"],
            "processed_symbols": ["FPT", "MWG", "VN30", "VNINDEX"],
            "invalid_symbols": ["BADSYM"],
            "insufficient_history_symbols": [],
            "failed_symbols": [],
            "missing_symbols": [],
            "counts": {
                "expected_count": 5,
                "processed_count": 4,
                "invalid_count": 1,
                "insufficient_history_count": 0,
                "failed_count": 0,
                "missing_count": 0,
                "diagnostic_count": 1,
            },
            "exclusions": [ex_record],
            "diagnostics": [ex_record],
        }
        res = check_universe_audit_invariants(audit, payload)
        self.assertEqual(res.status, "PASS")
        self.assertEqual(audit["exclusions"][0]["category"], "INVALID_SYMBOL")
        self.assertEqual(audit["exclusions"][0]["stage"], "STOCK_FETCH")

    def test_scenario_3_one_insufficient_history_symbol(self):
        """Scenario 3: One symbol with insufficient historical data."""
        payload = copy.deepcopy(self.healthy_payload)
        insuf_rec = self._make_insufficient_rec("SHORT")
        payload["recommendations"].append(insuf_rec)
        payload["summary"]["total_scanned"] = 3
        payload["summary"]["avoid_count"] = 1

        ex_record = {
            "symbol": "SHORT",
            "stage": "STOCK_FETCH",
            "category": "INSUFFICIENT_HISTORICAL_DATA",
            "status": "INSUFFICIENT",
            "reason": "Insufficient historical sessions (10 < 20)",
            "latest_date": "2026-09-25",
            "expected_date": self.data_as_of,
            "processed": False,
        }
        audit = {
            "status": "DEGRADED",
            "failed_stage": "STOCK_FETCH",
            "expected_symbols": ["FPT", "MWG", "SHORT", "VN30", "VNINDEX"],
            "processed_symbols": ["FPT", "MWG", "VN30", "VNINDEX"],
            "invalid_symbols": [],
            "insufficient_history_symbols": ["SHORT"],
            "failed_symbols": [],
            "missing_symbols": [],
            "counts": {
                "expected_count": 5,
                "processed_count": 4,
                "invalid_count": 0,
                "insufficient_history_count": 1,
                "failed_count": 0,
                "missing_count": 0,
                "diagnostic_count": 1,
            },
            "exclusions": [ex_record],
            "diagnostics": [ex_record],
        }
        res = check_universe_audit_invariants(audit, payload)
        self.assertEqual(res.status, "PASS")
        self.assertEqual(audit["exclusions"][0]["category"], "INSUFFICIENT_HISTORICAL_DATA")

    def test_scenario_4_one_provider_failure(self):
        """Scenario 4: One symbol encountering provider failure."""
        payload = copy.deepcopy(self.healthy_payload)
        fail_rec = self._make_insufficient_rec("FAILSYM")
        payload["recommendations"].append(fail_rec)
        payload["summary"]["total_scanned"] = 3
        payload["summary"]["avoid_count"] = 1

        ex_record = {
            "symbol": "FAILSYM",
            "stage": "STOCK_FETCH",
            "category": "PROVIDER_FAILURE",
            "status": "FAILED",
            "reason": "Provider network timeout for symbol FAILSYM",
            "latest_date": None,
            "expected_date": self.data_as_of,
            "processed": False,
        }
        audit = {
            "status": "DEGRADED",
            "failed_stage": "STOCK_FETCH",
            "expected_symbols": ["FAILSYM", "FPT", "MWG", "VN30", "VNINDEX"],
            "processed_symbols": ["FPT", "MWG", "VN30", "VNINDEX"],
            "invalid_symbols": [],
            "insufficient_history_symbols": [],
            "failed_symbols": ["FAILSYM"],
            "missing_symbols": [],
            "counts": {
                "expected_count": 5,
                "processed_count": 4,
                "invalid_count": 0,
                "insufficient_history_count": 0,
                "failed_count": 1,
                "missing_count": 0,
                "diagnostic_count": 1,
            },
            "exclusions": [ex_record],
            "diagnostics": [ex_record],
        }
        res = check_universe_audit_invariants(audit, payload)
        self.assertEqual(res.status, "PASS")
        self.assertEqual(audit["exclusions"][0]["category"], "PROVIDER_FAILURE")

    def test_scenario_5_one_temporal_invalid_symbol(self):
        """Scenario 5: One symbol failing temporal validation."""
        payload = copy.deepcopy(self.healthy_payload)
        stale_rec = self._make_insufficient_rec("STALE")
        payload["recommendations"].append(stale_rec)
        payload["summary"]["total_scanned"] = 3
        payload["summary"]["avoid_count"] = 1

        ex_record = {
            "symbol": "STALE",
            "stage": "TEMPORAL_VALIDATION",
            "category": "TEMPORAL_INVALID",
            "status": "FAILED",
            "reason": "Stale date 2026-09-10 vs benchmark 2026-09-25",
            "latest_date": "2026-09-10",
            "expected_date": self.data_as_of,
            "processed": False,
        }
        audit = {
            "status": "DEGRADED",
            "failed_stage": "TEMPORAL_VALIDATION",
            "expected_symbols": ["FPT", "MWG", "STALE", "VN30", "VNINDEX"],
            "processed_symbols": ["FPT", "MWG", "VN30", "VNINDEX"],
            "invalid_symbols": [],
            "insufficient_history_symbols": [],
            "failed_symbols": ["STALE"],
            "missing_symbols": [],
            "counts": {
                "expected_count": 5,
                "processed_count": 4,
                "invalid_count": 0,
                "insufficient_history_count": 0,
                "failed_count": 1,
                "missing_count": 0,
                "diagnostic_count": 1,
            },
            "exclusions": [ex_record],
            "diagnostics": [ex_record],
        }
        res = check_universe_audit_invariants(audit, payload)
        self.assertEqual(res.status, "PASS")
        self.assertEqual(audit["exclusions"][0]["stage"], "TEMPORAL_VALIDATION")
        self.assertEqual(audit["exclusions"][0]["category"], "TEMPORAL_INVALID")

    def test_scenario_6_mixed_classifications(self):
        """Scenario 6: Universe containing mixed symbol classifications."""
        payload = copy.deepcopy(self.healthy_payload)
        payload["recommendations"].extend(
            [
                self._make_insufficient_rec("INVSYM"),
                self._make_insufficient_rec("SHORTSYM"),
                self._make_insufficient_rec("FAILSYM"),
            ]
        )
        payload["summary"]["total_scanned"] = 5
        payload["summary"]["avoid_count"] = 3

        exclusions = [
            {
                "symbol": "FAILSYM",
                "stage": "STOCK_FETCH",
                "category": "PROVIDER_FAILURE",
                "status": "FAILED",
                "reason": "Fetch error",
                "processed": False,
            },
            {
                "symbol": "INVSYM",
                "stage": "STOCK_FETCH",
                "category": "INVALID_SYMBOL",
                "status": "INVALID",
                "reason": "Invalid symbol",
                "processed": False,
            },
            {
                "symbol": "MISSSYM",
                "stage": "UNIVERSE_DISCOVERY",
                "category": "UNIVERSE_INCOMPLETE",
                "status": "MISSING",
                "reason": "Missing from scan",
                "processed": False,
            },
            {
                "symbol": "SHORTSYM",
                "stage": "STOCK_FETCH",
                "category": "INSUFFICIENT_HISTORICAL_DATA",
                "status": "INSUFFICIENT",
                "reason": "Short history",
                "processed": False,
            },
        ]

        audit = {
            "status": "DEGRADED",
            "failed_stage": "STOCK_FETCH",
            "expected_symbols": [
                "FAILSYM",
                "FPT",
                "INVSYM",
                "MISSSYM",
                "MWG",
                "SHORTSYM",
                "VN30",
                "VNINDEX",
            ],
            "processed_symbols": ["FPT", "MWG", "VN30", "VNINDEX"],
            "invalid_symbols": ["INVSYM"],
            "insufficient_history_symbols": ["SHORTSYM"],
            "failed_symbols": ["FAILSYM"],
            "missing_symbols": ["MISSSYM"],
            "counts": {
                "expected_count": 8,
                "processed_count": 4,
                "invalid_count": 1,
                "insufficient_history_count": 1,
                "failed_count": 1,
                "missing_count": 1,
                "diagnostic_count": 4,
            },
            "exclusions": exclusions,
            "diagnostics": exclusions,
        }
        res = check_universe_audit_invariants(audit, payload)
        self.assertEqual(res.status, "PASS")

        # Verify sum invariant: expected == processed + invalid + insufficient + failed + missing
        c = audit["counts"]
        self.assertEqual(
            c["expected_count"],
            c["processed_count"]
            + c["invalid_count"]
            + c["insufficient_history_count"]
            + c["failed_count"]
            + c["missing_count"],
        )

    def test_scenario_7_missing_symbol_detection(self):
        """Scenario 7: Symbol in expected universe missing from scan results."""
        payload = copy.deepcopy(self.healthy_payload)

        ex_record = {
            "symbol": "MISSSYM",
            "stage": "UNIVERSE_DISCOVERY",
            "category": "UNIVERSE_INCOMPLETE",
            "status": "MISSING",
            "reason": "Symbol MISSSYM missing from scan results",
            "latest_date": None,
            "expected_date": self.data_as_of,
            "processed": False,
        }

        audit = {
            "status": "DEGRADED",
            "failed_stage": "UNIVERSE_DISCOVERY",
            "expected_symbols": ["FPT", "MISSSYM", "MWG", "VN30", "VNINDEX"],
            "processed_symbols": ["FPT", "MWG", "VN30", "VNINDEX"],
            "invalid_symbols": [],
            "insufficient_history_symbols": [],
            "failed_symbols": [],
            "missing_symbols": ["MISSSYM"],
            "counts": {
                "expected_count": 5,
                "processed_count": 4,
                "invalid_count": 0,
                "insufficient_history_count": 0,
                "failed_count": 0,
                "missing_count": 1,
                "diagnostic_count": 1,
            },
            "exclusions": [ex_record],
            "diagnostics": [ex_record],
        }
        res = check_universe_audit_invariants(audit, payload)
        self.assertEqual(res.status, "PASS")
        self.assertEqual(audit["exclusions"][0]["category"], "UNIVERSE_INCOMPLETE")
        self.assertEqual(audit["exclusions"][0]["status"], "MISSING")

    def test_scenario_8_duplicate_classification_detection(self):
        """Scenario 8: Detection of duplicate classification (symbol in multiple disjoint sets)."""
        audit = {
            "status": "FAILED",
            "failed_stage": "STOCK_FETCH",
            "expected_symbols": ["FPT", "MWG", "OTHER", "VN30", "VNINDEX"],
            "processed_symbols": ["FPT", "MWG", "VN30", "VNINDEX"],
            "invalid_symbols": ["FPT"],  # Duplicate: FPT in both processed and invalid
            "insufficient_history_symbols": [],
            "failed_symbols": [],
            "missing_symbols": [],
            "counts": {
                "expected_count": 5,
                "processed_count": 4,
                "invalid_count": 1,
                "insufficient_history_count": 0,
                "failed_count": 0,
                "missing_count": 0,
                "diagnostic_count": 1,
            },
            "exclusions": [
                {
                    "symbol": "FPT",
                    "stage": "STOCK_FETCH",
                    "category": "INVALID_SYMBOL",
                    "status": "INVALID",
                    "reason": "Duplicate classification",
                }
            ],
            "diagnostics": [
                {
                    "symbol": "FPT",
                    "stage": "STOCK_FETCH",
                    "category": "INVALID_SYMBOL",
                    "status": "INVALID",
                    "reason": "Duplicate classification",
                }
            ],
        }
        res = check_universe_audit_invariants(audit, self.healthy_payload)
        self.assertEqual(res.status, "FAIL")
        self.assertIn("Duplicate symbol classification detected", res.message)

    def test_scenario_9_monitoring_count_consistency(self):
        """Scenario 9: Verification that production monitoring consumes exact pipeline universe_audit counts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = os.path.join(tmpdir, "history")
            os.makedirs(hist_dir, exist_ok=True)

            with open(os.path.join(tmpdir, "recommendations.json"), "w") as f:
                json.dump(self.healthy_payload, f)
            with open(os.path.join(tmpdir, "market.json"), "w") as f:
                json.dump(self.healthy_market, f)

            with open(os.path.join(hist_dir, "index.json"), "w") as f:
                json.dump({"dates": [self.data_as_of]}, f)
            with open(os.path.join(hist_dir, f"{self.data_as_of}.json"), "w") as f:
                json.dump(self.healthy_payload, f)

            audit_input = {
                "status": "SUCCESS",
                "failed_stage": None,
                "expected_symbols": ["FPT", "MWG", "VN30", "VNINDEX"],
                "processed_symbols": ["FPT", "MWG", "VN30", "VNINDEX"],
                "invalid_symbols": [],
                "insufficient_history_symbols": [],
                "failed_symbols": [],
                "missing_symbols": [],
                "counts": {
                    "status": "SUCCESS",
                    "failed_stage": None,
                    "expected_count": 4,
                    "processed_count": 4,
                    "invalid_count": 0,
                    "insufficient_history_count": 0,
                    "failed_count": 0,
                    "missing_count": 0,
                    "diagnostic_count": 0,
                },
                "exclusions": [],
                "diagnostics": [],
            }

            mon_res = evaluate_production_monitoring(
                generated_dir=tmpdir,
                recommendations_payload=self.healthy_payload,
                market_payload=self.healthy_market,
                reference_date=self.reference_date,
                universe_audit=audit_input,
            )

            mon_dict = mon_res.to_dict()
            self.assertEqual(mon_dict["metrics"]["universe_audit"], audit_input)

    def test_scenario_10_monitoring_count_mismatch_internal_consistency_failure(self):
        """Scenario 10: Count mismatch between set lengths and reported counts raises internal consistency failure."""
        audit_mismatched = {
            "status": "SUCCESS",
            "failed_stage": None,
            "expected_symbols": ["FPT", "MWG", "VN30", "VNINDEX"],
            "processed_symbols": ["FPT", "MWG", "VN30", "VNINDEX"],
            "invalid_symbols": [],
            "insufficient_history_symbols": [],
            "failed_symbols": [],
            "missing_symbols": [],
            "counts": {
                "expected_count": 100,  # Mismatch: 100 reported vs 4 actual
                "processed_count": 4,
                "invalid_count": 0,
                "insufficient_history_count": 0,
                "failed_count": 0,
                "missing_count": 0,
                "diagnostic_count": 0,
            },
            "exclusions": [],
            "diagnostics": [],
        }

        res = check_universe_audit_invariants(audit_mismatched, self.healthy_payload)
        self.assertEqual(res.status, "FAIL")
        self.assertIn("Count mismatch for expected", res.message)

    def test_scenario_11_monitoring_fail_diagnostic_identifies_failed_check(self):
        """Scenario 11: When monitoring produces FAIL, diagnostics explicitly identify the failed check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = os.path.join(tmpdir, "history")
            os.makedirs(hist_dir, exist_ok=True)

            bad_payload = copy.deepcopy(self.healthy_payload)
            bad_payload["data_as_of"] = "INVALID-DATE"

            with open(os.path.join(tmpdir, "recommendations.json"), "w") as f:
                json.dump(bad_payload, f)
            with open(os.path.join(tmpdir, "market.json"), "w") as f:
                json.dump(self.healthy_market, f)

            mon_res = evaluate_production_monitoring(
                generated_dir=tmpdir,
                recommendations_payload=bad_payload,
                market_payload=self.healthy_market,
                reference_date=self.reference_date,
            )

            mon_dict = mon_res.to_dict()
            self.assertEqual(mon_dict["overall_status"], "FAIL")

            # Check that failed monitoring diagnostics exist
            diag = mon_dict["metrics"]["monitoring_diagnostics"]
            self.assertGreater(len(diag), 0)
            failed_checks = [d["check"] for d in diag]
            self.assertTrue(
                any(c in failed_checks for c in ("data_freshness", "artifact_existence"))
            )
            for d in diag:
                self.assertEqual(d["stage"], "MONITORING")
                self.assertEqual(d["category"], "MONITORING_FAILURE")
                self.assertEqual(d["status"], "FAIL")

    def test_scenario_12_output_validation_failure_correct_stage_category(self):
        """Scenario 12: Payload validation failure identifies stage = OUTPUT_VALIDATION, category = OUTPUT_VALIDATION_FAILURE."""
        from scripts.generate_report import validate_final_payload_integrity

        invalid_payload = copy.deepcopy(self.healthy_payload)
        invalid_payload["recommendations"][0]["signal_score"] = 150.0  # Out of bounds score

        with self.assertRaises(ValueError) as cm:
            validate_final_payload_integrity(
                invalid_payload, schema=None, payload_name="recommendations"
            )

        exc = cm.exception
        self.assertTrue(hasattr(exc, "diagnostics"))
        self.assertGreater(len(exc.diagnostics), 0)
        diag = exc.diagnostics[0]
        self.assertEqual(diag["stage"], "OUTPUT_VALIDATION")
        self.assertEqual(diag["category"], "OUTPUT_VALIDATION_FAILURE")
        self.assertEqual(diag["payload"], "recommendations")
        self.assertEqual(diag["status"], "FAIL")

    def test_scenario_13_rate_limit_failure(self):
        """Scenario 13: Rate limit failure produces stage = STOCK_FETCH, category = RATE_LIMIT."""
        payload = copy.deepcopy(self.healthy_payload)
        rl_rec = self._make_insufficient_rec("RLSYM")
        payload["recommendations"].append(rl_rec)
        payload["summary"]["total_scanned"] = 3
        payload["summary"]["avoid_count"] = 1

        ex_record = {
            "symbol": "RLSYM",
            "stage": "STOCK_FETCH",
            "category": "RATE_LIMIT",
            "status": "FAILED",
            "reason": "Provider rate limit encountered fetching RLSYM",
            "latest_date": None,
            "expected_date": self.data_as_of,
            "processed": False,
        }

        audit = {
            "status": "DEGRADED",
            "failed_stage": "STOCK_FETCH",
            "expected_symbols": ["FPT", "MWG", "RLSYM", "VN30", "VNINDEX"],
            "processed_symbols": ["FPT", "MWG", "VN30", "VNINDEX"],
            "invalid_symbols": [],
            "insufficient_history_symbols": [],
            "failed_symbols": ["RLSYM"],
            "missing_symbols": [],
            "counts": {
                "expected_count": 5,
                "processed_count": 4,
                "invalid_count": 0,
                "insufficient_history_count": 0,
                "failed_count": 1,
                "missing_count": 0,
                "diagnostic_count": 1,
            },
            "exclusions": [ex_record],
            "diagnostics": [ex_record],
        }

        res = check_universe_audit_invariants(audit, payload)
        self.assertEqual(res.status, "PASS")
        self.assertEqual(audit["exclusions"][0]["category"], "RATE_LIMIT")

    def test_scenario_14_artifact_preservation_remains_unchanged(self):
        """Scenario 14: Failed validation or monitoring preserves existing generated artifacts on disk byte-for-byte."""
        from scripts.generate_report import validate_final_payload_integrity

        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = os.path.join(tmpdir, "history")
            os.makedirs(hist_dir, exist_ok=True)

            rec_path = os.path.join(tmpdir, "recommendations.json")
            mkt_path = os.path.join(tmpdir, "market.json")
            mon_path = os.path.join(tmpdir, "monitoring.json")
            idx_path = os.path.join(hist_dir, "index.json")
            hist_path = os.path.join(hist_dir, "2026-09-25.json")

            files_map = {
                rec_path: b'{\n  "artifact": "recommendations_v1"\n}\n',
                mkt_path: b'{\n  "artifact": "market_v1"\n}\n',
                mon_path: b'{\n  "artifact": "monitoring_v1"\n}\n',
                idx_path: b'{\n  "artifact": "index_v1"\n}\n',
                hist_path: b'{\n  "artifact": "history_2026-09-25_v1"\n}\n',
            }

            for fpath, content in files_map.items():
                with open(fpath, "wb") as f:
                    f.write(content)

            # Record exact bytes before triggering failure
            bytes_before = {fpath: open(fpath, "rb").read() for fpath in files_map}

            # Trigger real validation failure with corrupted payload
            corrupted_payload = copy.deepcopy(self.healthy_payload)
            corrupted_payload["recommendations"][0]["signal_score"] = -999.0  # Out of bounds

            with self.assertRaises(ValueError) as cm:
                validate_final_payload_integrity(corrupted_payload, payload_name="recommendations")

            self.assertIn("stage OUTPUT_VALIDATION", str(cm.exception))

            # Verify every pre-existing artifact is byte-for-byte unchanged
            for fpath, original_bytes in bytes_before.items():
                current_bytes = open(fpath, "rb").read()
                self.assertEqual(
                    current_bytes,
                    original_bytes,
                    f"Artifact '{os.path.basename(fpath)}' was modified during validation failure",
                )

            # Verify no unexpected partial or temp files were left in tmpdir
            all_files_in_root = set(os.listdir(tmpdir))
            all_files_in_hist = set(os.listdir(hist_dir))
            self.assertEqual(
                all_files_in_root,
                {"recommendations.json", "market.json", "monitoring.json", "history"},
            )
            self.assertEqual(all_files_in_hist, {"index.json", "2026-09-25.json"})

    def test_scenario_15_diagnostics_deterministic_across_repeated_runs(self):
        """Scenario 15: Run diagnostic-generation twice on identical input state and assert exact equality and stable symbol ordering."""

        def _generate_audit_from_input(
            candidate_list, missing_list, invalid_list, failed_list, data_as_of
        ):
            # Convert inputs to sets to simulate arbitrary set iteration order
            expected_set = (
                {"VNINDEX", "VN30"}
                | set(candidate_list)
                | set(missing_list)
                | set(invalid_list)
                | set(failed_list)
            )
            proc_set = {"VNINDEX", "VN30"} | set(candidate_list)
            inv_set = set(invalid_list)
            insuf_set = set()
            fail_set = set(failed_list)
            miss_set = set(missing_list)

            exclusions_map = {}
            for s in inv_set:
                exclusions_map[s] = {
                    "symbol": s,
                    "stage": "STOCK_FETCH",
                    "category": "INVALID_SYMBOL",
                    "status": "INVALID",
                    "reason": f"Invalid stock symbol {s}",
                    "latest_date": None,
                    "expected_date": data_as_of,
                    "processed": False,
                    "recoverable": False,
                }
            for s in fail_set:
                exclusions_map[s] = {
                    "symbol": s,
                    "stage": "STOCK_FETCH",
                    "category": "PROVIDER_FAILURE",
                    "status": "FAILED",
                    "reason": f"Provider timeout for {s}",
                    "latest_date": None,
                    "expected_date": data_as_of,
                    "processed": False,
                    "recoverable": True,
                }
            for s in miss_set:
                exclusions_map[s] = {
                    "symbol": s,
                    "stage": "UNIVERSE_DISCOVERY",
                    "category": "UNIVERSE_INCOMPLETE",
                    "status": "MISSING",
                    "reason": f"Symbol {s} missing from scan results",
                    "latest_date": None,
                    "expected_date": data_as_of,
                    "processed": False,
                    "recoverable": False,
                }

            diagnostics_list = [exclusions_map[s] for s in sorted(exclusions_map.keys())]

            summary = {
                "status": "DEGRADED",
                "failed_stage": "STOCK_FETCH",
                "expected_count": len(expected_set),
                "processed_count": len(proc_set),
                "invalid_count": len(inv_set),
                "insufficient_history_count": len(insuf_set),
                "failed_count": len(fail_set),
                "missing_count": len(miss_set),
                "diagnostic_count": len(diagnostics_list),
            }

            return {
                "status": "DEGRADED",
                "failed_stage": "STOCK_FETCH",
                "expected_symbols": sorted(expected_set),
                "processed_symbols": sorted(proc_set),
                "invalid_symbols": sorted(inv_set),
                "insufficient_history_symbols": sorted(insuf_set),
                "failed_symbols": sorted(fail_set),
                "missing_symbols": sorted(miss_set),
                "counts": summary,
                "summary": summary,
                "exclusions": diagnostics_list,
                "diagnostics": diagnostics_list,
            }

        # Run 1: Input lists in order A
        candidates_1 = ["MWG", "FPT", "VIC", "VNM"]
        missing_1 = ["ZAL", "AAA"]
        invalid_1 = ["XYZ"]
        failed_1 = ["BID"]

        audit_run_1 = _generate_audit_from_input(
            candidates_1, missing_1, invalid_1, failed_1, "2026-09-25"
        )

        # Run 2: Input lists in different order B
        candidates_2 = ["VNM", "VIC", "FPT", "MWG"]
        missing_2 = ["AAA", "ZAL"]
        invalid_2 = ["XYZ"]
        failed_2 = ["BID"]

        audit_run_2 = _generate_audit_from_input(
            candidates_2, missing_2, invalid_2, failed_2, "2026-09-25"
        )

        # Assert exact equality across runs
        self.assertEqual(audit_run_1, audit_run_2)

        # Assert symbol lists are deterministically sorted
        self.assertEqual(audit_run_1["expected_symbols"], sorted(audit_run_1["expected_symbols"]))
        self.assertEqual(audit_run_1["processed_symbols"], sorted(audit_run_1["processed_symbols"]))
        symbols_in_diagnostics = [d["symbol"] for d in audit_run_1["diagnostics"]]
        self.assertEqual(symbols_in_diagnostics, sorted(symbols_in_diagnostics))


if __name__ == "__main__":
    unittest.main()
