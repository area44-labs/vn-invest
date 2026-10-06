"""Schema validation and versioned schema registry contract tests."""

import json
import os
import unittest

import jsonschema

from scripts.artifacts.publisher import ArtifactPublisher
from scripts.pipeline.validation import (
    load_performance_schema,
    load_schema,
    validate_final_payload_integrity,
)
from scripts.schema import (
    SchemaResolutionError,
    load_schema_for_version,
    resolve_schema,
)


class TestSchemaValidation(unittest.TestCase):
    def test_generated_recommendations_schema(self):
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        schema_path = os.path.join(root_dir, "schemas", "recommendations.schema.json")
        data_path = os.path.join(root_dir, "generated", "recommendations.json")

        self.assertTrue(os.path.exists(schema_path), f"Schema file not found: {schema_path}")

        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)

        if os.path.exists(data_path):
            with open(data_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            jsonschema.validate(instance=data, schema=schema)


class TestVersionedSchemaRegistry(unittest.TestCase):
    """Deterministic unit tests for versioned schema registry and resolution."""

    def test_supported_versions_resolution(self):
        """1. Verify recommendations and performance v2.0 resolve correctly."""
        rec_schema = resolve_schema("recommendations", "2.0")
        self.assertIsInstance(rec_schema, dict)
        self.assertEqual(rec_schema.get("title"), "VnInvestRecommendationsSchema")

        perf_schema = resolve_schema("performance", "2.0")
        self.assertIsInstance(perf_schema, dict)
        self.assertEqual(
            perf_schema.get("title"), "VN Invest Production Performance Payload Schema"
        )

        # Verify helper functions delegate properly
        self.assertEqual(load_schema("2.0"), rec_schema)
        self.assertEqual(load_performance_schema("2.0"), perf_schema)

    def test_unsupported_versions_rejected(self):
        """2. Verify unsupported versions (1.0, 9.9) are strictly rejected with SchemaResolutionError."""
        with self.assertRaises(SchemaResolutionError) as cm_1:
            resolve_schema("recommendations", "1.0")
        self.assertIn("Unsupported schema version '1.0'", str(cm_1.exception))

        with self.assertRaises(SchemaResolutionError) as cm_9:
            resolve_schema("recommendations", "9.9")
        self.assertIn("Unsupported schema version '9.9'", str(cm_9.exception))

        with self.assertRaises(SchemaResolutionError) as cm_perf:
            resolve_schema("performance", "1.0")
        self.assertIn("Unsupported schema version '1.0'", str(cm_perf.exception))

    def test_invalid_versions_rejected(self):
        """3. Verify None, empty string, or whitespace version parameters are rejected."""
        with self.assertRaises(SchemaResolutionError):
            resolve_schema("recommendations", None)

        with self.assertRaises(SchemaResolutionError):
            resolve_schema("recommendations", "")

        with self.assertRaises(SchemaResolutionError):
            resolve_schema("recommendations", "   ")

        with self.assertRaises(SchemaResolutionError):
            resolve_schema("", "2.0")

    def test_validation_routing(self):
        """4. Verify that changing artifact declared schema_version routes to schema resolution and fails on unknown versions."""
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

        schema_2_0 = load_schema(valid_rec_payload["schema_version"])
        validate_final_payload_integrity(valid_rec_payload, schema=schema_2_0)

        # Resolving schema for 9.9 raises SchemaResolutionError
        with self.assertRaises(SchemaResolutionError) as cm:
            load_schema("9.9")
        self.assertIn("Unsupported schema version '9.9'", str(cm.exception))

    def test_publisher_schema_version_enforcement(self):
        """5. Verify ArtifactPublisher uses version-aware validation and rejects artifacts missing or having unregistered schema_version."""
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
        }

        # Valid performance artifact passes validation
        publisher.validate_artifact("performance.json", valid_perf_payload)

        # Missing schema_version fails closed via schema validation
        no_ver_perf = dict(valid_perf_payload)
        del no_ver_perf["schema_version"]
        with self.assertRaises(jsonschema.ValidationError) as cm_no_ver:
            publisher.validate_artifact("performance.json", no_ver_perf)
        self.assertIn("schema_version", str(cm_no_ver.exception))

        # Unsupported schema_version fails closed
        bad_ver_perf = dict(valid_perf_payload, schema_version="3.0")
        with self.assertRaises(SchemaResolutionError) as cm_bad_ver:
            publisher.validate_artifact("performance.json", bad_ver_perf)
        self.assertIn("Unsupported schema version '3.0'", str(cm_bad_ver.exception))

    def test_no_latest_schema_fallback(self):
        """6. Prove an unknown schema version never silently falls back to the default/latest schema."""
        with self.assertRaises(SchemaResolutionError):
            load_schema_for_version("recommendations", "unknown_ver_99")

        with self.assertRaises(SchemaResolutionError):
            load_schema_for_version("performance", "unknown_ver_99")


if __name__ == "__main__":
    unittest.main()
