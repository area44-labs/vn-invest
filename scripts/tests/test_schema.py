"""Schema validation tests using jsonschema."""

import json
import os
import unittest

import jsonschema


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


if __name__ == "__main__":
    unittest.main()
