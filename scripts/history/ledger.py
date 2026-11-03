"""Recommendation Ledger subsystem: partitioned append-oriented storage and deterministic deduplication."""

import json
import logging
import os
from collections.abc import Sequence
from typing import Any

from scripts.history.models import (
    HistoryDirectoryConventions,
    RecommendationLedgerEntry,
    generate_recommendation_id,
    is_valid_date_string,
)

logger = logging.getLogger(__name__)


def extract_ledger_entries_from_recommendations(
    recommendations: Sequence[Any],
    trading_date: str,
    model_version: str | None = None,
    config_hash: str | None = None,
) -> list[RecommendationLedgerEntry]:
    """Extract RecommendationLedgerEntry records from Recommendation domain instances or dictionaries."""
    if not is_valid_date_string(trading_date):
        raise ValueError(f"Invalid trading_date: {trading_date!r}")

    entries: list[RecommendationLedgerEntry] = []
    for rec in recommendations:
        if hasattr(rec, "to_dict"):
            r_dict = rec.to_dict()
        elif isinstance(rec, dict):
            r_dict = rec
        else:
            raise TypeError(f"Unsupported recommendation object type: {type(rec).__name__}")

        sym = str(r_dict.get("symbol", "")).strip().upper()
        act = str(r_dict.get("action", "")).strip().upper()
        if not sym or not act:
            continue

        mv = r_dict.get("model_version") or model_version or "2.0"
        ch = r_dict.get("config_hash") or config_hash or ""

        rec_id = generate_recommendation_id(
            trading_date=trading_date,
            symbol=sym,
            action=act,
            model_version=mv,
            config_hash=ch,
        )

        tp = r_dict.get("trade_plan") or {}
        ref_price = (
            tp.get("current_price") if isinstance(tp, dict) else getattr(tp, "current_price", None)
        )
        target_price = tp.get("tp1") if isinstance(tp, dict) else getattr(tp, "tp1", None)

        reasons = tuple(r_dict.get("reasons") or ())

        entry = RecommendationLedgerEntry(
            recommendation_id=rec_id,
            symbol=sym,
            trading_date=trading_date,
            action=act,
            reference_price=float(ref_price) if ref_price is not None else None,
            target_price=float(target_price) if target_price is not None else None,
            confidence=r_dict.get("confidence"),
            signal_score=r_dict.get("signal_score"),
            risk_adjusted_score=r_dict.get("risk_adjusted_score"),
            risk_level=r_dict.get("risk_level"),
            strategy_version=r_dict.get("quant_version"),
            model_version=mv,
            config_hash=ch,
            reasons=reasons,
            schema_version=1,
        )
        entries.append(entry)

    return entries


class RecommendationLedger:
    """Manages immutable append-oriented partitioned storage of recommendations."""

    def __init__(self, base_generated_dir: str):
        self.conventions = HistoryDirectoryConventions(base_generated_dir)

    def load_partition(self, trading_date: str) -> list[RecommendationLedgerEntry]:
        """Load all recommendation ledger entries for a given trading date."""
        filepath = self.conventions.get_ledger_partition_path(trading_date)
        if not os.path.exists(filepath):
            return []

        entries: list[RecommendationLedgerEntry] = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                clean_line = line.strip()
                if not clean_line:
                    continue
                try:
                    data = json.loads(clean_line)
                    entries.append(RecommendationLedgerEntry.from_dict(data))
                except (json.JSONDecodeError, ValueError, TypeError) as err:
                    logger.warning(
                        "Malformed recommendation ledger line %d in '%s': %s",
                        line_no,
                        filepath,
                        err,
                    )
        return entries

    def stage_partition_entries(
        self,
        staging_dir: str,
        trading_date: str,
        new_entries: Sequence[RecommendationLedgerEntry],
    ) -> str:
        """Merge new entries into staging partition idempotently, preserving older entries."""
        if not is_valid_date_string(trading_date):
            raise ValueError(f"Invalid trading_date: {trading_date!r}")

        staged_conventions = HistoryDirectoryConventions(staging_dir)
        target_path = staged_conventions.get_ledger_partition_path(trading_date)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)

        # First load existing from current live ledger if exists
        existing_entries = self.load_partition(trading_date)
        entries_by_id: dict[str, RecommendationLedgerEntry] = {
            e.recommendation_id: e for e in existing_entries
        }

        # Also load from staging partition if it was already written in this transaction
        if os.path.exists(target_path):
            with open(target_path, "r", encoding="utf-8") as f:
                for line in f:
                    clean = line.strip()
                    if clean:
                        try:
                            item = RecommendationLedgerEntry.from_dict(json.loads(clean))
                            entries_by_id[item.recommendation_id] = item
                        except (json.JSONDecodeError, ValueError, TypeError) as err:
                            logger.debug("Skipping unparseable staged ledger line: %s", err)

        for entry in new_entries:
            if entry.trading_date != trading_date:
                raise ValueError(
                    f"Entry trading_date '{entry.trading_date}' does not match partition date '{trading_date}'"
                )
            entries_by_id[entry.recommendation_id] = entry

        sorted_entries = sorted(entries_by_id.values(), key=lambda e: (e.symbol, e.action))

        with open(target_path, "w", encoding="utf-8") as f:
            for entry in sorted_entries:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

        return target_path


__all__ = [
    "RecommendationLedger",
    "extract_ledger_entries_from_recommendations",
]
