"""Trading history reconciliation engine."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd

from scripts.artifacts.manifest import load_history_index
from scripts.history.manifest import RunManifestTracker
from scripts.history.models import HistoryDirectoryConventions, is_valid_date_string

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReconciliationReport:
    """Report detailing reconciliation status between trading calendar and available historical artifacts."""

    start_date: str
    end_date: str
    expected_trading_dates: tuple[str, ...]
    available_report_dates: tuple[str, ...]
    missing_report_dates: tuple[str, ...]
    successful_run_dates: tuple[str, ...]
    failed_run_dates: tuple[str, ...]
    skipped_run_dates: tuple[str, ...]
    backfill_candidates: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "expected_trading_days_count": len(self.expected_trading_dates),
            "available_reports_count": len(self.available_report_dates),
            "missing_reports_count": len(self.missing_report_dates),
            "successful_runs_count": len(self.successful_run_dates),
            "failed_runs_count": len(self.failed_run_dates),
            "skipped_runs_count": len(self.skipped_run_dates),
            "backfill_candidates_count": len(self.backfill_candidates),
            "expected_trading_dates": list(self.expected_trading_dates),
            "missing_report_dates": list(self.missing_report_dates),
            "backfill_candidates": list(self.backfill_candidates),
        }


def reconcile_trading_history(
    generated_dir: str,
    start_date: str,
    end_date: str,
    known_trading_calendar_dates: Sequence[str] | None = None,
) -> ReconciliationReport:
    """Reconcile expected trading dates against indexed daily reports and run manifests.

    Rules:
    - If known_trading_calendar_dates (e.g. from benchmark VNINDEX trading dates) is provided,
      expected dates are strictly filtered to those dates.
    - Otherwise, standard weekdays (Mon-Fri) in [start_date, end_date] are used as initial candidates,
      distinguishing weekends automatically.
    - Compares against history/index.json dates and run-manifest partitions.
    - Backfill candidates are expected dates that have neither an available report nor a deliberately SKIPPED run.
    """
    if not is_valid_date_string(start_date):
        raise ValueError(f"Invalid start_date: {start_date!r}")
    if not is_valid_date_string(end_date):
        raise ValueError(f"Invalid end_date: {end_date!r}")
    if start_date > end_date:
        raise ValueError(f"start_date '{start_date}' cannot be after end_date '{end_date}'")

    if known_trading_calendar_dates is not None:
        expected_dates = sorted(
            {
                d
                for d in known_trading_calendar_dates
                if is_valid_date_string(d) and start_date <= d <= end_date
            }
        )
    else:
        # Generate Mon-Fri business days
        b_days = pd.date_range(start=start_date, end=end_date, freq="B").strftime("%Y-%m-%d")
        expected_dates = sorted(b_days)

    conventions = HistoryDirectoryConventions(generated_dir)
    index_path = conventions.history_index_path
    index_data = load_history_index(index_path)
    available_dates = sorted(
        {d for d in index_data.get("dates", []) if start_date <= d <= end_date}
    )

    manifest_tracker = RunManifestTracker(generated_dir)
    successful_runs = set()
    failed_runs = set()
    skipped_runs = set()

    for d in expected_dates:
        entries = manifest_tracker.load_partition(d)
        for e in entries:
            if e.status == "SUCCESS":
                successful_runs.add(d)
            elif e.status == "FAILED":
                failed_runs.add(d)
            elif e.status == "SKIPPED":
                skipped_runs.add(d)

    missing_dates = sorted(set(expected_dates) - set(available_dates))
    backfill_candidates = sorted(set(missing_dates) - skipped_runs)

    return ReconciliationReport(
        start_date=start_date,
        end_date=end_date,
        expected_trading_dates=tuple(expected_dates),
        available_report_dates=tuple(available_dates),
        missing_report_dates=tuple(missing_dates),
        successful_run_dates=tuple(sorted(successful_runs)),
        failed_run_dates=tuple(sorted(failed_runs)),
        skipped_run_dates=tuple(sorted(skipped_runs)),
        backfill_candidates=tuple(backfill_candidates),
    )


__all__ = [
    "ReconciliationReport",
    "reconcile_trading_history",
]
