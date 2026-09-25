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
    validate_monitoring_payload,
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

    def test_complete_universe_audit(self):
        """Test 1: Complete universe where 100% of expected symbols are processed."""
        expected = ["FPT", "MWG", "VN30", "VNINDEX"]
        audit = {
            "expected_symbols": expected,
            "processed_symbols": expected,
            "invalid_symbols": [],
            "insufficient_history_symbols": [],
            "failed_symbols": [],
            "missing_symbols": [],
            "counts": {
                "expected_count": 4,
                "processed_count": 4,
                "invalid_count": 0,
                "insufficient_history_count": 0,
                "failed_count": 0,
                "missing_count": 0,
            },
            "exclusions": [],
        }
        res = check_universe_audit_invariants(audit, self.healthy_payload)
        self.assertEqual(res.status, "PASS")

    def test_invalid_symbols_audit(self):
        """Test 2: Universe containing invalid stock symbols tagged INVALID_SYMBOL / EXPLICITLY_INVALID."""
        payload = copy.deepcopy(self.healthy_payload)
        bad_rec = self._make_insufficient_rec("BADSYM")
        payload["recommendations"].append(bad_rec)
        payload["summary"]["total_scanned"] = 3
        payload["summary"]["avoid_count"] = 1

        audit = {
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
            },
            "exclusions": [
                {
                    "symbol": "BADSYM",
                    "category": "INVALID_SYMBOL",
                    "reason": "Invalid stock symbol BADSYM",
                }
            ],
        }
        res = check_universe_audit_invariants(audit, payload)
        self.assertEqual(res.status, "PASS")

    def test_insufficient_history_symbols_audit(self):
        """Test 3: Universe containing symbols with insufficient historical sessions."""
        payload = copy.deepcopy(self.healthy_payload)
        insuf_rec = self._make_insufficient_rec("SHORT")
        payload["recommendations"].append(insuf_rec)
        payload["summary"]["total_scanned"] = 3
        payload["summary"]["avoid_count"] = 1

        audit = {
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
            },
            "exclusions": [
                {
                    "symbol": "SHORT",
                    "category": "INSUFFICIENT_HISTORICAL_DATA",
                    "reason": "Insufficient historical sessions (10 < 20)",
                }
            ],
        }
        res = check_universe_audit_invariants(audit, payload)
        self.assertEqual(res.status, "PASS")

    def test_provider_failures_audit(self):
        """Test 4: Universe containing provider fetch failure symbols."""
        payload = copy.deepcopy(self.healthy_payload)
        fail_rec = self._make_insufficient_rec("FAILSYM")
        payload["recommendations"].append(fail_rec)
        payload["summary"]["total_scanned"] = 3
        payload["summary"]["avoid_count"] = 1

        audit = {
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
            },
            "exclusions": [
                {
                    "symbol": "FAILSYM",
                    "category": "PROVIDER_FAILURE",
                    "reason": "Provider network timeout for symbol FAILSYM",
                }
            ],
        }
        res = check_universe_audit_invariants(audit, payload)
        self.assertEqual(res.status, "PASS")

    def test_temporal_invalid_symbols_audit(self):
        """Test 5: Universe containing symbols excluded due to temporal inconsistency."""
        payload = copy.deepcopy(self.healthy_payload)
        stale_rec = self._make_insufficient_rec("STALE")
        payload["recommendations"].append(stale_rec)
        payload["summary"]["total_scanned"] = 3
        payload["summary"]["avoid_count"] = 1

        audit = {
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
            },
            "exclusions": [
                {
                    "symbol": "STALE",
                    "category": "TEMPORAL_INVALID",
                    "reason": "Stale date 2026-09-10 vs benchmark 2026-09-25",
                }
            ],
        }
        res = check_universe_audit_invariants(audit, payload)
        self.assertEqual(res.status, "PASS")

    def test_mixed_classification_audit(self):
        """Test 6: Universe containing a mix of processed, invalid, insufficient, failed, and missing symbols."""
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

        audit = {
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
            },
            "exclusions": [
                {"symbol": "FAILSYM", "category": "PROVIDER_FAILURE", "reason": "Fetch error"},
                {"symbol": "INVSYM", "category": "INVALID_SYMBOL", "reason": "Invalid symbol"},
                {"symbol": "MISSSYM", "category": "MISSING_SYMBOL", "reason": "Missing from scan"},
                {
                    "symbol": "SHORTSYM",
                    "category": "INSUFFICIENT_HISTORICAL_DATA",
                    "reason": "Short history",
                },
            ],
        }
        res = check_universe_audit_invariants(audit, payload)
        self.assertEqual(res.status, "PASS")

    def test_zero_valid_symbols_audit(self):
        """Test 7: Universe where 0 valid symbols were processed."""
        payload = copy.deepcopy(self.healthy_payload)
        payload["recommendations"] = [
            self._make_insufficient_rec("FPT"),
            self._make_insufficient_rec("MWG"),
        ]
        payload["summary"] = {
            "total_scanned": 2,
            "buy_count": 0,
            "watch_count": 0,
            "hold_count": 0,
            "sell_count": 0,
            "avoid_count": 2,
        }

        audit = {
            "expected_symbols": ["FPT", "MWG", "VN30", "VNINDEX"],
            "processed_symbols": [],
            "invalid_symbols": [],
            "insufficient_history_symbols": ["FPT", "MWG"],
            "failed_symbols": ["VN30", "VNINDEX"],
            "missing_symbols": [],
            "counts": {
                "expected_count": 4,
                "processed_count": 0,
                "invalid_count": 0,
                "insufficient_history_count": 2,
                "failed_count": 2,
                "missing_count": 0,
            },
            "exclusions": [
                {"symbol": "FPT", "category": "INSUFFICIENT_HISTORICAL_DATA", "reason": "No data"},
                {"symbol": "MWG", "category": "INSUFFICIENT_HISTORICAL_DATA", "reason": "No data"},
                {"symbol": "VN30", "category": "PROVIDER_FAILURE", "reason": "VN30 failed"},
                {"symbol": "VNINDEX", "category": "PROVIDER_FAILURE", "reason": "VNINDEX failed"},
            ],
        }
        res = check_universe_audit_invariants(audit, payload)
        self.assertEqual(res.status, "PASS")

    def test_count_consistency_invariant_failure(self):
        """Test 8: Failure when expected != processed + invalid + insufficient + failed + missing."""
        exp = [f"SYM_{i}" for i in range(10)]
        audit = {
            "expected_symbols": exp,
            "processed_symbols": ["SYM_0", "SYM_1", "SYM_2", "SYM_3"],
            "invalid_symbols": [],
            "insufficient_history_symbols": [],
            "failed_symbols": [],
            "missing_symbols": [],
            "counts": {
                "expected_count": 10,
                "processed_count": 4,
                "invalid_count": 0,
                "insufficient_history_count": 0,
                "failed_count": 0,
                "missing_count": 0,
            },
            "exclusions": [],
        }
        res = check_universe_audit_invariants(audit, self.healthy_payload)
        self.assertEqual(res.status, "FAIL")
        self.assertIn("Audit sum invariant failed", res.message)

    def test_duplicate_classification_detection(self):
        """Test 9: Detection of duplicate classifications (symbol in multiple sets)."""
        audit = {
            "expected_symbols": ["FPT", "MWG", "OTHER", "VN30", "VNINDEX"],
            "processed_symbols": ["FPT", "MWG", "VN30", "VNINDEX"],
            "invalid_symbols": ["FPT"],  # FPT is in both processed and invalid
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
            },
            "exclusions": [{"symbol": "FPT", "category": "INVALID_SYMBOL", "reason": "Duplicate"}],
        }
        res = check_universe_audit_invariants(audit, self.healthy_payload)
        self.assertEqual(res.status, "FAIL")
        self.assertIn("Duplicate symbol classification detected", res.message)

    def test_monitoring_payload_consistency_with_pipeline_state(self):
        """Test 10: Verify production monitoring output payload contains exact universe audit state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = os.path.join(tmpdir, "history")
            os.makedirs(hist_dir, exist_ok=True)

            with open(os.path.join(tmpdir, "recommendations.json"), "w") as f:
                json.dump(self.healthy_payload, f)
            with open(os.path.join(tmpdir, "market.json"), "w") as f:
                json.dump(self.healthy_market, f)

            index_dates = [self.data_as_of]
            with open(os.path.join(hist_dir, "index.json"), "w") as f:
                json.dump({"dates": index_dates}, f)
            with open(os.path.join(hist_dir, f"{self.data_as_of}.json"), "w") as f:
                json.dump(self.healthy_payload, f)

            audit_input = {
                "expected_symbols": ["FPT", "MWG", "VN30", "VNINDEX"],
                "processed_symbols": ["FPT", "MWG", "VN30", "VNINDEX"],
                "invalid_symbols": [],
                "insufficient_history_symbols": [],
                "failed_symbols": [],
                "missing_symbols": [],
                "counts": {
                    "expected_count": 4,
                    "processed_count": 4,
                    "invalid_count": 0,
                    "insufficient_history_count": 0,
                    "failed_count": 0,
                    "missing_count": 0,
                },
                "exclusions": [],
            }

            mon_res = evaluate_production_monitoring(
                generated_dir=tmpdir,
                recommendations_payload=self.healthy_payload,
                market_payload=self.healthy_market,
                reference_date=self.reference_date,
                universe_audit=audit_input,
            )

            mon_dict = mon_res.to_dict()
            self.assertTrue(validate_monitoring_payload(mon_dict))

            # Verify metrics contains universe_audit
            mon_audit = mon_dict["metrics"]["universe_audit"]
            self.assertEqual(mon_audit, audit_input)

            # Verify universe_audit_invariants check passed
            chk_names = [c["check_name"] for c in mon_dict["checks"]]
            self.assertIn("universe_audit_invariants", chk_names)
            inv_chk = next(
                c for c in mon_dict["checks"] if c["check_name"] == "universe_audit_invariants"
            )
            self.assertEqual(inv_chk["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
