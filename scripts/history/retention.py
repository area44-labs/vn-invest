"""Centralized Daily Report retention policy and staging cleanup engine."""

import logging
import os
import re
from collections.abc import Sequence

from scripts.history.models import MAX_RETAINED_REPORTS, is_valid_date_string

logger = logging.getLogger(__name__)

REPORT_FILE_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")


def apply_history_retention(
    dates: Sequence[str],
    max_reports: int = MAX_RETAINED_REPORTS,
) -> tuple[list[str], list[str]]:
    """Determine retained and expired dates based on trading_date descending order.

    Rules:
    - Retain newest max_reports (default 14) valid trading dates.
    - Dates are strictly deduplicated and sorted descending.
    - Returns (retained_dates, expired_dates).
    """
    if max_reports <= 0:
        raise ValueError(f"max_reports must be positive integer, got {max_reports}")

    valid_dates = sorted(
        {d.strip() for d in dates if is_valid_date_string(d.strip())},
        reverse=True,
    )

    retained = valid_dates[:max_reports]
    expired = valid_dates[max_reports:]
    return retained, expired


def prune_staged_history_reports(
    staging_dir: str,
    retained_dates: Sequence[str],
) -> list[str]:
    """Physically remove un-retained historical daily report files within staging directory.

    Safety constraints:
    - Only operates inside `staging_dir/history`.
    - Only deletes files matching `YYYY-MM-DD.json`.
    - Never deletes `index.json` or files outside `staging_dir/history`.
    - Returns list of removed relative file paths.
    """
    hist_dir = os.path.join(staging_dir, "history")
    if not os.path.exists(hist_dir):
        return []

    retained_set = set(retained_dates)
    removed_paths: list[str] = []

    for fname in os.listdir(hist_dir):
        m = REPORT_FILE_PATTERN.match(fname)
        if not m:
            continue
        date_str = m.group(1)
        if date_str not in retained_set:
            file_to_remove = os.path.join(hist_dir, fname)
            try:
                os.remove(file_to_remove)
                rel_path = os.path.join("history", fname)
                removed_paths.append(rel_path)
                logger.info("Pruned expired history report in staging: %s", rel_path)
            except OSError as err:
                logger.error(
                    "Failed pruning expired report file '%s' in staging: %s",
                    file_to_remove,
                    err,
                )
                raise RuntimeError(
                    f"Retention invariant violation: Failed to prune expired report file '{file_to_remove}' in staging: {err}"
                ) from err

    # Verify retention invariant in staging: no un-retained reports exist
    remaining = [
        m.group(1)
        for f in os.listdir(hist_dir)
        if (m := REPORT_FILE_PATTERN.match(f)) and m.group(1) not in retained_set
    ]
    if remaining:
        raise RuntimeError(
            f"Retention invariant violation: Staged history contains un-retained reports: {remaining}"
        )

    return sorted(removed_paths)


__all__ = [
    "apply_history_retention",
    "prune_staged_history_reports",
]
