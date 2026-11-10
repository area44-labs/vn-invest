"""Unit tests for History Reconciliation and Backfill."""

import json
import os
import tempfile

import pytest

from scripts.history.manifest import RunManifestTracker
from scripts.history.models import RunManifestEntry
from scripts.history.reconciliation import reconcile_trading_history


@pytest.mark.unit
class TestReconciliationSuite:
    """Tests for reconciliation between trading calendar, available reports, and run manifests."""

    def test_reconciliation_identifies_missing_dates(self):
        """Reconciliation identifies missing trading days correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = os.path.join(tmpdir, "history")
            os.makedirs(hist_dir, exist_ok=True)

            # Available dates: Monday 2026-10-05 and Wednesday 2026-10-07
            idx_payload = {
                "last_updated": "2026-10-07T12:00:00Z",
                "total_reports": 2,
                "dates": ["2026-10-07", "2026-10-05"],
            }
            with open(os.path.join(hist_dir, "index.json"), "w") as f:
                json.dump(idx_payload, f)

            # Known calendar: Mon 2026-10-05, Tue 2026-10-06, Wed 2026-10-07
            known_calendar = ["2026-10-05", "2026-10-06", "2026-10-07"]

            rep = reconcile_trading_history(
                generated_dir=tmpdir,
                start_date="2026-10-05",
                end_date="2026-10-07",
                known_trading_calendar_dates=known_calendar,
            )

            assert rep.expected_trading_dates == ("2026-10-05", "2026-10-06", "2026-10-07")
            assert rep.available_report_dates == ("2026-10-05", "2026-10-07")
            assert rep.missing_report_dates == ("2026-10-06",)
            assert rep.backfill_candidates == ("2026-10-06",)

    def test_reconciliation_excludes_skipped_runs_from_backfill_candidates(self):
        """Dates with a deliberately SKIPPED run manifest are not flagged as backfill candidates."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = os.path.join(tmpdir, "history")
            os.makedirs(hist_dir, exist_ok=True)
            with open(os.path.join(hist_dir, "index.json"), "w") as f:
                json.dump({"dates": []}, f)

            # Mark 2026-10-06 as SKIPPED in manifest
            tracker = RunManifestTracker(tmpdir)
            entry = RunManifestEntry(
                run_id="run_skip",
                trading_date="2026-10-06",
                generated_at="2026-10-06T08:00:00Z",
                status="SKIPPED",
                run_type="SCHEDULED",
            )
            tracker.stage_run_entry(tmpdir, entry)

            known_calendar = ["2026-10-06"]
            rep = reconcile_trading_history(
                generated_dir=tmpdir,
                start_date="2026-10-06",
                end_date="2026-10-06",
                known_trading_calendar_dates=known_calendar,
            )

            assert rep.missing_report_dates == ("2026-10-06",)
            assert rep.skipped_run_dates == ("2026-10-06",)
            assert rep.backfill_candidates == ()

    def test_reconciliation_excludes_successful_expired_dates_from_backfill(self):
        """A date with a SUCCESS run manifest older than the 14-report retention window is NOT backfilled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = os.path.join(tmpdir, "history")
            os.makedirs(hist_dir, exist_ok=True)

            # Daily report index has only recent dates, date 2026-08-01 was evicted
            with open(os.path.join(hist_dir, "index.json"), "w") as f:
                json.dump({"dates": ["2026-10-15"]}, f)

            # But RunManifest for 2026-08-01 shows SUCCESS
            tracker = RunManifestTracker(tmpdir)
            entry = RunManifestEntry(
                run_id="run_old_success",
                trading_date="2026-08-01",
                generated_at="2026-08-01T15:00:00Z",
                status="SUCCESS",
                run_type="SCHEDULED",
            )
            tracker.stage_run_entry(tmpdir, entry)

            rep = reconcile_trading_history(
                generated_dir=tmpdir,
                start_date="2026-08-01",
                end_date="2026-08-01",
                known_trading_calendar_dates=["2026-08-01"],
            )

            assert rep.successful_run_dates == ("2026-08-01",)
            assert rep.missing_report_dates == ("2026-08-01",)
            assert rep.backfill_candidates == ()

    def test_reconciliation_unverified_dates_without_calendar(self):
        """Without known calendar, dates without execution history are marked unverified, not backfilled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = os.path.join(tmpdir, "history")
            os.makedirs(hist_dir, exist_ok=True)
            with open(os.path.join(hist_dir, "index.json"), "w") as f:
                json.dump({"dates": []}, f)

            # 2026-10-05 is a Monday
            rep = reconcile_trading_history(
                generated_dir=tmpdir,
                start_date="2026-10-05",
                end_date="2026-10-05",
                known_trading_calendar_dates=None,  # Fallback business days
            )

            assert "2026-10-05" in rep.expected_trading_dates
            assert rep.backfill_candidates == ()
            assert rep.unverified_dates == ("2026-10-05",)
