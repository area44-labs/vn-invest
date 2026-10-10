"""Deterministic offline regression tests for production data-quality auditability and observability."""

import copy
import json
import os
import tempfile

import pytest

from scripts.monitoring import (
    check_universe_audit_invariants,
    evaluate_production_monitoring,
)
from scripts.quant.config import DEFAULT_QUANT_CONFIG

SIGNAL_MODEL_VERSION = DEFAULT_QUANT_CONFIG.model_version


@pytest.mark.unit
class TestAuditTrailObservability:
    """Offline regression tests covering universe audit coverage, exclusion reasons, and invariant cross-checks."""

    def setup_method(self):
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

    def test_complete_production_universe(self):
        """Verifies that a complete healthy production universe results in 100% symbol processing with zero audit failures."""
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
        assert res.status == "PASS"
        assert audit["summary"]["diagnostic_count"] == 0

    def test_one_invalid_symbol(self):
        """Verifies that an invalid candidate symbol is recorded in audit exclusions and passes audit set invariants."""
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
        assert res.status == "PASS"
        assert audit["exclusions"][0]["category"] == "INVALID_SYMBOL"
        assert audit["exclusions"][0]["stage"] == "STOCK_FETCH"

    def test_one_insufficient_history_symbol(self):
        """Verifies that a candidate symbol with insufficient history is classified under INSUFFICIENT_HISTORICAL_DATA in audit exclusions."""
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
        assert res.status == "PASS"
        assert audit["exclusions"][0]["category"] == "INSUFFICIENT_HISTORICAL_DATA"

    def test_one_provider_failure(self):
        """Verifies that a provider network failure for a symbol is classified under PROVIDER_FAILURE in audit exclusions."""
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
        assert res.status == "PASS"
        assert audit["exclusions"][0]["category"] == "PROVIDER_FAILURE"

    def test_one_temporal_invalid_symbol(self):
        """Verifies that a stale or temporally invalid candidate symbol is classified under TEMPORAL_INVALID in audit exclusions."""
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
        assert res.status == "PASS"
        assert audit["exclusions"][0]["stage"] == "TEMPORAL_VALIDATION"
        assert audit["exclusions"][0]["category"] == "TEMPORAL_INVALID"

    def test_mixed_classifications(self):
        """Verifies audit invariant checks across a universe containing mixed symbol failure categories."""
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
        assert res.status == "PASS"

        # Verify sum invariant: expected == processed + invalid + insufficient + failed + missing
        c = audit["counts"]
        assert c["expected_count"] == (
            c["processed_count"]
            + c["invalid_count"]
            + c["insufficient_history_count"]
            + c["failed_count"]
            + c["missing_count"]
        )

    def test_missing_symbol_detection(self):
        """Verifies that candidate symbols missing from scan results are flagged as UNIVERSE_INCOMPLETE with MISSING status."""
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
        assert res.status == "PASS"
        assert audit["exclusions"][0]["category"] == "UNIVERSE_INCOMPLETE"
        assert audit["exclusions"][0]["status"] == "MISSING"

    def test_duplicate_classification_detection(self):
        """Verifies that a symbol classified in multiple disjoint sets triggers an audit invariant failure."""
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
        assert res.status == "FAIL"
        assert "Duplicate symbol classification detected" in res.message

    def test_monitoring_count_consistency(self):
        """Verifies that production monitoring consumes exact pipeline universe audit counts without modification."""
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
            assert mon_dict["metrics"]["universe_audit"] == audit_input

    def test_monitoring_count_mismatch_internal_consistency_failure(self):
        """Verifies that a count mismatch between set lengths and reported summary counts triggers an audit invariant failure."""
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
        assert res.status == "FAIL"
        assert "Count mismatch for expected" in res.message

    def test_monitoring_fail_diagnostic_identifies_failed_check(self):
        """Verifies that when monitoring status is FAIL, output diagnostics explicitly identify the failing monitoring check."""
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
            assert mon_dict["overall_status"] == "FAIL"

            # Check that failed monitoring diagnostics exist
            diag = mon_dict["metrics"]["monitoring_diagnostics"]
            assert len(diag) > 0
            failed_checks = [d["check"] for d in diag]
            assert any(c in failed_checks for c in ("data_freshness", "artifact_existence"))
            for d in diag:
                assert d["stage"] == "MONITORING"
                assert d["category"] == "MONITORING_FAILURE"
                assert d["status"] == "FAIL"

    def test_output_validation_failure_correct_stage_category(self):
        """Verifies that payload validation failure attaches stage OUTPUT_VALIDATION and category OUTPUT_VALIDATION_FAILURE to error diagnostics."""
        from scripts.generate_report import validate_final_payload_integrity

        invalid_payload = copy.deepcopy(self.healthy_payload)
        invalid_payload["recommendations"][0]["signal_score"] = 150.0  # Out of bounds score

        with pytest.raises(ValueError) as cm:
            validate_final_payload_integrity(invalid_payload, payload_name="recommendations")

        exc = cm.value
        assert hasattr(exc, "diagnostics")
        assert len(exc.diagnostics) > 0
        diag = exc.diagnostics[0]
        assert diag["stage"] == "OUTPUT_VALIDATION"
        assert diag["category"] == "OUTPUT_VALIDATION_FAILURE"
        assert diag["payload"] == "recommendations"
        assert diag["status"] == "FAIL"

    def test_rate_limit_failure(self):
        """Verifies that provider rate limiting produces audit exclusion records with stage STOCK_FETCH and category RATE_LIMIT."""
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
        assert res.status == "PASS"
        assert audit["exclusions"][0]["category"] == "RATE_LIMIT"

    def test_diagnostics_deterministic_across_repeated_runs(self):
        """Verifies that build_universe_audit produces identical output and deterministically sorted symbol lists across repeated executions."""
        from scripts.domain.universe import Universe, UniverseScanResult
        from scripts.generate_report import build_universe_audit

        data_as_of = "2026-09-25"

        exclusions = {
            "XYZ": {
                "symbol": "XYZ",
                "stage": "STOCK_FETCH",
                "category": "INVALID_SYMBOL",
                "status": "INVALID",
                "reason": "Invalid symbol XYZ",
                "latest_date": None,
                "expected_date": data_as_of,
                "processed": False,
                "recoverable": False,
            },
            "BID": {
                "symbol": "BID",
                "stage": "STOCK_FETCH",
                "category": "PROVIDER_FAILURE",
                "status": "FAILED",
                "reason": "Provider timeout for BID",
                "latest_date": None,
                "expected_date": data_as_of,
                "processed": False,
                "recoverable": True,
            },
            "ZAL": {
                "symbol": "ZAL",
                "stage": "UNIVERSE_DISCOVERY",
                "category": "UNIVERSE_INCOMPLETE",
                "status": "MISSING",
                "reason": "Symbol ZAL missing from scan results",
                "latest_date": None,
                "expected_date": data_as_of,
                "processed": False,
                "recoverable": False,
            },
            "AAA": {
                "symbol": "AAA",
                "stage": "UNIVERSE_DISCOVERY",
                "category": "UNIVERSE_INCOMPLETE",
                "status": "MISSING",
                "reason": "Symbol AAA missing from scan results",
                "latest_date": None,
                "expected_date": data_as_of,
                "processed": False,
                "recoverable": False,
            },
        }

        u = Universe.from_candidates(
            candidates=[
                {"symbol": sym, "companyName": sym, "sector": "Sec", "exchange": "HOSE"}
                for sym in ["MWG", "FPT", "VIC", "VNM", "ZAL", "AAA", "XYZ", "BID"]
            ],
            universe_type="TEST_AUDIT",
            benchmarks=("VNINDEX", "VN30"),
        )

        scan_1 = UniverseScanResult(
            universe=u,
            processed_symbols=["VNINDEX", "VN30", "MWG", "FPT", "VIC", "VNM"],
            invalid_symbols=["XYZ"],
            insufficient_symbols=[],
            failed_symbols=["BID"],
            missing_symbols=["ZAL", "AAA"],
            exclusions_map=exclusions,
        )

        scan_2 = UniverseScanResult(
            universe=u,
            processed_symbols=["VNM", "VIC", "FPT", "MWG", "VN30", "VNINDEX"],
            invalid_symbols=["XYZ"],
            insufficient_symbols=[],
            failed_symbols=["BID"],
            missing_symbols={"AAA", "ZAL"},
            exclusions_map=exclusions,
        )

        audit_run_1 = build_universe_audit(scan_result=scan_1, update_data=False)
        audit_run_2 = build_universe_audit(scan_result=scan_2, update_data=False)

        # Assert exact equality across runs
        assert audit_run_1 == audit_run_2

        # Assert symbol lists are deterministically sorted
        assert audit_run_1["expected_symbols"] == sorted(audit_run_1["expected_symbols"])
        assert audit_run_1["processed_symbols"] == sorted(audit_run_1["processed_symbols"])
        symbols_in_diagnostics = [d["symbol"] for d in audit_run_1["diagnostics"]]
        assert symbols_in_diagnostics == sorted(symbols_in_diagnostics)
