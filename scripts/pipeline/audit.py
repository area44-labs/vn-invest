"""Universe Audit adapter for VN Invest pipeline orchestration."""

from typing import Any

from scripts.domain.universe import Universe, UniverseScanResult


def build_universe_audit(
    scan_result: UniverseScanResult | None = None,
    expected_symbols: set[str] | list[str] | tuple[str, ...] | None = None,
    processed_symbols: set[str] | list[str] | tuple[str, ...] | None = None,
    invalid_symbols: set[str] | list[str] | tuple[str, ...] | None = None,
    insufficient_history_symbols: set[str] | list[str] | tuple[str, ...] | None = None,
    failed_symbols: set[str] | list[str] | tuple[str, ...] | None = None,
    missing_symbols: set[str] | list[str] | tuple[str, ...] | None = None,
    exclusions_map: dict[str, dict[str, Any]] | None = None,
    update_data: bool = False,
    performance_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Adapter function delegating universe audit payload generation directly to UniverseScanResult."""
    if isinstance(scan_result, UniverseScanResult):
        return scan_result.to_audit_dict(update_data=update_data, performance_data=performance_data)

    s_expected = set(expected_symbols or ())
    s_processed = set(processed_symbols or ())
    s_invalid = set(invalid_symbols or ())
    s_insufficient = set(insufficient_history_symbols or ())
    s_failed = set(failed_symbols or ())
    s_missing = set(missing_symbols or ())
    ex_map = dict(exclusions_map or {})

    # Disambiguate benchmarks strictly from expected_symbols if present, without hardcoded assumptions
    # constructing a minimal candidates-only Universe for backward compatibility
    cands_only = s_expected - {"VNINDEX", "VN30"}
    benchmarks = tuple(s for s in ("VNINDEX", "VN30") if s in s_expected)

    u_temp = Universe.from_candidates(
        candidates=[
            {"symbol": sym, "companyName": sym, "sector": "UNKNOWN", "exchange": "HOSE"}
            for sym in sorted(cands_only)
        ],
        universe_type="AUDIT_ADAPTER",
        benchmarks=benchmarks,
    )

    scan_res = UniverseScanResult(
        universe=u_temp,
        processed_symbols=tuple(s_processed),
        invalid_symbols=tuple(s_invalid),
        insufficient_symbols=tuple(s_insufficient),
        failed_symbols=tuple(s_failed),
        missing_symbols=tuple(s_missing),
        exclusions_map=ex_map,
    )

    return scan_res.to_audit_dict(update_data=update_data, performance_data=performance_data)


__all__ = ["build_universe_audit"]
