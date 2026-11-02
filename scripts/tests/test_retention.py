"""Deterministic offline tests for historical market data retention and pruning.

Verifies:
- Records before October 2026 are safely pruned.
- Records from October 1, 2026 onward are preserved.
- Latest daily record is preserved even if all records precede cutoff.
- Duplicate dates are deduplicated chronologically.
- Unparseable dates are reported safely or rejected per configuration.
- Empty datasets and missing date columns handle safely without crashes.
- Repeated executions are strictly idempotent.
- Atomic file writes preserve original files if write operations fail.
- Compatibility with canonical pipeline acquisition, temporal validation, and monitoring.
"""

import json
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from scripts.data.models import CanonicalMarketData, OHLCVData
from scripts.data.retention import (
    RETENTION_CUTOFF_DATE,
    RetentionError,
    UnparseableDateError,
    atomic_write_json,
    parse_canonical_date,
    prune_dataframe,
    prune_date_list,
    prune_generated_history_artifacts,
)
from scripts.data.validation import validate_canonical_market_data, validate_temporal_integrity
from scripts.monitoring import evaluate_production_monitoring


class TestDataRetentionUnit:
    """Unit test suite for retention utility parsing, dataframe pruning, and date list pruning."""

    def test_parse_canonical_date_valid(self):
        """Valid calendar date strings and ISO timestamps are parsed to YYYY-MM-DD."""
        assert parse_canonical_date("2026-10-01") == "2026-10-01"
        assert parse_canonical_date("2026-10-16T15:18:31.502140+00:00") == "2026-10-16"
        assert parse_canonical_date("2026-10-16 09:30:00") == "2026-10-16"

    def test_parse_canonical_date_invalid_raises_error(self):
        """Invalid, empty, or non-string dates raise UnparseableDateError."""
        with pytest.raises(UnparseableDateError):
            parse_canonical_date("")
        with pytest.raises(UnparseableDateError):
            parse_canonical_date(None)
        with pytest.raises(UnparseableDateError):
            parse_canonical_date("invalid-date")
        with pytest.raises(UnparseableDateError):
            parse_canonical_date("2026-13-45")

    def test_prune_date_list_basic_retention(self):
        """Records before October 1, 2026 are removed while records from cutoff onward are retained."""
        dates = [
            "2026-09-28",
            "2026-09-30",
            "2026-10-01",
            "2026-10-05",
            "2026-10-16",
        ]
        pruned, summary = prune_date_list(dates, cutoff_date=RETENTION_CUTOFF_DATE)
        assert pruned == ["2026-10-16", "2026-10-05", "2026-10-01"]
        assert summary.initial_count == 5
        assert summary.retained_count == 3
        assert summary.removed_count == 2
        assert summary.latest_record_date == "2026-10-16"

    def test_prune_date_list_deduplication(self):
        """Duplicate dates are deduplicated and sorted in descending order."""
        dates = ["2026-10-05", "2026-10-01", "2026-10-05", "2026-10-01"]
        pruned, summary = prune_date_list(dates)
        assert pruned == ["2026-10-05", "2026-10-01"]
        assert summary.retained_count == 2

    def test_prune_date_list_unparseable_handling(self):
        """Unparseable dates raise UnparseableDateError unless allow_unparseable is True."""
        dates = ["2026-10-01", "bad-date", "2026-10-05"]
        with pytest.raises(UnparseableDateError):
            prune_date_list(dates, allow_unparseable=False)

        pruned, summary = prune_date_list(dates, allow_unparseable=True)
        assert pruned == ["2026-10-05", "2026-10-01"]
        assert summary.unparseable_count == 1

    def test_prune_dataframe_retention_and_sorting(self):
        """DataFrame rows before October 2026 are pruned, and retained rows are sorted chronologically."""
        df = pd.DataFrame(
            {
                "time": ["2026-09-25", "2026-10-02", "2026-09-29", "2026-10-01", "2026-10-16"],
                "close": [10.0, 11.0, 10.5, 11.2, 12.0],
                "volume": [100, 200, 150, 250, 300],
            }
        )
        pruned_df, summary = prune_dataframe(df, date_col="time")
        assert list(pruned_df["time"]) == ["2026-10-01", "2026-10-02", "2026-10-16"]
        assert summary.retained_count == 3
        assert summary.removed_count == 2
        assert summary.latest_record_date == "2026-10-16"

    def test_prune_dataframe_preserves_latest_record_when_all_prior(self):
        """Preserve latest daily record when all historical records precede the cutoff date."""
        df = pd.DataFrame(
            {
                "time": ["2026-08-01", "2026-08-15", "2026-09-20"],
                "close": [100.0, 105.0, 110.0],
            }
        )
        pruned_df, summary = prune_dataframe(df, date_col="time", preserve_latest=True)
        assert len(pruned_df) == 1
        assert pruned_df["time"].iloc[0] == "2026-09-20"
        assert summary.latest_record_date == "2026-09-20"

    def test_prune_dataframe_empty_and_missing_column(self):
        """Empty DataFrame returns empty safely; missing date column raises RetentionError."""
        empty_df = pd.DataFrame()
        pruned_empty, summary = prune_dataframe(empty_df)
        assert pruned_empty.empty
        assert summary.initial_count == 0

        df_no_date = pd.DataFrame({"close": [10.0]})
        with pytest.raises(RetentionError):
            prune_dataframe(df_no_date, date_col="time")

    def test_prune_dataframe_deduplication(self):
        """Duplicate dates in DataFrame keep the latest occurrence."""
        df = pd.DataFrame(
            {
                "time": ["2026-10-01", "2026-10-01"],
                "close": [10.0, 15.0],
            }
        )
        pruned_df, summary = prune_dataframe(df)
        assert len(pruned_df) == 1
        assert pruned_df["close"].iloc[0] == 15.0
        assert summary.retained_count == 1


class TestDataRetentionArtifacts:
    """Integration test suite for pruning generated history artifacts and history index."""

    def test_prune_history_artifacts_removes_old_files(self):
        """Artifacts dated before October 2026 are removed from directory and index updated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = Path(tmpdir) / "history"
            hist_dir.mkdir(parents=True)

            # Create synthetic old and new history files
            (hist_dir / "2026-09-15.json").write_text(
                '{"data_as_of": "2026-09-15"}', encoding="utf-8"
            )
            (hist_dir / "2026-09-30.json").write_text(
                '{"data_as_of": "2026-09-30"}', encoding="utf-8"
            )
            (hist_dir / "2026-10-01.json").write_text(
                '{"data_as_of": "2026-10-01"}', encoding="utf-8"
            )
            (hist_dir / "2026-10-16.json").write_text(
                '{"data_as_of": "2026-10-16"}', encoding="utf-8"
            )

            index_content = {
                "last_updated": "2026-10-16T00:00:00Z",
                "total_reports": 4,
                "dates": ["2026-10-16", "2026-10-01", "2026-09-30", "2026-09-15"],
            }
            (hist_dir / "index.json").write_text(json.dumps(index_content), encoding="utf-8")

            res = prune_generated_history_artifacts(str(hist_dir))

            assert res["removed_files_count"] == 2
            assert res["retained_files_count"] == 2
            assert not (hist_dir / "2026-09-15.json").exists()
            assert not (hist_dir / "2026-09-30.json").exists()
            assert (hist_dir / "2026-10-01.json").exists()
            assert (hist_dir / "2026-10-16.json").exists()

            updated_index = json.loads((hist_dir / "index.json").read_text(encoding="utf-8"))
            assert updated_index["dates"] == ["2026-10-16", "2026-10-01"]
            assert updated_index["total_reports"] == 2

    def test_idempotent_execution(self):
        """Repeated pruning executions produce identical outputs without errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_dir = Path(tmpdir) / "history"
            hist_dir.mkdir(parents=True)

            (hist_dir / "2026-09-20.json").write_text(
                '{"data_as_of": "2026-09-20"}', encoding="utf-8"
            )
            (hist_dir / "2026-10-08.json").write_text(
                '{"data_as_of": "2026-10-08"}', encoding="utf-8"
            )
            index_content = {
                "last_updated": "2026-10-08T00:00:00Z",
                "total_reports": 2,
                "dates": ["2026-10-08", "2026-09-20"],
            }
            (hist_dir / "index.json").write_text(json.dumps(index_content), encoding="utf-8")

            res1 = prune_generated_history_artifacts(str(hist_dir))
            index_after_first = (hist_dir / "index.json").read_text(encoding="utf-8")

            res2 = prune_generated_history_artifacts(str(hist_dir))
            index_after_second = (hist_dir / "index.json").read_text(encoding="utf-8")

            assert res1["removed_files_count"] == 1
            assert res2["removed_files_count"] == 0
            assert index_after_first == index_after_second

    def test_atomic_write_preserves_original_on_failure(self):
        """Atomic write leaves existing destination file untouched if write fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target_file = Path(tmpdir) / "test_artifact.json"
            target_file.write_text('{"status": "original"}', encoding="utf-8")

            class UnserializableObject:
                pass

            bad_data = {"key": UnserializableObject()}
            with pytest.raises(TypeError):
                atomic_write_json(str(target_file), bad_data)

            # Original file remains untouched
            assert target_file.read_text(encoding="utf-8") == '{"status": "original"}'


class TestDataRetentionPipelineCompatibility:
    """Verifies pipeline components (canonical market data, temporal validation, monitoring) work with retained range."""

    def test_canonical_market_data_with_retained_records(self):
        """CanonicalMarketData validates and produces clean DataFrames for retained date range."""
        dates = pd.bdate_range("2026-10-01", periods=10).strftime("%Y-%m-%d")
        records = [
            OHLCVData(
                date=d,
                open=1000.0,
                high=1010.0,
                low=990.0,
                close=1005.0,
                volume=500000.0,
            )
            for d in dates
        ]
        cmd = CanonicalMarketData(
            symbol="VNINDEX",
            records=tuple(records),
            data_as_of=dates[-1],
        )
        val = validate_canonical_market_data(cmd)
        assert val.symbol == "VNINDEX"
        assert val.to_df().shape[0] == 10

    def test_temporal_validation_with_retained_records(self):
        """validate_temporal_integrity verifies benchmark data ending on reference date."""
        dates = pd.bdate_range("2026-10-01", periods=10).strftime("%Y-%m-%d")
        data_as_of = dates[-1]
        stock_dates = {"FPT": dates[-1]}
        res = validate_temporal_integrity(data_as_of, stock_dates, reference_date=dates[-1])
        assert res["is_valid"]
        assert res["issues"] == []
        assert res["future_symbols"] == set()
        assert res["stale_symbols"] == set()

    def test_monitoring_generation_with_project_retained_history(self):
        """evaluate_production_monitoring generates valid monitoring with project retained history."""
        with open("generated/recommendations.json", "r", encoding="utf-8") as f:
            recs = json.load(f)
        with open("generated/market.json", "r", encoding="utf-8") as f:
            mkt = json.load(f)

        mon_res = evaluate_production_monitoring(
            generated_dir="generated",
            recommendations_payload=recs,
            market_payload=mkt,
            reference_date=recs["data_as_of"],
        )
        mon_dict = mon_res.to_dict()
        assert mon_dict["data_as_of"] == "2026-10-16"
        chk_names = {c["check_name"]: c["status"] for c in mon_dict["checks"]}
        assert chk_names.get("history_index_status") == "PASS"
        assert chk_names.get("data_freshness") == "PASS"
        assert chk_names.get("schema_validation") == "PASS"
