"""Unit and integration tests for History 14-report retention policy and atomic staging cleanup."""

import json
import os
import tempfile

import pytest

from scripts.artifacts import ArtifactPublisher
from scripts.history.retention import apply_history_retention, prune_staged_history_reports


@pytest.mark.unit
class TestHistoryRetentionPolicy:
    """Tests for 14-report retention calculation and safe pruning."""

    def test_apply_retention_single_report(self):
        """Publishing the first report retains exactly that 1 report."""
        retained, expired = apply_history_retention(["2026-10-01"])
        assert retained == ["2026-10-01"]
        assert expired == []

    def test_apply_retention_fourteen_reports(self):
        """Publishing 14 reports retains all 14."""
        dates = [f"2026-10-{i:02d}" for i in range(1, 15)]
        retained, expired = apply_history_retention(dates, max_reports=14)
        assert len(retained) == 14
        assert expired == []
        assert retained[0] == "2026-10-14"
        assert retained[-1] == "2026-10-01"

    def test_apply_retention_fifteen_reports_removes_oldest(self):
        """Publishing the 15th report removes the oldest report."""
        dates = [f"2026-10-{i:02d}" for i in range(1, 16)]
        retained, expired = apply_history_retention(dates, max_reports=14)
        assert len(retained) == 14
        assert len(expired) == 1
        assert "2026-10-01" in expired
        assert "2026-10-15" in retained

    def test_apply_retention_twenty_reports_retains_latest_fourteen(self):
        """Publishing 20 reports retains the latest 14 successful reports."""
        dates = [f"2026-10-{i:02d}" for i in range(1, 21)]
        retained, expired = apply_history_retention(dates, max_reports=14)
        assert len(retained) == 14
        assert len(expired) == 6
        assert retained == [f"2026-10-{i:02d}" for i in range(20, 6, -1)]
        assert expired == [f"2026-10-{i:02d}" for i in range(6, 0, -1)]

    def test_apply_retention_deduplicates_same_trading_date(self):
        """Reprocessing an existing trading date does not create duplicates."""
        dates = ["2026-10-01", "2026-10-02", "2026-10-02", "2026-10-03"]
        retained, expired = apply_history_retention(dates, max_reports=14)
        assert retained == ["2026-10-03", "2026-10-02", "2026-10-01"]
        assert expired == []

    def test_backfill_old_date_does_not_evict_newer_reports_incorrectly(self):
        """Backfilling an older date retains newest 14 reports and evicts oldest from reports window."""
        latest_dates = [f"2026-10-{i:02d}" for i in range(10, 24)]  # 14 dates (10 to 23)
        old_backfill_date = "2026-09-01"
        candidate_dates = latest_dates + [old_backfill_date]

        retained, expired = apply_history_retention(candidate_dates, max_reports=14)
        assert len(retained) == 14
        assert old_backfill_date in expired
        assert "2026-10-23" in retained
        assert "2026-10-10" in retained

    def test_prune_staged_history_reports_deletes_only_unretained_reports(self):
        """Prune helper strictly deletes expired YYYY-MM-DD.json files in staging, preserving index.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = os.path.join(tmpdir, "history")
            os.makedirs(hist_dir, exist_ok=True)

            # Create sample files
            retained = ["2026-10-02", "2026-10-03"]
            with open(os.path.join(hist_dir, "index.json"), "w") as f:
                f.write("{}")
            with open(os.path.join(hist_dir, "2026-10-01.json"), "w") as f:
                f.write("{}")
            with open(os.path.join(hist_dir, "2026-10-02.json"), "w") as f:
                f.write("{}")
            with open(os.path.join(hist_dir, "2026-10-03.json"), "w") as f:
                f.write("{}")

            removed = prune_staged_history_reports(tmpdir, retained_dates=retained)
            assert removed == ["history/2026-10-01.json"]
            assert not os.path.exists(os.path.join(hist_dir, "2026-10-01.json"))
            assert os.path.exists(os.path.join(hist_dir, "2026-10-02.json"))
            assert os.path.exists(os.path.join(hist_dir, "2026-10-03.json"))
            assert os.path.exists(os.path.join(hist_dir, "index.json"))


@pytest.mark.integration
class TestHistoryRetentionAtomicPublishing:
    """Integration test verifying retention enforcement during atomic transactions."""

    def test_publishing_fifteenth_report_evicts_oldest_from_disk(self):
        """Publishing 15 reports one by one leaves exactly 14 report files and matching index."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = os.path.join(tmpdir, "generated")
            publisher = ArtifactPublisher(target_dir=target_dir, strict_provenance=False)

            def make_payload(d):
                return {
                    "schema_version": "2.0",
                    "signal_model_version": "2.0",
                    "generated_at": f"{d}T00:00:00Z",
                    "data_as_of": d,
                    "source_date": d,
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

            # Publish 15 successive days
            for i in range(1, 16):
                d = f"2026-10-{i:02d}"
                batch = {
                    "recommendations.json": make_payload(d),
                    "market.json": {"data_as_of": d, "market": {"regime": "BULL"}},
                    f"history/{d}.json": make_payload(d),
                }
                # Load current index to update
                from scripts.artifacts.manifest import load_history_index
                from scripts.history.retention import apply_history_retention

                idx_path = os.path.join(target_dir, "history", "index.json")
                curr_dates = load_history_index(idx_path).get("dates", [])
                retained_dates, _ = apply_history_retention(curr_dates + [d])
                batch["history/index.json"] = {
                    "last_updated": f"{d}T00:00:00Z",
                    "total_reports": len(retained_dates),
                    "dates": retained_dates,
                }
                publisher.publish(batch, canonical_data_as_of=d)

            # Check that 2026-10-01.json was physically deleted
            hist_dir = os.path.join(target_dir, "history")
            assert not os.path.exists(os.path.join(hist_dir, "2026-10-01.json"))
            assert os.path.exists(os.path.join(hist_dir, "2026-10-15.json"))

            # Check index has exactly 14 dates
            with open(os.path.join(hist_dir, "index.json"), "r") as f:
                idx = json.load(f)
            assert idx["total_reports"] == 14
            assert len(idx["dates"]) == 14
            assert idx["dates"][0] == "2026-10-15"
            assert idx["dates"][-1] == "2026-10-02"
