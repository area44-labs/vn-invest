"""Unit tests for fail-closed history index persistence loader."""

import json
import os
import sys
import tempfile

import pytest

from scripts.generate_report import GENERATED_DIR, load_history_index, update_history_index

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


@pytest.mark.unit
class TestHistoryIndexLoader:
    """Test suite for history index loader and updater fail-closed semantics."""

    def setup_method(self):
        history_dir = os.path.join(GENERATED_DIR, "history")
        os.makedirs(history_dir, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=history_dir)
        self.index_path = os.path.join(self.temp_dir.name, "index.json")

    def teardown_method(self):
        self.temp_dir.cleanup()

    def test_missing_file_returns_initialized_empty_index(self):
        """Verifies that a non-existent history index file initializes a valid empty index contract."""
        assert not os.path.exists(self.index_path)
        data = load_history_index(self.index_path)
        assert data == {"dates": []}

    def test_valid_index_loads_successfully(self):
        """Verifies that a valid history index JSON file loads successfully and returns expected dates."""
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        valid_payload = {
            "last_updated": "2026-09-14T04:11:09.418616+00:00",
            "total_reports": 2,
            "dates": ["2026-09-14", "2026-09-13"],
        }
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(valid_payload, f)

        data = load_history_index(self.index_path)
        assert data["dates"] == ["2026-09-14", "2026-09-13"]
        assert data["total_reports"] == 2

    def test_malformed_json_raises(self):
        """Verifies that reading a history index file with invalid JSON raises ValueError with file path context."""
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        with open(self.index_path, "w", encoding="utf-8") as f:
            f.write("{ corrupted_json: true, ")

        with pytest.raises(ValueError) as ctx:
            load_history_index(self.index_path)

        assert "invalid JSON" in str(ctx.value)
        assert self.index_path in str(ctx.value)

    def test_invalid_root_type_raises(self):
        """Verifies that valid JSON with non-object root types raises TypeError or ValueError."""
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)

        for invalid_root in ['[ "2026-09-14" ]', "null", '"2026-09-14"', "123"]:
            with open(self.index_path, "w", encoding="utf-8") as f:
                f.write(invalid_root)

            with pytest.raises((ValueError, TypeError)) as ctx:
                load_history_index(self.index_path)

            assert "Invalid history index structure" in str(ctx.value)
            assert self.index_path in str(ctx.value)

    def test_invalid_structure_raises(self):
        """Verifies that a history index JSON object with missing or invalid 'dates' field raises TypeError or ValueError."""
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

            with pytest.raises((ValueError, TypeError)) as ctx:
                load_history_index(self.index_path)

            assert "Invalid history index structure" in str(ctx.value)
            assert self.index_path in str(ctx.value)

    def test_permission_read_failure_raises(self, mocker):
        """Verifies that permission errors reading the history index file raise OSError without swallowing into an empty index."""
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump({"dates": ["2026-09-14"]}, f)

        mocker.patch("builtins.open", side_effect=PermissionError("Permission denied"))
        with pytest.raises((PermissionError, OSError)) as ctx:
            load_history_index(self.index_path)

        assert "Permission denied" in str(ctx.value)

    def test_corrupted_file_is_not_overwritten(self):
        """Verifies that updating a history index when the file is corrupted raises ValueError and leaves the original file untouched."""
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        corrupted_content = "CORRUPTED_INDEX_DATA_NON_JSON\n"
        with open(self.index_path, "w", encoding="utf-8") as f:
            f.write(corrupted_content)

        with pytest.raises(ValueError):
            update_history_index("2026-09-15", index_path=self.index_path)

        # Verify corrupted file content remains unchanged
        with open(self.index_path, "r", encoding="utf-8") as f:
            content_after = f.read()

        assert content_after == corrupted_content
