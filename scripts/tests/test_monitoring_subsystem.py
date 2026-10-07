"""Deterministic unit and integration tests for the Decomposed Monitoring Subsystem (scripts/monitoring/).

Verifies:
1. Subsystem module decomposition and clean internal contracts.
2. Output schema, invariant structure, and payload integrity preservation.
3. Monitoring fail-safe isolation (monitoring logic does not mutate business/quantitative calculations).
"""

import json
import os
import tempfile

import pytest

from scripts.monitoring.evaluator import (
    evaluate_production_monitoring,
)
from scripts.monitoring.metrics import (
    classify_confidence_bucket,
    is_canonical_yyyy_mm_dd,
    normalize_market_payload,
)
from scripts.monitoring.models import (
    CheckResult,
    PipelineMonitoringResult,
    _sanitize_value_for_json,
    find_nan_or_inf,
)
from scripts.monitoring.performance import (
    create_default_performance_payload,
    load_performance_schema,
    validate_performance_payload,
)


@pytest.mark.unit
class TestMonitoringSubsystem:
    """Unit test suite for decomposed scripts.monitoring components."""

    def test_canonical_date_validation(self):
        """Verify date format check utility."""
        assert is_canonical_yyyy_mm_dd("2026-03-31")
        assert not is_canonical_yyyy_mm_dd("2026-3-31")
        assert not is_canonical_yyyy_mm_dd("2026-02-29")  # invalid leap year for 2026
        assert not is_canonical_yyyy_mm_dd(True)
        assert not is_canonical_yyyy_mm_dd(None)

    def test_confidence_bucket_classification(self):
        """Verify confidence score bucket classification."""
        assert classify_confidence_bucket(0.0) == "0.0-0.1"
        assert classify_confidence_bucket(0.55) == "0.5-0.6"
        assert classify_confidence_bucket(1.0) == "0.9-1.0"
        assert classify_confidence_bucket(None) is None
        with pytest.raises(ValueError):
            classify_confidence_bucket(1.5)

    def test_json_sanitization(self):
        """Verify NaN/Inf sanitization for JSON serialization."""
        data = {"a": float("nan"), "b": [float("inf"), float("-inf"), 1.23]}
        sanitized = _sanitize_value_for_json(data)
        assert sanitized["a"] == "NaN"
        assert sanitized["b"] == ["Inf", "-Inf", 1.23]

        nan_issues = find_nan_or_inf(data)
        assert len(nan_issues) == 3

    def test_check_result_models(self):
        """Verify dataclasses validate check statuses."""
        ck = CheckResult(
            check_name="test_check",
            status="PASS",
            measured_value=10,
            expected_condition=">0",
            message="Passed",
        )
        assert ck.to_dict()["status"] == "PASS"

        with pytest.raises(ValueError):
            CheckResult(
                check_name="invalid",
                status="UNKNOWN_STATUS",
                measured_value=0,
                expected_condition="",
                message="",
            )

    def test_normalize_market_payload(self):
        """Verify normalization of market payload shapes."""
        raw = {"regime": "BULLISH", "data_as_of": "2026-03-30", "metrics": {}}
        norm = normalize_market_payload(raw, data_as_of="2026-03-30")
        assert norm["data_as_of"] == "2026-03-30"
        assert norm["market"]["regime"] == "BULLISH"
        assert "data_as_of" not in norm["market"]

    def test_performance_schema_loading_and_validation(self):
        """Verify performance schema validation in performance module."""
        schema = load_performance_schema()
        assert isinstance(schema, dict)

        payload = create_default_performance_payload()
        assert "stages" in payload
        validate_performance_payload(payload)


@pytest.mark.unit
class TestMonitoringFailSafeAndIsolation:
    """Verify monitoring subsystem isolation and fail-closed behaviors."""

    def test_evaluate_production_monitoring_missing_payload_fail_closed(self):
        """Verify missing payload causes evaluate_production_monitoring to return overall_status == FAIL without crashing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            res = evaluate_production_monitoring(generated_dir=tmpdir)
            assert isinstance(res, PipelineMonitoringResult)
            assert res.overall_status == "FAIL"
            assert "error" in res.metrics

    def test_monitoring_failure_does_not_mutate_business_payloads(self):
        """Verify that running monitoring checks does not mutate input recommendation or market payloads."""
        rec_payload = {
            "schema_version": "v1.0",
            "signal_model_version": "v2.0",
            "generated_at": "2026-03-31T00:00:00Z",
            "data_as_of": "2026-03-31",
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
                    "symbol": "VNM",
                    "action": "BUY",
                    "data_quality": "SUFFICIENT",
                    "signal_score": 85.0,
                    "risk_adjusted_score": 80.0,
                    "confidence": 0.9,
                }
            ],
        }
        rec_payload_copy = json.loads(json.dumps(rec_payload))

        market_payload = {
            "data_as_of": "2026-03-31",
            "market": {
                "regime": "UPTREND",
                "confidence": 0.85,
                "metrics": {
                    "vnindex_value": 1250.0,
                    "vnindex_change_pct": 1.2,
                    "market_breadth_ratio": 0.65,
                },
            },
        }
        market_payload_copy = json.loads(json.dumps(market_payload))

        with tempfile.TemporaryDirectory() as tmpdir:
            # Setup dummy history index so artifact existence check passes history
            hist_dir = os.path.join(tmpdir, "history")
            os.makedirs(hist_dir, exist_ok=True)
            with open(os.path.join(hist_dir, "index.json"), "w", encoding="utf-8") as f:
                json.dump({"dates": ["2026-03-31"]}, f)
            with open(os.path.join(hist_dir, "2026-03-31.json"), "w", encoding="utf-8") as f:
                json.dump(rec_payload, f)

            res = evaluate_production_monitoring(
                generated_dir=tmpdir,
                recommendations_payload=rec_payload,
                market_payload=market_payload,
                reference_date="2026-03-31",
            )

            assert isinstance(res, PipelineMonitoringResult)
            assert rec_payload == rec_payload_copy
            assert market_payload == market_payload_copy
