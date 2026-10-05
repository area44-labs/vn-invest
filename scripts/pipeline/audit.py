"""Universe Audit adapter for VN Invest pipeline orchestration."""

from typing import Any

from scripts.domain.universe import Universe, UniverseScanResult


def build_universe_audit(
    expected_symbols: set[str] | list[str] | tuple[str, ...],
    processed_symbols: set[str] | list[str] | tuple[str, ...],
    invalid_symbols: set[str] | list[str] | tuple[str, ...],
    insufficient_history_symbols: set[str] | list[str] | tuple[str, ...],
    failed_symbols: set[str] | list[str] | tuple[str, ...],
    missing_symbols: set[str] | list[str] | tuple[str, ...],
    exclusions_map: dict[str, dict[str, Any]],
    update_data: bool = False,
    performance_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Adapter function constructing UniverseScanResult to delegate universe audit generation."""
    s_expected = set(expected_symbols)
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
        processed_symbols=tuple(processed_symbols),
        invalid_symbols=tuple(invalid_symbols),
        insufficient_symbols=tuple(insufficient_history_symbols),
        failed_symbols=tuple(failed_symbols),
        missing_symbols=tuple(missing_symbols),
        exclusions_map=exclusions_map,
    )

    return scan_res.to_audit_dict(update_data=update_data, performance_data=performance_data)


__all__ = ["build_universe_audit"]
