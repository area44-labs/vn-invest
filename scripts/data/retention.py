"""Reusable Historical Market Data Retention and Pruning Utility.

Implements the project-wide market data retention policy:
- Cutoff date: 2026-10-01 (RETENTION_CUTOFF_DATE).
- Retains valid records on or after the cutoff date.
- Removes obsolete records dated before the cutoff date.
- Preserves the latest available daily record as the primary/current data point.
- Deduplicates and chronologically sorts retained records.
- Safely reports unparseable or malformed dates without crashing.
- Handles empty datasets and missing date columns safely.
- Performs atomic file writes to protect against corruption.
- Guarantees idempotent execution.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

RETENTION_CUTOFF_DATE: str = "2026-10-01"


class RetentionError(Exception):
    """Base error for data retention operations."""


class UnparseableDateError(RetentionError):
    """Raised when an unparseable or malformed date is encountered."""


@dataclass(frozen=True)
class PruningSummary:
    """Summary of records pruned and retained during a dataset retention operation."""

    dataset_name: str
    initial_count: int
    retained_count: int
    removed_count: int
    unparseable_count: int
    latest_record_date: str | None


def parse_canonical_date(date_str: Any) -> str:
    """Parse and validate a date string as canonical YYYY-MM-DD.

    Raises UnparseableDateError if the date is invalid, malformed, or missing.
    """
    if not isinstance(date_str, str) or not date_str.strip():
        raise UnparseableDateError(f"Missing or non-string date value: {date_str!r}")

    cleaned = date_str.strip()
    # Support ISO timestamps (e.g., 2026-10-16T15:18:31.502140+00:00 -> 2026-10-16)
    if "T" in cleaned:
        cleaned = cleaned.split("T")[0]
    elif " " in cleaned:
        cleaned = cleaned.split(" ")[0]

    try:
        dt = datetime.strptime(cleaned, "%Y-%m-%d").replace(tzinfo=UTC)
        return dt.strftime("%Y-%m-%d")
    except ValueError as err:
        raise UnparseableDateError(
            f"Date value '{date_str}' is not a valid YYYY-MM-DD calendar date"
        ) from err


def prune_date_list(
    dates: list[Any],
    cutoff_date: str = RETENTION_CUTOFF_DATE,
    date_order: str = "descending",
    allow_unparseable: bool = False,
) -> tuple[list[str], PruningSummary]:
    """Prune and deduplicate a list of date strings according to the retention policy.

    Parameters:
    - dates: list of date strings (e.g. from history/index.json).
    - cutoff_date: retention cutoff date in YYYY-MM-DD (default '2026-10-01').
    - date_order: 'descending' (newest first, standard for index.json) or 'ascending'.
    - allow_unparseable: if False, raises UnparseableDateError on bad date. If True, skips and counts.
    """
    parsed_cutoff = parse_canonical_date(cutoff_date)
    initial_count = len(dates)
    valid_dates: set[str] = set()
    unparseable_count = 0

    for item in dates:
        try:
            d_str = parse_canonical_date(item)
            if d_str >= parsed_cutoff:
                valid_dates.add(d_str)
        except UnparseableDateError as exc:
            if not allow_unparseable:
                raise
            unparseable_count += 1
            logger.warning("Skipping unparseable date entry in list: %s (%s)", item, exc)

    reverse_sort = date_order == "descending"
    sorted_dates = sorted(valid_dates, reverse=reverse_sort)
    retained_count = len(sorted_dates)
    removed_count = initial_count - retained_count - unparseable_count

    latest_date = None
    if valid_dates:
        latest_date = max(valid_dates)

    summary = PruningSummary(
        dataset_name="date_list",
        initial_count=initial_count,
        retained_count=retained_count,
        removed_count=removed_count,
        unparseable_count=unparseable_count,
        latest_record_date=latest_date,
    )
    return sorted_dates, summary


def prune_dataframe(
    df: pd.DataFrame,
    date_col: str = "time",
    cutoff_date: str = RETENTION_CUTOFF_DATE,
    preserve_latest: bool = True,
    allow_unparseable: bool = False,
) -> tuple[pd.DataFrame, PruningSummary]:
    """Prune an OHLCV or tabular DataFrame according to the retention policy.

    Ensures:
    - Records >= cutoff_date are retained.
    - Records < cutoff_date are removed.
    - If preserve_latest is True and no records meet the cutoff, the latest valid daily record is preserved.
    - Rows are sorted chronologically by date and deduplicated on date_col.
    """
    if df is None or df.empty:
        summary = PruningSummary(
            dataset_name="dataframe",
            initial_count=0,
            retained_count=0,
            removed_count=0,
            unparseable_count=0,
            latest_record_date=None,
        )
        return pd.DataFrame(columns=df.columns if df is not None else None), summary

    if date_col not in df.columns:
        raise RetentionError(f"DataFrame missing required date column '{date_col}'")

    parsed_cutoff = parse_canonical_date(cutoff_date)
    initial_count = len(df)

    # Normalize date values
    parsed_dates = []
    unparseable_indices = []
    for idx, raw_val in enumerate(df[date_col]):
        try:
            d_str = parse_canonical_date(str(raw_val))
            parsed_dates.append(d_str)
        except UnparseableDateError as exc:
            if not allow_unparseable:
                raise
            parsed_dates.append(None)
            unparseable_indices.append(idx)
            logger.warning("Unparseable date in DataFrame row %d: %s (%s)", idx, raw_val, exc)

    working_df = df.copy()
    working_df["_canonical_date"] = parsed_dates

    if unparseable_indices:
        working_df = working_df.dropna(subset=["_canonical_date"])

    # Deduplicate keeping last occurrence and sort chronologically
    working_df = working_df.sort_values(by="_canonical_date", ascending=True)
    working_df = working_df.drop_duplicates(subset=["_canonical_date"], keep="last")

    latest_date = working_df["_canonical_date"].iloc[-1] if not working_df.empty else None

    # Filter >= cutoff_date
    mask = working_df["_canonical_date"] >= parsed_cutoff
    pruned_df = working_df[mask].copy()

    # If cutoff removed all rows but preserve_latest is True and rows existed
    if pruned_df.empty and preserve_latest and not working_df.empty:
        pruned_df = working_df.iloc[[-1]].copy()
        logger.info(
            "Retention cutoff (%s) filtered all rows; preserved latest available daily record (%s)",
            cutoff_date,
            latest_date,
        )

    # Clean up auxiliary column and restore original date_col formatted as YYYY-MM-DD string
    pruned_df[date_col] = pruned_df["_canonical_date"]
    pruned_df = pruned_df.drop(columns=["_canonical_date"]).reset_index(drop=True)

    retained_count = len(pruned_df)
    unparseable_count = len(unparseable_indices)
    removed_count = initial_count - retained_count - unparseable_count

    summary = PruningSummary(
        dataset_name="dataframe",
        initial_count=initial_count,
        retained_count=retained_count,
        removed_count=removed_count,
        unparseable_count=unparseable_count,
        latest_record_date=latest_date,
    )
    return pruned_df, summary


def atomic_write_json(filepath: str, data: Any, indent: int = 2) -> None:
    """Atomically write JSON data to file to prevent corrupt or partial writes."""
    abs_path = os.path.abspath(filepath)
    parent_dir = os.path.dirname(abs_path)
    os.makedirs(parent_dir, exist_ok=True)

    temp_fd, temp_path = tempfile.mkstemp(dir=parent_dir, prefix=".tmp_retention_")
    try:
        with open(temp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
            f.write("\n")
        os.replace(temp_path, abs_path)
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        raise


def prune_history_index(
    index_file_path: str,
    cutoff_date: str = RETENTION_CUTOFF_DATE,
    dry_run: bool = False,
    allow_unparseable: bool = False,
) -> tuple[dict[str, Any], PruningSummary]:
    """Prune dates before cutoff_date in a history index JSON file.

    Maintains canonical schema:
    {
        "last_updated": ...,
        "total_reports": ...,
        "dates": [...]
    }
    """
    if not os.path.exists(index_file_path):
        raise FileNotFoundError(f"History index file not found: {index_file_path}")

    with open(index_file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict) or "dates" not in data:
        raise RetentionError(f"Invalid history index format in {index_file_path}")

    dates = data.get("dates", [])
    pruned_dates, summary = prune_date_list(
        dates,
        cutoff_date=cutoff_date,
        date_order="descending",
        allow_unparseable=allow_unparseable,
    )

    updated_data = dict(data)
    updated_data["dates"] = pruned_dates
    updated_data["total_reports"] = len(pruned_dates)

    if not dry_run:
        atomic_write_json(index_file_path, updated_data)
        logger.info(
            "Pruned history index '%s': initial=%d, retained=%d, removed=%d",
            index_file_path,
            summary.initial_count,
            summary.retained_count,
            summary.removed_count,
        )

    return updated_data, summary


def prune_generated_history_artifacts(
    history_dir: str,
    cutoff_date: str = RETENTION_CUTOFF_DATE,
    dry_run: bool = False,
    allow_unparseable: bool = False,
) -> dict[str, Any]:
    """Prune historical daily report JSON files from generated/history/ prior to cutoff_date.

    Also prunes and updates generated/history/index.json atomically.
    Preserves all records dated >= cutoff_date.
    """
    history_dir = os.path.abspath(history_dir)
    if not os.path.isdir(history_dir):
        raise FileNotFoundError(f"History directory not found: {history_dir}")

    parsed_cutoff = parse_canonical_date(cutoff_date)
    removed_files: list[str] = []
    retained_files: list[str] = []
    unparseable_files: list[str] = []

    for entry in os.listdir(history_dir):
        if not entry.endswith(".json") or entry == "index.json":
            continue

        date_part = entry[:-5]  # strip .json
        try:
            d_str = parse_canonical_date(date_part)
            fpath = os.path.join(history_dir, entry)
            if d_str < parsed_cutoff:
                removed_files.append(entry)
                if not dry_run:
                    os.unlink(fpath)
            else:
                retained_files.append(entry)
        except UnparseableDateError as exc:
            if not allow_unparseable:
                raise
            unparseable_files.append(entry)
            logger.warning("Unparseable history file name '%s': %s", entry, exc)

    index_path = os.path.join(history_dir, "index.json")
    index_summary = None
    if os.path.exists(index_path):
        _, index_summary = prune_history_index(
            index_path,
            cutoff_date=parsed_cutoff,
            dry_run=dry_run,
            allow_unparseable=allow_unparseable,
        )

    result = {
        "cutoff_date": parsed_cutoff,
        "removed_files_count": len(removed_files),
        "removed_files": sorted(removed_files),
        "retained_files_count": len(retained_files),
        "retained_files": sorted(retained_files),
        "unparseable_files_count": len(unparseable_files),
        "index_summary": index_summary.__dict__ if index_summary else None,
    }
    logger.info(
        "Pruned history artifacts in '%s': removed=%d, retained=%d (cutoff=%s)",
        history_dir,
        len(removed_files),
        len(retained_files),
        parsed_cutoff,
    )
    return result


def main() -> None:
    """CLI entry point for historical market data retention utility."""
    parser = argparse.ArgumentParser(
        description="Prune obsolete historical market data records before October 2026."
    )
    parser.add_argument(
        "--target-dir",
        default="generated",
        help="Path to generated artifacts directory (default: 'generated')",
    )
    parser.add_argument(
        "--cutoff-date",
        default=RETENTION_CUTOFF_DATE,
        help=f"Retention cutoff date in YYYY-MM-DD (default: '{RETENTION_CUTOFF_DATE}')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate pruning without deleting or modifying files",
    )
    parser.add_argument(
        "--allow-unparseable",
        action="store_true",
        help="Skip and report unparseable records instead of failing",
    )

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    gen_dir = os.path.abspath(args.target_dir)
    hist_dir = os.path.join(gen_dir, "history")

    if not os.path.isdir(hist_dir):
        logger.error("Target history directory does not exist: %s", hist_dir)
        raise SystemExit(1)

    try:
        res = prune_generated_history_artifacts(
            history_dir=hist_dir,
            cutoff_date=args.cutoff_date,
            dry_run=args.dry_run,
            allow_unparseable=args.allow_unparseable,
        )
        print(json.dumps(res, indent=2))
    except Exception as exc:
        logger.error("Data retention pruning failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
