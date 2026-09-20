"""Schema validation and contract synchronization tests using jsonschema."""

import json
import os
import re
import unittest

import jsonschema
from scripts.lib.config import SIGNAL_MODEL_VERSION, VALID_MARKET_REGIMES


class TestSchemaValidation(unittest.TestCase):
    def setUp(self):
        self.root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.schema_path = os.path.join(self.root_dir, "schemas", "recommendations.schema.json")
        self.ts_type_path = os.path.join(self.root_dir, "src", "types", "recommendation.ts")
        self.data_path = os.path.join(self.root_dir, "generated", "recommendations.json")

    def test_generated_recommendations_schema(self):
        self.assertTrue(os.path.exists(self.schema_path), f"Schema file not found: {self.schema_path}")

        with open(self.schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)

        if os.path.exists(self.data_path):
            with open(self.data_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            jsonschema.validate(instance=data, schema=schema)

    def test_python_valid_regimes_match_schema_and_typescript_contract(self):
        """Contract test: Verify VALID_MARKET_REGIMES matches schema enum and TS types."""
        with open(self.schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)

        schema_regimes = set(schema["properties"]["market"]["properties"]["regime"]["enum"])
        self.assertEqual(
            VALID_MARKET_REGIMES,
            schema_regimes,
            f"Python VALID_MARKET_REGIMES {VALID_MARKET_REGIMES} != Schema regimes {schema_regimes}",
        )

        # Check TypeScript type file
        with open(self.ts_type_path, "r", encoding="utf-8") as f:
            ts_code = f.read()

        for regime in VALID_MARKET_REGIMES:
            self.assertIn(
                f'"{regime}"',
                ts_code,
                f"MarketRegime '{regime}' missing from src/types/recommendation.ts",
            )

    def test_signal_model_version_contract_consistency(self):
        """Contract test: Verify SIGNAL_MODEL_VERSION is documented in schema and TS types."""
        with open(self.schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)

        self.assertIn(
            "signal_model_version",
            schema["properties"],
            "signal_model_version missing from recommendations.schema.json properties",
        )

        with open(self.ts_type_path, "r", encoding="utf-8") as f:
            ts_code = f.read()

        self.assertIn(
            "signal_model_version",
            ts_code,
            "signal_model_version missing from src/types/recommendation.ts",
        )


if __name__ == "__main__":
    unittest.main()
