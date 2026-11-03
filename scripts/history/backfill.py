"""Historical backfill execution engine."""

import logging
from typing import Any

from scripts.artifacts.transaction import GENERATED_DIR
from scripts.history.models import is_valid_date_string
from scripts.pipeline.runner import generate_historical_report

logger = logging.getLogger(__name__)


def backfill_historical_date(
    trading_date: str,
    universe_stock_map: dict[str, Any],
    df_vnindex: Any,
    df_vn30: Any | None = None,
    candidate_metadata: list[dict[str, Any]] | None = None,
    generated_dir: str | None = None,
    publish_artifacts: bool = True,
) -> Any:
    """Execute safe and idempotent historical backfill for a single trading date.

    Guarantees:
    - Backfills recommendation ledger partition independent of report retention.
    - Creates run manifest with run_type = 'BACKFILL' and status = 'SUCCESS'.
    - Updates history/index.json retaining newest 14 reports without corrupting newer reports.
    """
    if not is_valid_date_string(trading_date):
        raise ValueError(f"Invalid trading_date for backfill: {trading_date!r}")

    gen_dir = generated_dir or GENERATED_DIR

    logger.info("Starting historical backfill for trading date %s...", trading_date)

    res = generate_historical_report(
        data_as_of=trading_date,
        universe_stock_map=universe_stock_map,
        df_vnindex=df_vnindex,
        df_vn30=df_vn30,
        candidate_metadata=candidate_metadata,
        data_source="backfill_historical_input",
        generated_dir=gen_dir,
        publish_artifacts=publish_artifacts,
    )

    logger.info("Completed historical backfill for trading date %s.", trading_date)
    return res


__all__ = [
    "backfill_historical_date",
]
