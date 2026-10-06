"""Market Data Provider Performance Metrics and Duplicate Operation Detection.

Extracts provider timing records, retries, call counts, and duplicate operations
without modifying provider business logic or quantitative calculations.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def aggregate_provider_performance(
    call_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregate provider call timing history into structured performance statistics.

    If call_history is None, delegates to VnstockDataProvider.get_global_call_history().
    """
    if call_history is None:
        try:
            from scripts.data_provider import VnstockDataProvider

            call_history = VnstockDataProvider.get_global_call_history()
        except ImportError:
            call_history = []

    total_calls = len(call_history)
    successful_calls = sum(1 for c in call_history if c.get("success"))
    failed_calls = sum(1 for c in call_history if not c.get("success"))
    retry_count = sum(c.get("retry_count", 0) for c in call_history)
    total_elapsed_seconds = round(
        sum(float(c.get("elapsed_seconds", 0.0)) for c in call_history), 4
    )
    average_call_seconds = round(total_elapsed_seconds / total_calls, 4) if total_calls > 0 else 0.0

    calls_by_source: dict[str, int] = {}
    for c in call_history:
        src = str(c.get("source") or "unknown")
        calls_by_source[src] = calls_by_source.get(src, 0) + 1

    return {
        "total_calls": total_calls,
        "successful_calls": successful_calls,
        "failed_calls": failed_calls,
        "retry_count": retry_count,
        "total_elapsed_seconds": total_elapsed_seconds,
        "average_call_seconds": average_call_seconds,
        "calls_by_source": calls_by_source,
    }


def detect_duplicate_operations(
    call_history: list[dict[str, Any]] | None = None,
    symbol_requests: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Detect repeated or duplicate provider operations per symbol across calls and requests."""
    if call_history is None:
        try:
            from scripts.data_provider import VnstockDataProvider

            call_history = VnstockDataProvider.get_global_call_history()
        except ImportError:
            call_history = []

    symbol_provider_calls: dict[str, list[dict[str, Any]]] = {}
    for c in call_history:
        sym = c.get("symbol")
        if sym:
            symbol_provider_calls.setdefault(str(sym).strip().upper(), []).append(c)

    all_symbols = set(symbol_provider_calls.keys())
    if symbol_requests:
        all_symbols.update(str(s).strip().upper() for s in symbol_requests.keys())

    duplicates = []
    for sym in sorted(all_symbols):
        calls = symbol_provider_calls.get(sym, [])
        p_count = len(calls)
        req_count = symbol_requests.get(sym, 0) if symbol_requests else 0

        if p_count > 1 or req_count > 1:
            succ = sum(1 for c in calls if c.get("success"))
            failed = sum(1 for c in calls if not c.get("success"))
            retries = sum(c.get("retry_count", 0) for c in calls)
            duplicates.append(
                {
                    "symbol": sym,
                    "provider_call_count": p_count,
                    "request_count": max(req_count, p_count),
                    "successful_calls": succ,
                    "failed_calls": failed,
                    "retry_count": retries,
                }
            )

    return duplicates


__all__ = [
    "aggregate_provider_performance",
    "detect_duplicate_operations",
]
