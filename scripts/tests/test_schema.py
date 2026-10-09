"""Schema validation and versioned schema registry contract tests."""

import json
import os
from unittest.mock import patch

import jsonschema
import pytest

from scripts.artifacts.publisher import ArtifactPublisher
from scripts.monitoring.checks import check_schema_validation
from scripts.pipeline.validation import (
    load_performance_schema,
    load_schema,
    validate_final_payload_integrity,
    validate_performance_payload,
)
from scripts.schema import (
    SchemaResolutionError,
    load_schema_for_version,
    resolve_schema,
)


@pytest.mark.unit
class TestSchemaValidation:
    def test_generated_recommendations_schema(self):
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        schema_path = os.path.join(root_dir, "schemas", "v2", "recommendations.schema.json")
        data_path = os.path.join(root_dir, "generated", "recommendations.json")

        assert os.path.exists(schema_path), f"Schema file not found: {schema_path}"

        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)

        if os.path.exists(data_path):
            with open(data_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            jsonschema.validate(instance=data, schema=schema)


@pytest.mark.unit
class TestVersionedSchemaRegistry:
    """Deterministic unit tests for versioned schema registry and resolution."""

    def test_supported_versions_resolution(self):
        """Verify recommendations and performance v2.0 resolve correctly."""
        rec_schema = resolve_schema("recommendations", "2.0")
        assert isinstance(rec_schema, dict)
        assert rec_schema.get("title") == "VN Invest Recommendations Schema"

        perf_schema = resolve_schema("performance", "2.0")
        assert isinstance(perf_schema, dict)
        assert perf_schema.get("title") == "VN Invest Production Performance Payload Schema"

        # Verify helper functions delegate properly
        assert load_schema("2.0") == rec_schema
        assert load_performance_schema("2.0") == perf_schema

    def test_unsupported_versions_rejected(self):
        """Verify unsupported versions (1.0, 9.9) are strictly rejected with SchemaResolutionError."""
        with pytest.raises(SchemaResolutionError) as cm_1:
            resolve_schema("recommendations", "1.0")
        assert "Unsupported schema version '1.0'" in str(cm_1.value)

        with pytest.raises(SchemaResolutionError) as cm_9:
            resolve_schema("recommendations", "9.9")
        assert "Unsupported schema version '9.9'" in str(cm_9.value)

        with pytest.raises(SchemaResolutionError) as cm_perf:
            resolve_schema("performance", "1.0")
        assert "Unsupported schema version '1.0'" in str(cm_perf.value)

    def test_invalid_versions_rejected(self):
        """Verify None, empty string, or whitespace version parameters are rejected."""
        with pytest.raises(SchemaResolutionError):
            resolve_schema("recommendations", None)

        with pytest.raises(SchemaResolutionError):
            resolve_schema("recommendations", "")

        with pytest.raises(SchemaResolutionError):
            resolve_schema("recommendations", "   ")

        with pytest.raises(SchemaResolutionError):
            resolve_schema("", "2.0")

    def test_validation_routing(self):
        """Verify that changing artifact declared schema_version routes to schema resolution and fails on unknown versions."""
        valid_rec_payload = {
            "schema_version": "2.0",
            "signal_model_version": "2.0",
            "generated_at": "2026-10-06T12:00:00Z",
            "data_as_of": "2026-10-06",
            "source_date": "2026-10-06",
            "market": {
                "regime": "BULL",
                "confidence": 0.9,
                "metrics": {"vnindex_value": 1250.0, "vnindex_change_pct": 0.01},
            },
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

        validate_final_payload_integrity(valid_rec_payload)

        # Resolving schema for 9.9 raises SchemaResolutionError
        with pytest.raises(SchemaResolutionError) as cm:
            load_schema("9.9")
        assert "Unsupported schema version '9.9'" in str(cm.value)

    def test_publisher_schema_version_enforcement(self):
        """Verify ArtifactPublisher uses version-aware validation and rejects artifacts missing or having unregistered schema_version."""
        publisher = ArtifactPublisher(strict_provenance=False)

        valid_perf_payload = {
            "schema_version": "2.0",
            "stages": [{"stage": "pipeline", "elapsed_seconds": 0.5, "status": "SUCCESS"}],
            "provider": {
                "total_calls": 1,
                "successful_calls": 1,
                "failed_calls": 0,
                "retry_count": 0,
                "total_elapsed_seconds": 0.2,
                "average_call_seconds": 0.2,
                "calls_by_source": {"vnstock": 1},
            },
            "duplicate_operations": [],
            "workload": {
                "benchmark_request_count": 1,
                "stock_request_count": 0,
                "total_request_count": 1,
                "requested_symbols": ["VNINDEX"],
            },
        }

        # Valid performance artifact passes validation
        publisher.validate_artifact("performance.json", valid_perf_payload)

        # Missing schema_version fails closed via SchemaResolutionError
        no_ver_perf = dict(valid_perf_payload)
        del no_ver_perf["schema_version"]
        with pytest.raises(SchemaResolutionError) as cm_no_ver:
            publisher.validate_artifact("performance.json", no_ver_perf)
        assert "missing required" in str(cm_no_ver.value)

        # Unsupported schema_version fails closed
        bad_ver_perf = dict(valid_perf_payload, schema_version="3.0")
        with pytest.raises(SchemaResolutionError) as cm_bad_ver:
            publisher.validate_artifact("performance.json", bad_ver_perf)
        assert "Unsupported schema version '3.0'" in str(cm_bad_ver.value)

    def test_no_latest_schema_fallback(self):
        """Prove an unknown schema version never silently falls back to the default/latest schema."""
        with pytest.raises(SchemaResolutionError):
            load_schema_for_version("recommendations", "unknown_ver_99")

        with pytest.raises(SchemaResolutionError):
            load_schema_for_version("performance", "unknown_ver_99")

    def test_performance_validation_routes_through_registry(self):
        """Verify validate_performance_payload routes through schema registry and fails closed on missing or unknown version."""
        valid_perf = {
            "schema_version": "2.0",
            "stages": [{"stage": "pipeline", "elapsed_seconds": 0.5, "status": "SUCCESS"}],
            "provider": {
                "total_calls": 1,
                "successful_calls": 1,
                "failed_calls": 0,
                "retry_count": 0,
                "total_elapsed_seconds": 0.2,
                "average_call_seconds": 0.2,
                "calls_by_source": {"vnstock": 1},
            },
            "duplicate_operations": [],
            "workload": {
                "benchmark_request_count": 1,
                "stock_request_count": 0,
                "total_request_count": 1,
                "requested_symbols": ["VNINDEX"],
            },
        }

        # Valid 2.0 performance payload passes
        validate_performance_payload(valid_perf)

        # Performance payload with missing schema_version raises SchemaResolutionError
        no_ver_perf = dict(valid_perf)
        del no_ver_perf["schema_version"]
        with pytest.raises(SchemaResolutionError) as cm_missing:
            validate_performance_payload(no_ver_perf)
        assert "missing required" in str(cm_missing.value)

        # Performance payload with unsupported schema_version raises SchemaResolutionError
        bad_ver_perf = dict(valid_perf, schema_version="9.9")
        with pytest.raises(SchemaResolutionError) as cm_unsupported:
            validate_performance_payload(bad_ver_perf)
        assert "Unsupported schema version '9.9'" in str(cm_unsupported.value)

    def test_check_schema_validation_version_enforcement(self):
        """Verify check_schema_validation fail-closed enforcement across all schema_version values."""
        valid_payload = {
            "schema_version": "2.0",
            "signal_model_version": "2.0",
            "generated_at": "2026-10-06T12:00:00Z",
            "data_as_of": "2026-10-06",
            "source_date": "2026-10-06",
            "market": {
                "regime": "BULL",
                "confidence": 0.9,
                "metrics": {"vnindex_value": 1250.0, "vnindex_change_pct": 0.01},
            },
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

        # Valid 2.0 passes
        res_20 = check_schema_validation(valid_payload)
        assert res_20.status == "PASS"

        # Missing schema_version -> FAIL
        p_missing = dict(valid_payload)
        del p_missing["schema_version"]
        res_missing = check_schema_validation(p_missing)
        assert res_missing.status == "FAIL"

        # None -> FAIL
        res_none = check_schema_validation(dict(valid_payload, schema_version=None))
        assert res_none.status == "FAIL"

        # Empty string "" -> FAIL
        res_empty = check_schema_validation(dict(valid_payload, schema_version=""))
        assert res_empty.status == "FAIL"

        # Whitespace "   " -> FAIL
        res_space = check_schema_validation(dict(valid_payload, schema_version="   "))
        assert res_space.status == "FAIL"

        # Unsupported "1.0" -> FAIL
        res_10 = check_schema_validation(dict(valid_payload, schema_version="1.0"))
        assert res_10.status == "FAIL"

        # Unsupported "9.9" -> FAIL
        res_99 = check_schema_validation(dict(valid_payload, schema_version="9.9"))
        assert res_99.status == "FAIL"

    def test_custom_schema_path_cannot_bypass_registry(self):
        """Verify check_schema_validation refuses extra parameters and fails closed on unsupported version."""
        valid_payload = {
            "schema_version": "9.9",  # Unsupported version
            "recommendations": [],
        }

        res = check_schema_validation(valid_payload)
        assert res.status == "FAIL"

    @patch("scripts.schema.load_schema_for_version")
    def test_registry_routing_integration(self, mock_load_schema):
        """Prove monitoring checks, publisher, and pipeline validation actually invoke the central schema registry."""
        mock_load_schema.return_value = resolve_schema("recommendations", "2.0")

        valid_payload = {
            "schema_version": "2.0",
            "signal_model_version": "2.0",
            "generated_at": "2026-10-06T12:00:00Z",
            "data_as_of": "2026-10-06",
            "source_date": "2026-10-06",
            "market": {
                "regime": "BULL",
                "confidence": 0.9,
                "metrics": {"vnindex_value": 1250.0, "vnindex_change_pct": 0.01},
            },
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

        res = check_schema_validation(valid_payload)
        assert res.status == "PASS"
        mock_load_schema.assert_called_with("recommendations", "2.0")

        # Prove ArtifactPublisher.validate_artifact calls load_schema_for_version
        publisher = ArtifactPublisher(strict_provenance=False)
        publisher.validate_artifact("recommendations.json", valid_payload)
        mock_load_schema.assert_called_with("recommendations", "2.0")

    @patch("scripts.pipeline.validation.load_schema_for_version")
    def test_validate_performance_payload_calls_registry(self, mock_load_perf_schema):
        """Prove validate_performance_payload calls central registry with payload's schema_version."""
        mock_load_perf_schema.return_value = resolve_schema("performance", "2.0")

        valid_perf = {
            "schema_version": "2.0",
            "stages": [{"stage": "pipeline", "elapsed_seconds": 0.5, "status": "SUCCESS"}],
            "provider": {
                "total_calls": 1,
                "successful_calls": 1,
                "failed_calls": 0,
                "retry_count": 0,
                "total_elapsed_seconds": 0.2,
                "average_call_seconds": 0.2,
                "calls_by_source": {"vnstock": 1},
            },
            "duplicate_operations": [],
            "workload": {
                "benchmark_request_count": 1,
                "stock_request_count": 0,
                "total_request_count": 1,
                "requested_symbols": ["VNINDEX"],
            },
        }

        validate_performance_payload(valid_perf)
        mock_load_perf_schema.assert_called_with("performance", "2.0")

    def test_caller_supplied_schema_or_version_or_path_cannot_override_or_bypass(self):
        """Directly that caller-supplied schema, version, or schema_path parameters raise TypeError."""
        valid_perf = {
            "schema_version": "2.0",
            "stages": [{"stage": "pipeline", "elapsed_seconds": 0.5, "status": "SUCCESS"}],
            "provider": {
                "total_calls": 1,
                "successful_calls": 1,
                "failed_calls": 0,
                "retry_count": 0,
                "total_elapsed_seconds": 0.2,
                "average_call_seconds": 0.2,
                "calls_by_source": {"vnstock": 1},
            },
            "duplicate_operations": [],
            "workload": {
                "benchmark_request_count": 1,
                "stock_request_count": 0,
                "total_request_count": 1,
                "requested_symbols": ["VNINDEX"],
            },
        }

        valid_rec = {
            "schema_version": "2.0",
            "signal_model_version": "2.0",
            "generated_at": "2026-10-06T12:00:00Z",
            "data_as_of": "2026-10-06",
            "source_date": "2026-10-06",
            "market": {
                "regime": "BULL",
                "confidence": 0.9,
                "metrics": {"vnindex_value": 1250.0, "vnindex_change_pct": 0.01},
            },
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

        fake_schema = {"type": "object", "properties": {}}

        # Attempt passing schema, version, schema_path to validate_performance_payload -> TypeError
        with pytest.raises(TypeError):
            validate_performance_payload(valid_perf, schema=fake_schema)  # type: ignore[call-arg]

        with pytest.raises(TypeError):
            validate_performance_payload(valid_perf, version="1.0")  # type: ignore[call-arg]

        with pytest.raises(TypeError):
            validate_performance_payload(valid_perf, schema_path="/tmp/fake.json")  # type: ignore[call-arg]

        # Attempt passing schema, version, schema_path to check_schema_validation -> TypeError
        with pytest.raises(TypeError):
            check_schema_validation(valid_rec, schema=fake_schema)  # type: ignore[call-arg]

        with pytest.raises(TypeError):
            check_schema_validation(valid_rec, version="1.0")  # type: ignore[call-arg]

        with pytest.raises(TypeError):
            check_schema_validation(valid_rec, schema_path="/tmp/fake.json")  # type: ignore[call-arg]

        # Attempt passing schema, version, schema_path to validate_final_payload_integrity -> TypeError
        with pytest.raises(TypeError):
            validate_final_payload_integrity(valid_rec, schema=fake_schema)  # type: ignore[call-arg]

        with pytest.raises(TypeError):
            validate_final_payload_integrity(valid_rec, version="1.0")  # type: ignore[call-arg]

        with pytest.raises(TypeError):
            validate_final_payload_integrity(valid_rec, schema_path="/tmp/fake.json")  # type: ignore[call-arg]

        # Attempt passing schema, version, schema_path to ArtifactPublisher.validate_artifact -> TypeError
        publisher = ArtifactPublisher(strict_provenance=False)
        with pytest.raises(TypeError):
            publisher.validate_artifact("recommendations.json", valid_rec, schema=fake_schema)  # type: ignore[call-arg]

        with pytest.raises(TypeError):
            publisher.validate_artifact("recommendations.json", valid_rec, version="1.0")  # type: ignore[call-arg]

        with pytest.raises(TypeError):
            publisher.validate_artifact(
                "recommendations.json", valid_rec, schema_path="/tmp/fake.json"
            )  # type: ignore[call-arg]

    @patch("scripts.pipeline.validation.load_schema_for_version")
    @patch("scripts.schema.load_schema_for_version")
    def test_publisher_always_resolves_via_registry_for_all_schema_governed_artifacts(
        self, mock_load_schema_registry, mock_load_schema_pipeline
    ):
        """Prove ArtifactPublisher always resolves schema via central registry using payload's schema_version."""
        mock_load_schema_registry.side_effect = lambda art_type, ver: resolve_schema(art_type, ver)
        mock_load_schema_pipeline.side_effect = lambda art_type, ver: resolve_schema(art_type, ver)

        publisher = ArtifactPublisher(strict_provenance=False)

        valid_perf = {
            "schema_version": "2.0",
            "stages": [{"stage": "pipeline", "elapsed_seconds": 0.5, "status": "SUCCESS"}],
            "provider": {
                "total_calls": 1,
                "successful_calls": 1,
                "failed_calls": 0,
                "retry_count": 0,
                "total_elapsed_seconds": 0.2,
                "average_call_seconds": 0.2,
                "calls_by_source": {"vnstock": 1},
            },
            "duplicate_operations": [],
            "workload": {
                "benchmark_request_count": 1,
                "stock_request_count": 0,
                "total_request_count": 1,
                "requested_symbols": ["VNINDEX"],
            },
        }

        valid_rec = {
            "schema_version": "2.0",
            "signal_model_version": "2.0",
            "generated_at": "2026-10-06T12:00:00Z",
            "data_as_of": "2026-10-06",
            "source_date": "2026-10-06",
            "market": {
                "regime": "BULL",
                "confidence": 0.9,
                "metrics": {"vnindex_value": 1250.0, "vnindex_change_pct": 0.01},
            },
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

        # Performance artifact
        publisher.validate_artifact("performance.json", valid_perf)
        mock_load_schema_pipeline.assert_called_with("performance", "2.0")

        # Recommendations artifact
        publisher.validate_artifact("recommendations.json", valid_rec)
        mock_load_schema_registry.assert_called_with("recommendations", "2.0")

        # History report artifact
        publisher.validate_artifact("history/2026-10-06.json", valid_rec)
        mock_load_schema_registry.assert_called_with("recommendations", "2.0")
