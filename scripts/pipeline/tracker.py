"""Structured Performance Tracker for VN Invest pipeline orchestration."""

import time
from contextlib import contextmanager
from typing import Any

from scripts.data_provider import (
    VnstockDataProvider,
    aggregate_provider_performance,
    detect_duplicate_operations,
)
from scripts.lib.monitoring import (
    evaluate_performance_regression,
    evaluate_provider_budget,
    validate_performance_payload,
)


def _perf_counter() -> float:
    """Get perf_counter, respecting mocks on scripts.generate_report.time.perf_counter if active."""
    import sys

    mod = sys.modules.get("scripts.generate_report")
    if mod and hasattr(mod, "time") and hasattr(mod.time, "perf_counter"):
        return mod.time.perf_counter()
    return time.perf_counter()


class PerformanceTracker:
    """Deterministic structured performance timer and diagnostics collector."""

    def __init__(self):
        self.t_pipeline_start = _perf_counter()
        self.stages: list[dict[str, Any]] = []
        self.symbol_requests: dict[str, int] = {}

    def record_request(self, symbol: str) -> None:
        if symbol:
            sym_u = str(symbol).strip().upper()
            self.symbol_requests[sym_u] = self.symbol_requests.get(sym_u, 0) + 1

    def record_stage(
        self, stage: str, elapsed_seconds: float, status: str = "SUCCESS"
    ) -> dict[str, Any]:
        record = {
            "stage": stage,
            "elapsed_seconds": round(max(0.0, elapsed_seconds), 4),
            "status": status,
        }
        self.stages.append(record)
        return record

    @contextmanager
    def measure_stage(self, stage: str):
        t0 = _perf_counter()
        status = "SUCCESS"
        try:
            yield
        except Exception:
            status = "FAILED"
            raise
        finally:
            elapsed = _perf_counter() - t0
            self.record_stage(stage, elapsed, status)

    def get_performance_payload(
        self,
        pipeline_elapsed: float | None = None,
        pipeline_status: str = "SUCCESS",
        call_history: list[dict] | None = None,
    ) -> dict[str, Any]:
        if call_history is None:
            call_history = VnstockDataProvider.get_global_call_history()

        provider_summary = aggregate_provider_performance(call_history)
        duplicates = detect_duplicate_operations(call_history, self.symbol_requests)

        stages_list = []
        if pipeline_elapsed is not None:
            stages_list.append(
                {
                    "stage": "pipeline",
                    "elapsed_seconds": round(max(0.0, pipeline_elapsed), 4),
                    "status": pipeline_status,
                }
            )

        stages_list.extend(self.stages)

        payload = {
            "stages": stages_list,
            "provider": provider_summary,
            "duplicate_operations": duplicates,
        }

        payload["regression"] = evaluate_performance_regression(payload)
        payload["budget"] = evaluate_provider_budget(payload)

        validate_performance_payload(payload)
        return payload


__all__ = ["PerformanceTracker"]
