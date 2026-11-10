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
    unverified_dates: tuple[str, ...] = ()

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
            "unverified_dates_count": len(self.unverified_dates),
            "expected_trading_dates": list(self.expected_trading_dates),
            "missing_report_dates": list(self.missing_report_dates),
            "backfill_candidates": list(self.backfill_candidates),
            "unverified_dates": list(self.unverified_dates),
        }


def reconcile_trading_history(
    generated_dir: str,
    start_date: str,
    end_date: str,
    known_trading_calendar_dates: Sequence[str] | None = None,
) -> ReconciliationReport:
    """Reconcile expected trading dates against indexed daily reports and run manifests.

    Rules & States:
    1. Calendar Certainty:
       - If `known_trading_calendar_dates` (e.g. from benchmark VNINDEX trading dates) is provided,
         dates are treated as confirmed trading dates.
       - If not provided, weekdays (Mon-Fri) are inspected. Any date without confirmed execution
         history is classified as `unverified` and NOT automatically scheduled for backfill,
         preventing market holidays from generating false backfills.
    2. Retention Awareness:
       - Daily report retention keeps the latest 14 reports in `history/index.json`.
       - A date that was successfully processed (RunManifest status == 'SUCCESS') is NEVER
         scheduled for backfill, even if its daily report has expired from `history/index.json`.
    3. Backfill Candidates:
       - Confirmed trading dates that failed execution (and have no subsequent successful run).
       - Confirmed trading dates that have never been processed (no run manifest entry).
       - Dates with deliberate 'SKIPPED' status or successful executions are excluded.
    """
    if not is_valid_date_string(start_date):
        raise ValueError(f"Invalid start_date: {start_date!r}")
    if not is_valid_date_string(end_date):
        raise ValueError(f"Invalid end_date: {end_date!r}")
    if start_date > end_date:
        raise ValueError(f"start_date '{start_date}' cannot be after end_date '{end_date}'")

    has_known_calendar = known_trading_calendar_dates is not None

    if has_known_calendar:
        expected_dates = sorted(
            {
                d
                for d in (known_trading_calendar_dates or [])
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
    all_dates_with_history = set()

    for d in expected_dates:
        entries = manifest_tracker.load_partition(d)
        if entries:
            all_dates_with_history.add(d)
            # Latest run entry determines state for that date
            # But if ANY run succeeded for that date, consider successful
            has_success = any(e.status == "SUCCESS" for e in entries)
            has_skipped = any(e.status == "SKIPPED" for e in entries)
            has_failed = any(e.status == "FAILED" for e in entries)

            if has_success:
                successful_runs.add(d)
            elif has_skipped:
                skipped_runs.add(d)
            elif has_failed:
                failed_runs.add(d)

    missing_report_dates = sorted(set(expected_dates) - set(available_dates))

    unverified_dates: list[str] = []
    backfill_candidates: list[str] = []

    for d in expected_dates:
        # If date had a successful run (even if report expired by retention), no backfill needed
        if d in successful_runs or d in available_dates:
            continue
        # If date was skipped, respect the skip
        if d in skipped_runs:
            continue

        if has_known_calendar:
            # Confirmed trading date that either failed or was never processed
            backfill_candidates.append(d)
        else:
            # Fallback calendar: check if date has verified failed history
            if d in failed_runs:
                # Confirmed run occurred and failed -> backfill candidate
                backfill_candidates.append(d)
            elif d not in all_dates_with_history:
                # Date has no history and calendar is unverified -> do not automatically backfill
                unverified_dates.append(d)

    return ReconciliationReport(
        start_date=start_date,
        end_date=end_date,
        expected_trading_dates=tuple(expected_dates),
        available_report_dates=tuple(available_dates),
        missing_report_dates=tuple(missing_report_dates),
        successful_run_dates=tuple(sorted(successful_runs)),
        failed_run_dates=tuple(sorted(failed_runs)),
        skipped_run_dates=tuple(sorted(skipped_runs)),
        backfill_candidates=tuple(sorted(backfill_candidates)),
        unverified_dates=tuple(sorted(unverified_dates)),
    )


__all__ = [
    "ReconciliationReport",
    "reconcile_trading_history",
]
