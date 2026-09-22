"""Unit tests for fail-closed history index persistence loader."""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.generate_report import GENERATED_DIR, load_history_index, update_history_index

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


class TestHistoryIndexLoader(unittest.TestCase):
    """Test suite for history index loader and updater fail-closed semantics."""

    def setUp(self):
        history_dir = os.path.join(GENERATED_DIR, "history")
        os.makedirs(history_dir, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=history_dir)
        self.addCleanup(self.temp_dir.cleanup)
        self.index_path = os.path.join(self.temp_dir.name, "index.json")

    def test_1_missing_file_returns_initialized_empty_index(self):
        """Test 1: Non-existent history index file initializes an empty index contract."""
        self.assertFalse(os.path.exists(self.index_path))
        data = load_history_index(self.index_path)
        self.assertEqual(data, {"dates": []})

    def test_2_valid_index_loads_successfully(self):
        """Test 2: Valid JSON and expected structure loads successfully."""
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        valid_payload = {
            "last_updated": "2026-09-14T04:11:09.418616+00:00",
            "total_reports": 2,
            "dates": ["2026-09-14", "2026-09-13"],
        }
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(valid_payload, f)

        data = load_history_index(self.index_path)
        self.assertEqual(data["dates"], ["2026-09-14", "2026-09-13"])
        self.assertEqual(data["total_reports"], 2)

    def test_3_malformed_json_raises(self):
        """Test 3: Existing file with invalid JSON raises ValueError with file path context."""
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        with open(self.index_path, "w", encoding="utf-8") as f:
            f.write("{ corrupted_json: true, ")

        with self.assertRaises(ValueError) as ctx:
            load_history_index(self.index_path)

        self.assertIn("invalid JSON", str(ctx.exception))
        self.assertIn(self.index_path, str(ctx.exception))

    def test_4_invalid_root_type_raises(self):
        """Test 4: Valid JSON with non-object root type (array, string, int, null) raises TypeError or ValueError."""
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)

        for invalid_root in ['[ "2026-09-14" ]', "null", '"2026-09-14"', "123"]:
            with open(self.index_path, "w", encoding="utf-8") as f:
                f.write(invalid_root)

            with self.assertRaises((ValueError, TypeError)) as ctx:
                load_history_index(self.index_path)

            self.assertIn("Invalid history index structure", str(ctx.exception))
            self.assertIn(self.index_path, str(ctx.exception))

    def test_5_invalid_structure_raises(self):
        """Test 5: Valid JSON object with invalid or missing 'dates' structure raises TypeError or ValueError."""
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)

        invalid_structures = [
            {"wrong_field": "2026-09-14"},
            {"dates": "2026-09-14"},  # not a list
            {"dates": [123, "2026-09-14"]},  # non-string item in list
            {"dates": None},  # null dates
        ]

        for payload in invalid_structures:
            with open(self.index_path, "w", encoding="utf-8") as f:
                json.dump(payload, f)

            with self.assertRaises((ValueError, TypeError)) as ctx:
                load_history_index(self.index_path)

            self.assertIn("Invalid history index structure", str(ctx.exception))
            self.assertIn(self.index_path, str(ctx.exception))

    def test_6_permission_read_failure_raises(self):
        """Test 6: Read/Permission filesystem failures raise OSError and are NOT converted into empty index."""
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump({"dates": ["2026-09-14"]}, f)

        with patch("builtins.open", side_effect=PermissionError("Permission denied")):
            with self.assertRaises((PermissionError, OSError)) as ctx:
                load_history_index(self.index_path)

            self.assertIn("Permission denied", str(ctx.exception))

    def test_7_corrupted_file_is_not_overwritten(self):
        """Test 7: Updating history index with an existing corrupted file raises and leaves original file untouched."""
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        corrupted_content = "CORRUPTED_INDEX_DATA_NON_JSON\n"
        with open(self.index_path, "w", encoding="utf-8") as f:
            f.write(corrupted_content)

        with self.assertRaises(ValueError):
            update_history_index("2026-09-15", index_path=self.index_path)

        # Verify corrupted file content remains unchanged
        with open(self.index_path, "r", encoding="utf-8") as f:
            content_after = f.read()

        self.assertEqual(content_after, corrupted_content)


if __name__ == "__main__":
    unittest.main()
