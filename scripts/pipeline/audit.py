"""Universe Audit builder for VN Invest pipeline orchestration."""

from typing import Any

from scripts.lib.monitoring import validate_performance_payload


def build_universe_audit(
    expected_symbols: set[str] | list[str],
    processed_symbols: set[str] | list[str],
    invalid_symbols: set[str] | list[str],
    insufficient_history_symbols: set[str] | list[str],
    failed_symbols: set[str] | list[str],
    missing_symbols: set[str] | list[str],
    exclusions_map: dict[str, dict[str, Any]],
    update_data: bool = False,
    performance_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build deterministic production universe_audit dictionary from pipeline sets and exclusions map."""
    s_expected = set(expected_symbols)
    s_processed = set(processed_symbols)
    s_invalid = set(invalid_symbols)
    s_insufficient = set(insufficient_history_symbols)
    s_failed = set(failed_symbols)
    s_missing = set(missing_symbols)

    failed_stage = None
    if "VNINDEX" in s_failed or "VN30" in s_failed:
        failed_stage = "BENCHMARK_FETCH"
    elif any(e.get("stage") == "TEMPORAL_VALIDATION" for e in exclusions_map.values()):
        failed_stage = "TEMPORAL_VALIDATION"
    elif any(e.get("stage") == "STOCK_FETCH" for e in exclusions_map.values()):
        failed_stage = "STOCK_FETCH"
    elif s_missing:
        failed_stage = "UNIVERSE_DISCOVERY"

    pipeline_status = "SUCCESS"
    if failed_stage is not None:
        pipeline_status = "FAILED" if update_data else "DEGRADED"

    diagnostics_list = [exclusions_map[s] for s in sorted(exclusions_map.keys())]

    universe_summary = {
        "status": pipeline_status,
        "failed_stage": failed_stage,
        "expected_count": len(s_expected),
        "processed_count": len(s_processed),
        "invalid_count": len(s_invalid),
        "insufficient_history_count": len(s_insufficient),
        "failed_count": len(s_failed),
        "missing_count": len(s_missing),
        "diagnostic_count": len(diagnostics_list),
    }

    audit = {
        "status": pipeline_status,
        "failed_stage": failed_stage,
        "expected_symbols": sorted(s_expected),
        "processed_symbols": sorted(s_processed),
        "invalid_symbols": sorted(s_invalid),
        "insufficient_history_symbols": sorted(s_insufficient),
        "failed_symbols": sorted(s_failed),
        "missing_symbols": sorted(s_missing),
        "counts": universe_summary,
        "summary": universe_summary,
        "exclusions": diagnostics_list,
        "diagnostics": diagnostics_list,
    }

    if performance_data is not None:
        validate_performance_payload(performance_data)
        audit["performance"] = performance_data

    return audit


__all__ = ["build_universe_audit"]
