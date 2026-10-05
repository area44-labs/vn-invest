"""Universe Audit adapter for VN Invest pipeline orchestration."""

from typing import Any

from scripts.domain.universe import UniverseScanResult


def build_universe_audit(
    scan_result: UniverseScanResult | None = None,
    update_data: bool = False,
    performance_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Adapter function delegating universe audit payload generation directly to UniverseScanResult."""
    if isinstance(scan_result, UniverseScanResult):
        return scan_result.to_audit_dict(update_data=update_data, performance_data=performance_data)

    raise TypeError("build_universe_audit requires a UniverseScanResult instance")


__all__ = ["build_universe_audit"]
