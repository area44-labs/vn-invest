"""Unit tests for Production Monitoring Module (scripts/monitoring/)."""

import copy
import json
import os
import tempfile

import pandas as pd
import pytest

from scripts.monitoring import (
    CheckResult,
    check_data_freshness,
    check_history_index_status,
    check_numeric_sanity,
    check_ohlcv_data_quality,
    check_required_artifacts,
    check_schema_validation,
    check_symbol_processing_counts,
    evaluate_production_monitoring,
    find_nan_or_inf,
    normalize_market_payload,
    validate_monitoring_payload,
)
from scripts.quant.config import DEFAULT_QUANT_CONFIG
from scripts.quant.recommendation import generate_single_recommendation
from scripts.quant.regime import detect_market_regime

SIGNAL_MODEL_VERSION = DEFAULT_QUANT_CONFIG.model_version


@pytest.mark.unit
class TestProductionMonitoring:
    """Test suite for production monitoring checks, fail-closed rules, and serialization."""

    def setup_method(self):
        self.reference_date = "2026-09-17"
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
        self.healthy_summary = {
            "total_scanned": 2,
            "buy_count": 1,
            "watch_count": 1,
            "hold_count": 0,
            "sell_count": 0,
            "avoid_count": 0,
        }
        self.healthy_recommendations = [
            {
                "symbol": "FPT",
                "company_name": "FPT Corporation",
                "exchange": "HOSE",
                "sector": "Công nghệ",
                "action": "BUY",
                "data_quality": "SUFFICIENT",
                "data_quality_issues": [],
                "data_as_of": "2026-09-17",
                "data_source": "REAL_DATA",
                "signal_score": 82.5,
                "risk_adjusted_score": 78.0,
                "confidence": 0.85,
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
                "reasons": ["Strong trend", "High volume"],
                "warnings": [],
                "invalidation": ["Close below stop loss"],
            },
            {
                "symbol": "MWG",
                "company_name": "Mobile World Corporation",
                "exchange": "HOSE",
                "sector": "Bán lẻ",
                "action": "WATCH",
                "data_quality": "SUFFICIENT",
                "data_quality_issues": [],
                "data_as_of": "2026-09-17",
                "data_source": "REAL_DATA",
                "signal_score": 65.0,
                "risk_adjusted_score": 62.0,
                "confidence": 0.75,
                "risk_level": "MEDIUM",
                "expected_return": {
                    "expected_return_5d": 1.5,
                    "expected_return_10d": 2.5,
                    "expected_return_20d": 4.0,
                },
                "risk_metrics": {
                    "var_t25": -4.0,
                    "es_t25": -5.5,
                    "volatility_60d": 0.22,
                    "max_drawdown": -12.0,
                    "liquidity_score": 80.0,
                    "avg_value_20d": 95.0,
                },
                "trade_plan": {
                    "current_price": 60000.0,
                    "entry_low": 58000.0,
                    "entry_high": 60000.0,
                    "stop_loss": 55000.0,
                    "tp1": 65000.0,
                    "tp2": 70000.0,
                    "risk_reward": 1.8,
                    "position_percent": 10.0,
                },
                "reasons": ["Consolidating near support"],
                "warnings": [],
                "invalidation": ["Close below support"],
            },
        ]
        self.healthy_performance = {
            "schema_version": "2.0",
            "stages": [
                {"stage": "pipeline", "elapsed_seconds": 1.0, "status": "SUCCESS"},
                {"stage": "benchmark_fetch", "elapsed_seconds": 0.1, "status": "SUCCESS"},
                {"stage": "stock_fetch", "elapsed_seconds": 0.5, "status": "SUCCESS"},
                {"stage": "temporal_validation", "elapsed_seconds": 0.05, "status": "SUCCESS"},
                {"stage": "market_calculation", "elapsed_seconds": 0.05, "status": "SUCCESS"},
                {"stage": "regime_calculation", "elapsed_seconds": 0.05, "status": "SUCCESS"},
                {"stage": "risk_calculation", "elapsed_seconds": 0.1, "status": "SUCCESS"},
                {
                    "stage": "recommendation_calculation",
                    "elapsed_seconds": 0.1,
                    "status": "SUCCESS",
                },
                {"stage": "monitoring", "elapsed_seconds": 0.05, "status": "SUCCESS"},
                {"stage": "payload_validation", "elapsed_seconds": 0.05, "status": "SUCCESS"},
            ],
            "provider": {
                "total_calls": 2,
                "successful_calls": 2,
                "failed_calls": 0,
                "retry_count": 0,
                "total_elapsed_seconds": 0.6,
                "average_call_seconds": 0.3,
                "calls_by_source": {"kbs": 2},
            },
            "duplicate_operations": [],
        }
        self.healthy_payload = {
            "schema_version": "2.0",
            "signal_model_version": SIGNAL_MODEL_VERSION,
            "generated_at": "2026-09-17T06:00:00+00:00",
            "data_as_of": "2026-09-17",
            "source_date": "2026-09-17",
            "data_source": "REAL_DATA",
            "universe_info": {"universe_type": "TEST", "universe_size": 2},
            "market": self.healthy_market,
            "summary": self.healthy_summary,
            "recommendations": self.healthy_recommendations,
        }
        self.healthy_audit = {
            "expected_symbols": ["VNINDEX", "VN30", "FPT", "MWG"],
            "processed_symbols": ["VNINDEX", "VN30", "FPT", "MWG"],
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
            "performance": self.healthy_performance,
        }

    def test_normalize_market_payload_variants(self):
        """Verify normalize_market_payload handles nested, standalone, flat, and missing date structures consistently."""
        # 1. Standalone market.json shape (with top-level data_as_of and market dict)
        standalone = {
            "data_as_of": "2026-09-28",
            "source_date": "2026-09-28",
            "generated_at": "2026-09-28T06:00:00+00:00",
            "data_source": "REAL_DATA",
            "universe_info": {"universe_type": "TEST", "universe_size": 2},
            "market": {
                "regime": "BEAR",
                "confidence": 0.85,
                "metrics": {"vnindex_value": 1780.0, "vnindex_change_pct": -0.25},
            },
            "summary": self.healthy_summary,
        }
        norm_standalone = normalize_market_payload(standalone, data_as_of="2026-09-28")
        assert norm_standalone["data_as_of"] == "2026-09-28"
        assert norm_standalone["market"]["regime"] == "BEAR"
        assert "data_as_of" not in norm_standalone["market"]

        # 2. Flat inner market dict with top-level data_as_of
        flat = {
            "data_as_of": "2026-09-28",
            "regime": "BEAR",
            "confidence": 0.85,
            "metrics": {"vnindex_value": 1780.0, "vnindex_change_pct": -0.25},
        }
        norm_flat = normalize_market_payload(flat, data_as_of="2026-09-28")
        assert norm_flat["data_as_of"] == "2026-09-28"
        assert norm_flat["market"]["regime"] == "BEAR"
        assert "data_as_of" not in norm_flat["market"]

        # 3. Direct inner market dict without data_as_of key
        inner = {
            "regime": "BEAR",
            "confidence": 0.85,
            "metrics": {"vnindex_value": 1780.0, "vnindex_change_pct": -0.25},
        }
        norm_inner = normalize_market_payload(inner, data_as_of="2026-09-28")
        assert norm_inner["data_as_of"] == "2026-09-28"
        assert norm_inner["market"]["regime"] == "BEAR"

        # 4. Non-dict input
        norm_none = normalize_market_payload(None, data_as_of="2026-09-28")
        assert norm_none["data_as_of"] == "2026-09-28"
        assert norm_none["market"] == {}

        # 5. Nested market.data_as_of differs from authoritative top-level data_as_of
        conflicting = {
            "data_as_of": "2026-09-28",
            "market": {
                "data_as_of": "2026-09-15",
                "regime": "BEAR",
                "confidence": 0.85,
                "metrics": {"vnindex_value": 1780.0, "vnindex_change_pct": -0.25},
            },
        }
        norm_conflicting = normalize_market_payload(conflicting, data_as_of="2026-09-28")
        assert norm_conflicting["data_as_of"] == "2026-09-28"
        assert norm_conflicting["market"]["regime"] == "BEAR"
        assert "data_as_of" not in norm_conflicting["market"]

    def test_missing_performance_data_fails_closed(self):
        """Verify missing performance data in universe_audit fails closed with FAIL status rather than defaulting to PASS."""
        audit_no_perf = copy.deepcopy(self.healthy_audit)
        audit_no_perf["performance"] = None

        res = evaluate_production_monitoring(
            recommendations_payload=self.healthy_payload,
            market_payload=self.healthy_market,
            reference_date=self.reference_date,
            universe_audit=audit_no_perf,
        )

        assert res.overall_status == "FAIL"
        perf_chk = next(c for c in res.checks if c.check_name == "performance_payload_integrity")
        assert perf_chk.status == "FAIL"
        assert "missing" in perf_chk.message.lower()

        reg_chk = next(c for c in res.checks if c.check_name == "performance_regression")
        assert reg_chk.status == "FAIL"

        bud_chk = next(c for c in res.checks if c.check_name == "provider_budget")
        assert bud_chk.status == "FAIL"

    def test_missing_universe_audit_performance_payload_fails_closed(self):
        """Verify when universe_audit is None and recommendations_payload lacks performance, monitoring fails closed."""
        payload_no_perf = copy.deepcopy(self.healthy_payload)

        res = evaluate_production_monitoring(
            recommendations_payload=payload_no_perf,
            market_payload=self.healthy_market,
            reference_date=self.reference_date,
            universe_audit=None,
        )

        assert res.overall_status == "FAIL"
        perf_chk = next(c for c in res.checks if c.check_name == "performance_payload_integrity")
        assert perf_chk.status == "FAIL"

    def test_run_37162713439_reproduction_does_not_fail_monitoring(self):
        """Verify that standard production market_payload structure with data_as_of passes monitoring without false positive FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = os.path.join(tmpdir, "history")
            os.makedirs(hist_dir, exist_ok=True)

            # Test Form A: Flat market_payload dict with data_as_of
            market_payload_flat = copy.deepcopy(self.healthy_market)
            market_payload_flat["data_as_of"] = "2026-09-17"

            with open(os.path.join(tmpdir, "recommendations.json"), "w") as f:
                json.dump(self.healthy_payload, f)
            with open(os.path.join(tmpdir, "market.json"), "w") as f:
                json.dump(market_payload_flat, f)

            baseline_dates = [f"2026-09-{16 - i:02d}" for i in range(5)]
            index_dates = ["2026-09-17"] + baseline_dates
            with open(os.path.join(hist_dir, "index.json"), "w") as f:
                json.dump({"dates": index_dates}, f)

            for d in index_dates:
                b_payload = copy.deepcopy(self.healthy_payload)
                b_payload["data_as_of"] = d
                with open(os.path.join(hist_dir, f"{d}.json"), "w") as f:
                    json.dump(b_payload, f)

            res = evaluate_production_monitoring(
                generated_dir=tmpdir,
                recommendations_payload=self.healthy_payload,
                market_payload=market_payload_flat,
                reference_date=self.reference_date,
                universe_audit=self.healthy_audit,
            )

            failed_checks = [c for c in res.checks if c.status == "FAIL"]
            assert len(failed_checks) == 0, f"Expected 0 failed checks, got: {failed_checks}"
            assert res.overall_status in ("PASS", "WARNING")

            # Test Form B: Standalone market.json wrapper payload with nested "market"
            market_payload_nested = {
                "data_as_of": "2026-09-17",
                "source_date": "2026-09-17",
                "generated_at": "2026-09-17T06:00:00+00:00",
                "data_source": "REAL_DATA",
                "universe_info": {"universe_type": "TEST", "universe_size": 2},
                "market": copy.deepcopy(self.healthy_market),
                "summary": self.healthy_summary,
            }

            res_nested = evaluate_production_monitoring(
                generated_dir=tmpdir,
                recommendations_payload=self.healthy_payload,
                market_payload=market_payload_nested,
                reference_date=self.reference_date,
                universe_audit=self.healthy_audit,
            )

            failed_nested = [c for c in res_nested.checks if c.status == "FAIL"]
            assert len(failed_nested) == 0, (
                f"Expected 0 failed checks for nested market_payload, got: {failed_nested}"
            )
            assert res_nested.overall_status in ("PASS", "WARNING")

    def test_healthy_production_data_passes(self):
        """Verify healthy production data produces overall status 'PASS' when sufficient baseline exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = os.path.join(tmpdir, "history")
            os.makedirs(hist_dir, exist_ok=True)

            with open(os.path.join(tmpdir, "recommendations.json"), "w") as f:
                json.dump(self.healthy_payload, f)
            with open(os.path.join(tmpdir, "market.json"), "w") as f:
                json.dump(self.healthy_market, f)

            baseline_dates = [f"2026-09-{16 - i:02d}" for i in range(5)]
            index_dates = ["2026-09-17"] + baseline_dates
            with open(os.path.join(hist_dir, "index.json"), "w") as f:
                json.dump({"dates": index_dates}, f)

            for d in index_dates:
                b_payload = copy.deepcopy(self.healthy_payload)
                b_payload["data_as_of"] = d
                with open(os.path.join(hist_dir, f"{d}.json"), "w") as f:
                    json.dump(b_payload, f)

            res = evaluate_production_monitoring(
                generated_dir=tmpdir,
                recommendations_payload=self.healthy_payload,
                market_payload=self.healthy_market,
                reference_date=self.reference_date,
                universe_audit=self.healthy_audit,
            )
            assert res.overall_status == "PASS"
            assert res.data_as_of == "2026-09-17"
            assert validate_monitoring_payload(res.to_dict())

    def test_payload_supplied_in_memory_with_missing_artifacts_on_disk_fails(self):
        """Test A: In-memory payload supplied but generated_dir on disk is empty -> FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            res = evaluate_production_monitoring(
                generated_dir=tmpdir,
                recommendations_payload=self.healthy_payload,
                market_payload=self.healthy_market,
                reference_date="2026-09-17",
            )
            check_names = [c.check_name for c in res.checks]
            assert "artifact_existence" in check_names
            art_chk = next(c for c in res.checks if c.check_name == "artifact_existence")
            assert art_chk.status == "FAIL"
            assert res.overall_status == "FAIL"

    def test_payload_supplied_in_memory_but_history_index_missing_on_disk_fails(self):
        """Test B: In-memory payload supplied, recommendations.json and market.json exist, but history/index.json is missing -> FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "recommendations.json"), "w") as f:
                json.dump(self.healthy_payload, f)
            with open(os.path.join(tmpdir, "market.json"), "w") as f:
                json.dump(self.healthy_market, f)

            res = evaluate_production_monitoring(
                generated_dir=tmpdir,
                recommendations_payload=self.healthy_payload,
                market_payload=self.healthy_market,
                reference_date="2026-09-17",
            )
            check_names = [c.check_name for c in res.checks]
            assert "history_index_status" in check_names
            hist_chk = next(c for c in res.checks if c.check_name == "history_index_status")
            assert hist_chk.status == "FAIL"
            assert res.overall_status == "FAIL"

    def test_healthy_artifacts_on_disk_and_payload_in_memory_passes(self):
        """Test C: Healthy artifacts exist on disk AND payload supplied in memory -> PASS."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = os.path.join(tmpdir, "history")
            os.makedirs(hist_dir, exist_ok=True)

            with open(os.path.join(tmpdir, "recommendations.json"), "w") as f:
                json.dump(self.healthy_payload, f)
            with open(os.path.join(tmpdir, "market.json"), "w") as f:
                json.dump(self.healthy_market, f)

            baseline_dates = [f"2026-09-{16 - i:02d}" for i in range(5)]
            index_dates = ["2026-09-17"] + baseline_dates
            with open(os.path.join(hist_dir, "index.json"), "w") as f:
                json.dump({"dates": index_dates}, f)

            for d in index_dates:
                b_payload = copy.deepcopy(self.healthy_payload)
                b_payload["data_as_of"] = d
                with open(os.path.join(hist_dir, f"{d}.json"), "w") as f:
                    json.dump(b_payload, f)

            res = evaluate_production_monitoring(
                generated_dir=tmpdir,
                recommendations_payload=self.healthy_payload,
                market_payload=self.healthy_market,
                reference_date="2026-09-17",
                universe_audit=self.healthy_audit,
            )
            art_chk = next(c for c in res.checks if c.check_name == "artifact_existence")
            hist_chk = next(c for c in res.checks if c.check_name == "history_index_status")

            assert art_chk.status == "PASS"
            assert hist_chk.status == "PASS"
            assert res.overall_status == "PASS"
            # Ensure no duplicated check names
            check_names = [c.check_name for c in res.checks]
            assert len(check_names) == len(set(check_names))

    def test_data_freshness_exact_boundaries(self):
        """Verify exact freshness contract for PASS, WARNING, and FAIL thresholds."""
        # 1. Same date: data_as_of == reference_date -> PASS (0 days old)
        chk_pass = check_data_freshness("2026-09-17", reference_date="2026-09-17")
        assert chk_pass.status == "PASS"
        assert chk_pass.measured_value["staleness_days"] == 0

        # 2. 5 days stale: data_as_of="2026-09-12", reference_date="2026-09-17" -> WARNING
        chk_warn = check_data_freshness("2026-09-12", reference_date="2026-09-17")
        assert chk_warn.status == "WARNING"
        assert chk_warn.measured_value["staleness_days"] == 5

        # 3. 16 days stale: data_as_of="2026-09-01", reference_date="2026-09-17" -> FAIL (> 14 days)
        chk_fail = check_data_freshness("2026-09-01", reference_date="2026-09-17")
        assert chk_fail.status == "FAIL"
        assert chk_fail.measured_value["staleness_days"] == 16

    def test_production_script_does_not_pass_data_as_of_as_reference_date(self):
        """Verify scripts/generate_report.py does NOT pass reference_date=data_as_of."""
        report_script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "scripts",
            "generate_report.py",
        )
        with open(report_script_path, "r", encoding="utf-8") as f:
            code_text = f.read()

        assert "reference_date=data_as_of" not in code_text, (
            "scripts/generate_report.py must NOT pass reference_date=data_as_of to monitoring"
        )

    def test_explicit_reference_date_is_deterministic(self):
        """Verify explicit reference_date yields deterministic monitoring results regardless of system time."""
        res_1 = evaluate_production_monitoring(
            recommendations_payload=self.healthy_payload,
            reference_date="2026-09-17",
        )
        res_2 = evaluate_production_monitoring(
            recommendations_payload=self.healthy_payload,
            reference_date="2026-09-17",
        )
        assert res_1.to_dict() == res_2.to_dict()

    def test_missing_required_artifact_fails(self):
        """Verify missing required JSON artifacts cause check failure ('FAIL') for each artifact."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = os.path.join(tmpdir, "history")
            os.makedirs(hist_dir, exist_ok=True)

            recs_p = os.path.join(tmpdir, "recommendations.json")
            mkt_p = os.path.join(tmpdir, "market.json")
            idx_p = os.path.join(hist_dir, "index.json")
            as_of_p = os.path.join(hist_dir, "2026-09-17.json")

            # Case 1: missing recommendations.json => FAIL
            chk1 = check_required_artifacts(tmpdir, data_as_of="2026-09-17")
            assert chk1.status == "FAIL"
            assert "recommendations.json" in chk1.measured_value["missing"]

            # Create recommendations.json
            with open(recs_p, "w") as f:
                f.write("{}")

            # Case 2: missing market.json => FAIL
            chk2 = check_required_artifacts(tmpdir, data_as_of="2026-09-17")
            assert chk2.status == "FAIL"
            assert "market.json" in chk2.measured_value["missing"]

            # Create market.json
            with open(mkt_p, "w") as f:
                f.write("{}")

            # Case 3: missing history/index.json => FAIL
            chk3 = check_required_artifacts(tmpdir, data_as_of="2026-09-17")
            assert chk3.status == "FAIL"
            assert "index.json" in chk3.measured_value["missing"]

            # Create history/index.json
            with open(idx_p, "w") as f:
                f.write("{}")

            # Case 4: missing history/{data_as_of}.json => FAIL
            chk4 = check_required_artifacts(tmpdir, data_as_of="2026-09-17")
            assert chk4.status == "FAIL"
            assert "2026-09-17.json" in chk4.measured_value["missing"]

            # Create history/{data_as_of}.json
            with open(as_of_p, "w") as f:
                f.write("{}")

            # Case 5: all required artifacts present => PASS
            chk5 = check_required_artifacts(tmpdir, data_as_of="2026-09-17")
            assert chk5.status == "PASS"

    def test_malformed_artifact_fails(self):
        """Verify malformed non-JSON artifact causes check failure ('FAIL')."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_file = os.path.join(tmpdir, "recommendations.json")
            with open(bad_file, "w") as f:
                f.write("{ invalid json payload ...")

            chk = check_required_artifacts(tmpdir)
            assert chk.status == "FAIL"
            assert "Unreadable files" in chk.message

    def test_schema_invalid_artifact_fails(self):
        """Verify schema-invalid payload produces schema validation check failure ('FAIL')."""
        bad_payload = copy.deepcopy(self.healthy_payload)
        del bad_payload["signal_model_version"]  # Missing required top-level key

        chk = check_schema_validation(bad_payload)
        assert chk.status == "FAIL"
        assert "signal_model_version" in chk.message

    def test_summary_action_count_mismatch_fails(self):
        """Verify summary action count mismatch with actual recommendations produces status 'FAIL'."""
        bad_payload = copy.deepcopy(self.healthy_payload)
        # Summary claims 2 BUY, 0 WATCH, but recommendations has 1 BUY and 1 WATCH
        bad_payload["summary"]["buy_count"] = 2
        bad_payload["summary"]["watch_count"] = 0

        chk = check_symbol_processing_counts(bad_payload)
        assert chk.status == "FAIL"
        assert "buy_count" in chk.message

    def test_total_scanned_mismatch_fails(self):
        """Verify total_scanned mismatch with recommendations length produces status 'FAIL'."""
        bad_payload = copy.deepcopy(self.healthy_payload)
        bad_payload["summary"]["total_scanned"] = 5

        chk = check_symbol_processing_counts(bad_payload)
        assert chk.status == "FAIL"
        assert "Summary counts mismatch" in chk.message

    def test_invalid_date_string_in_history_index_fails(self):
        """Verify invalid date string in history index produces status 'FAIL'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = os.path.join(tmpdir, "history")
            os.makedirs(hist_dir, exist_ok=True)
            index_path = os.path.join(hist_dir, "index.json")

            with open(index_path, "w") as f:
                json.dump({"dates": ["2026-02-30", "2026-09-16"]}, f)  # Invalid calendar date

            chk = check_history_index_status(tmpdir)
            assert chk.status == "FAIL"
            assert "invalid date entries" in chk.message.lower()

    def test_missing_history_file_for_index_date_fails(self):
        """Verify date in history index pointing to missing file produces status 'FAIL'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = os.path.join(tmpdir, "history")
            os.makedirs(hist_dir, exist_ok=True)
            index_path = os.path.join(hist_dir, "index.json")

            # Index lists 2026-09-17 and 2026-09-16, but 2026-09-16.json does not exist
            with open(index_path, "w") as f:
                json.dump({"dates": ["2026-09-17", "2026-09-16"]}, f)

            with open(os.path.join(hist_dir, "2026-09-17.json"), "w") as f:
                f.write("{}")

            chk = check_history_index_status(tmpdir)
            assert chk.status == "FAIL"
            assert "missing report files" in chk.message.lower()

    def test_invalid_unsorted_duplicate_data_fails(self):
        """Verify duplicate or unsorted dates in history index fail closed ('FAIL')."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = os.path.join(tmpdir, "history")
            os.makedirs(hist_dir, exist_ok=True)
            index_path = os.path.join(hist_dir, "index.json")

            # Duplicate date entries in index
            with open(index_path, "w") as f:
                json.dump({"dates": ["2026-09-17", "2026-09-17"]}, f)

            with open(os.path.join(hist_dir, "2026-09-17.json"), "w") as f:
                f.write("{}")

            chk = check_history_index_status(tmpdir, data_as_of="2026-09-17")
            assert chk.status == "FAIL"
            assert "duplicate" in chk.message.lower()

            # Unsorted date entries in index
            with open(index_path, "w") as f:
                json.dump({"dates": ["2026-09-16", "2026-09-17"]}, f)

            with open(os.path.join(hist_dir, "2026-09-16.json"), "w") as f:
                f.write("{}")

            chk_unsorted = check_history_index_status(tmpdir, data_as_of="2026-09-17")
            assert chk_unsorted.status == "FAIL"
            assert "descending" in chk_unsorted.message.lower()

    def test_ohlcv_duplicate_and_unsorted_fails(self):
        """Verify duplicate or unsorted dates in OHLCV DataFrame produce check failure ('FAIL')."""
        dates = ["2026-09-17", "2026-09-16", "2026-09-15"]  # Reverse order
        df_unsorted = pd.DataFrame(
            {
                "time": dates,
                "open": [10.0, 10.0, 10.0],
                "high": [11.0, 11.0, 11.0],
                "low": [9.0, 9.0, 9.0],
                "close": [10.5, 10.5, 10.5],
                "volume": [1000, 1000, 1000],
            }
        )
        chk = check_ohlcv_data_quality(df_unsorted, "TEST_SYM")
        assert chk.status == "FAIL"

    def test_expected_insufficient_data_condition(self):
        """Verify expected insufficient-data condition for minority stock is tracked as PASS."""
        insufficient_rec = {
            "symbol": "ABC",
            "company_name": "ABC Corp",
            "exchange": "HOSE",
            "sector": "BĐS",
            "action": "AVOID",
            "data_quality": "INSUFFICIENT",
            "data_quality_issues": ["insufficient_history"],
            "data_as_of": "2026-09-17",
            "data_source": "REAL_DATA",
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

        # 9 out of 10 stocks processed (90% processed ratio)
        large_recs = [self.healthy_recommendations[0]] * 9 + [insufficient_rec]
        payload_large = copy.deepcopy(self.healthy_payload)
        payload_large["recommendations"] = large_recs
        payload_large["summary"] = {
            "total_scanned": 10,
            "buy_count": 9,
            "watch_count": 0,
            "hold_count": 0,
            "sell_count": 0,
            "avoid_count": 1,
        }

        chk_large = check_symbol_processing_counts(payload_large)
        assert chk_large.status == "PASS"
        assert chk_large.measured_value["processed_ratio"] == 0.90

    def test_avoid_with_sufficient_data_quality_not_counted_as_insufficient(self):
        """Verify AVOID action with SUFFICIENT data_quality is NOT counted as insufficient data."""
        avoid_sufficient_rec = copy.deepcopy(self.healthy_recommendations[0])
        avoid_sufficient_rec["symbol"] = "XYZ"
        avoid_sufficient_rec["action"] = "AVOID"
        avoid_sufficient_rec["data_quality"] = "SUFFICIENT"

        payload = copy.deepcopy(self.healthy_payload)
        payload["recommendations"].append(avoid_sufficient_rec)
        payload["summary"] = {
            "total_scanned": 3,
            "buy_count": 1,
            "watch_count": 1,
            "hold_count": 0,
            "sell_count": 0,
            "avoid_count": 1,
        }

        chk = check_symbol_processing_counts(payload)
        assert chk.status == "PASS"
        assert chk.measured_value["insufficient_count"] == 0
        assert chk.measured_value["processed_count"] == 3

    def test_nan_inf_in_market_payload_fails(self):
        """Verify NaN or Inf in market payload causes numeric_sanity check failure ('FAIL')."""
        bad_market = copy.deepcopy(self.healthy_market)
        bad_market["metrics"]["vnindex_value"] = float("nan")

        chk = check_numeric_sanity(self.healthy_payload, market_payload=bad_market)
        assert chk.status == "FAIL"
        assert "NaN" in chk.message

        bad_market_inf = copy.deepcopy(self.healthy_market)
        bad_market_inf["metrics"]["volatility"] = float("inf")

        chk_inf = check_numeric_sanity(self.healthy_payload, market_payload=bad_market_inf)
        assert chk_inf.status == "FAIL"
        assert "Inf" in chk_inf.message

    def test_nan_inf_detection(self):
        """Verify NaN or Inf float values in recommendations payload cause numeric_sanity check failure ('FAIL')."""
        bad_payload = copy.deepcopy(self.healthy_payload)
        bad_payload["recommendations"][0]["signal_score"] = float("nan")

        issues = find_nan_or_inf(bad_payload)
        assert len(issues) > 0

        chk = check_numeric_sanity(bad_payload)
        assert chk.status == "FAIL"
        assert "NaN" in chk.message

        bad_payload_inf = copy.deepcopy(self.healthy_payload)
        bad_payload_inf["recommendations"][0]["risk_metrics"]["var_t25"] = float("inf")

        chk_inf = check_numeric_sanity(bad_payload_inf)
        assert chk_inf.status == "FAIL"
        assert "Inf" in chk_inf.message

    def test_benchmark_ohlcv_checks_executed(self):
        """Verify production monitoring executes benchmark OHLCV checks when DataFrames are passed."""
        dates = pd.date_range("2026-01-01", periods=50, freq="B").strftime("%Y-%m-%d").tolist()
        df_vnindex = pd.DataFrame(
            {
                "time": dates,
                "open": [1200.0] * 50,
                "high": [1210.0] * 50,
                "low": [1190.0] * 50,
                "close": [1205.0] * 50,
                "volume": [500000] * 50,
            }
        )
        df_vn30 = pd.DataFrame(
            {
                "time": dates,
                "open": [1300.0] * 50,
                "high": [1310.0] * 50,
                "low": [1290.0] * 50,
                "close": [1305.0] * 50,
                "volume": [300000] * 50,
            }
        )

        res = evaluate_production_monitoring(
            recommendations_payload=self.healthy_payload,
            reference_date=self.reference_date,
            df_vnindex=df_vnindex,
            df_vn30=df_vn30,
        )

        check_names = [c.check_name for c in res.checks]
        assert "ohlcv_quality_vnindex" in check_names
        assert "ohlcv_quality_vn30" in check_names

        vn_chk = next(c for c in res.checks if c.check_name == "ohlcv_quality_vnindex")
        assert vn_chk.status == "PASS"

    def test_future_data_freshness_fails(self):
        """Verify future data_as_of relative to reference_date causes check failure ('FAIL')."""
        chk = check_data_freshness("2026-09-20", reference_date="2026-09-17")
        assert chk.status == "FAIL"
        assert "future" in chk.message.lower()

    def test_deterministic_serialization(self):
        """Verify CheckResult and PipelineMonitoringResult produce deterministic serializable dicts."""
        chk = CheckResult(
            check_name="test_chk",
            status="PASS",
            measured_value={"score": 10.5, "bad_val": float("nan")},
            expected_condition="condition",
            message="msg",
        )
        d = chk.to_dict()
        assert d["measured_value"]["bad_val"] == "NaN"

        res = evaluate_production_monitoring(
            recommendations_payload=self.healthy_payload,
            reference_date=self.reference_date,
        )
        res_dict1 = res.to_dict()
        res_dict2 = res.to_dict()

        json_str1 = json.dumps(res_dict1, indent=2)
        json_str2 = json.dumps(res_dict2, indent=2)

        assert json_str1 == json_str2

    def test_monitoring_does_not_mutate_payloads(self):
        """Verify monitoring execution does not mutate input recommendation or market payloads."""
        payload_orig = copy.deepcopy(self.healthy_payload)
        payload_copy = copy.deepcopy(self.healthy_payload)

        _res = evaluate_production_monitoring(
            recommendations_payload=payload_copy,
            reference_date=self.reference_date,
        )

        assert payload_copy == payload_orig

    def test_monitoring_does_not_change_signal_or_regime_outputs(self):
        """Verify monitoring layer does not alter recommendation or market regime calculation outputs."""
        dates = pd.date_range("2026-01-01", periods=100, freq="B").strftime("%Y-%m-%d").tolist()
        df_stock = pd.DataFrame(
            {
                "time": dates,
                "open": [100.0] * 100,
                "high": [105.0] * 100,
                "low": [95.0] * 100,
                "close": [102.0] * 100,
                "volume": [10000] * 100,
            }
        )
        df_vnindex = pd.DataFrame(
            {
                "time": dates,
                "open": [1200.0] * 100,
                "high": [1210.0] * 100,
                "low": [1190.0] * 100,
                "close": [1205.0] * 100,
                "volume": [500000] * 100,
            }
        )

        regime_1 = detect_market_regime(df_vnindex=df_vnindex, breadth_ratio=0.60)
        rec_1 = generate_single_recommendation(
            symbol="FPT",
            company_name="FPT Corp",
            sector="Tech",
            exchange="HOSE",
            df_stock=df_stock,
            market_regime_info=regime_1,
            df_vnindex=df_vnindex,
        )

        # Run monitoring
        payload = {
            "schema_version": "2.0",
            "signal_model_version": SIGNAL_MODEL_VERSION,
            "generated_at": "2026-09-17T06:00:00+00:00",
            "data_as_of": "2026-09-17",
            "source_date": "2026-09-17",
            "data_source": "REAL_DATA",
            "universe_info": {"universe_type": "TEST", "universe_size": 1},
            "market": regime_1,
            "summary": {
                "total_scanned": 1,
                "buy_count": 1 if rec_1["action"] == "BUY" else 0,
                "watch_count": 1 if rec_1["action"] == "WATCH" else 0,
                "hold_count": 1 if rec_1["action"] == "HOLD" else 0,
                "sell_count": 1 if rec_1["action"] == "SELL" else 0,
                "avoid_count": 1 if rec_1["action"] == "AVOID" else 0,
            },
            "recommendations": [rec_1],
        }

        _mon_res = evaluate_production_monitoring(
            recommendations_payload=payload, reference_date="2026-09-17"
        )

        # Re-compute outputs to verify immutability and identity
        regime_2 = detect_market_regime(df_vnindex=df_vnindex, breadth_ratio=0.60)
        rec_2 = generate_single_recommendation(
            symbol="FPT",
            company_name="FPT Corp",
            sector="Tech",
            exchange="HOSE",
            df_stock=df_stock,
            market_regime_info=regime_2,
            df_vnindex=df_vnindex,
        )

        assert regime_1 == regime_2
        assert rec_1 == rec_2
