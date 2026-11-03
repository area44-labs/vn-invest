"""One-off safe migration to seed recommendation ledger and run manifest from existing history reports."""

import json
import logging
import os
import re
from typing import Any

from scripts.artifacts.transaction import GENERATED_DIR
from scripts.history.ledger import RecommendationLedger, extract_ledger_entries_from_recommendations
from scripts.history.manifest import RunManifestTracker
from scripts.history.models import HistoryDirectoryConventions, RunManifestEntry

logger = logging.getLogger(__name__)

REPORT_DATE_REGEX = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")


def migrate_existing_history(generated_dir: str | None = None) -> dict[str, Any]:
    """Inspect all existing daily reports in history/, extract recommendations to recommendation-ledger/,
    and record baseline run-manifest entries while preserving all existing daily reports and history index.
    """
    g_dir = os.path.abspath(generated_dir or GENERATED_DIR)
    conventions = HistoryDirectoryConventions(g_dir)
    hist_dir = conventions.history_reports_dir

    if not os.path.exists(hist_dir):
        logger.info("No history directory found at %s. Nothing to migrate.", hist_dir)
        return {"migrated_dates": 0, "migrated_recommendations": 0}

    ledger = RecommendationLedger(g_dir)
    manifest_tracker = RunManifestTracker(g_dir)

    migrated_dates = 0
    migrated_recs_count = 0

    report_files = sorted([f for f in os.listdir(hist_dir) if REPORT_DATE_REGEX.match(f)])

    for fname in report_files:
        trading_date = REPORT_DATE_REGEX.match(fname).group(1)
        fpath = os.path.join(hist_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, ValueError, TypeError) as err:
            logger.error("Failed to read report %s: %s", fpath, err)
            continue

        recs = data.get("recommendations", [])
        if not recs:
            continue

        model_version = data.get("signal_model_version") or "2.0"
        config_hash = data.get("config_hash") or ""
        generated_at = data.get("generated_at") or f"{trading_date}T00:00:00Z"

        entries = extract_ledger_entries_from_recommendations(
            recommendations=recs,
            trading_date=trading_date,
            model_version=model_version,
            config_hash=config_hash,
        )

        ledger.stage_partition_entries(g_dir, trading_date, entries)

        run_entry = RunManifestEntry(
            run_id=f"run_{trading_date}_migrated",
            trading_date=trading_date,
            generated_at=generated_at,
            status="SUCCESS",
            run_type="MANUAL",
            error_metadata=None,
            commit_sha=None,
            schema_version=1,
        )
        manifest_tracker.stage_run_entry(g_dir, run_entry)

        migrated_dates += 1
        migrated_recs_count += len(entries)
        logger.info(
            "Migrated %s: %d recommendations into ledger and run manifest.",
            trading_date,
            len(entries),
        )

    return {
        "migrated_dates": migrated_dates,
        "migrated_recommendations": migrated_recs_count,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    res = migrate_existing_history()
    print("Migration result:", res)
