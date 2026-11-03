"""Unit tests for Run Manifest subsystem and error metadata sanitization."""

import tempfile

import pytest

from scripts.history.manifest import (
    RunManifestTracker,
    sanitize_error_metadata,
)
from scripts.history.models import RunManifestEntry


@pytest.mark.unit
class TestRunManifestSuite:
    """Tests for run manifest tracking, status codes, run types, and credential redaction."""

    def test_run_manifest_entry_validations(self):
        """Run manifest constructor enforces valid statuses, run_types, and dates."""
        valid_entry = RunManifestEntry(
            run_id="run_1",
            trading_date="2026-10-01",
            generated_at="2026-10-01T12:00:00Z",
            status="SUCCESS",
            run_type="SCHEDULED",
        )
        assert valid_entry.status == "SUCCESS"
        assert valid_entry.run_type == "SCHEDULED"

        with pytest.raises(ValueError):
            RunManifestEntry(
                run_id="run_bad",
                trading_date="2026-10-01",
                generated_at="2026-10-01T12:00:00Z",
                status="UNKNOWN_STATUS",
            )

        with pytest.raises(ValueError):
            RunManifestEntry(
                run_id="run_bad",
                trading_date="2026-10-01",
                generated_at="2026-10-01T12:00:00Z",
                status="SUCCESS",
                run_type="UNKNOWN_RUN_TYPE",
            )

    def test_error_metadata_sanitization(self):
        """Sensitive tokens, passwords, and API keys are redacted from error metadata."""
        raw_error = {
            "api_key": "secret_abc123",
            "Authorization": "Bearer token_xyz",
            "password": "my_password",
            "stage": "data_acquisition",
            "nested": {
                "user_token": "token_123",
                "detail": "Connection timed out",
            },
        }
        sanitized = sanitize_error_metadata(raw_error)
        assert sanitized["api_key"] == "[REDACTED]"
        assert sanitized["Authorization"] == "[REDACTED]"
        assert sanitized["password"] == "[REDACTED]"
        assert sanitized["nested"]["user_token"] == "[REDACTED]"
        assert sanitized["nested"]["detail"] == "Connection timed out"
        assert sanitized["stage"] == "data_acquisition"

    def test_run_manifest_persistence_and_partitioning(self):
        """Run manifest entries are safely appended into partition files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = RunManifestTracker(tmpdir)
            entry1 = RunManifestEntry(
                run_id="run_1",
                trading_date="2026-10-01",
                generated_at="2026-10-01T08:00:00Z",
                status="FAILED",
                run_type="SCHEDULED",
                error_metadata={"reason": "Rate limited"},
            )
            tracker.stage_run_entry(tmpdir, entry1)

            entry2 = RunManifestEntry(
                run_id="run_2",
                trading_date="2026-10-01",
                generated_at="2026-10-01T09:00:00Z",
                status="SUCCESS",
                run_type="MANUAL",
            )
            tracker.stage_run_entry(tmpdir, entry2)

            entries = tracker.load_partition("2026-10-01")
            assert len(entries) == 2
            assert entries[0].run_id == "run_1"
            assert entries[0].status == "FAILED"
            assert entries[1].run_id == "run_2"
            assert entries[1].status == "SUCCESS"
