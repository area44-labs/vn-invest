"""Structured Performance Tracker for VN Invest pipeline orchestration.

Orchestrates stage timing metrics, provider performance aggregation, duplicate operation detection,
budget enforcement, and performance regression evaluation into a unified performance payload.
"""

import logging
import time
from contextlib import contextmanager
from typing import Any

from scripts.performance.budget import evaluate_provider_budget
from scripts.performance.provider_metrics import (
    aggregate_provider_performance,
    detect_duplicate_operations,
)
from scripts.performance.regression import evaluate_performance_regression
from scripts.performance.stage_metrics import StageMetricsCollector

logger = logging.getLogger(__name__)


def create_default_performance_payload() -> dict[str, Any]:
    """Construct a minimal valid performance payload for test harness or fallback contexts."""
    payload: dict[str, Any] = {
        "schema_version": "2.0",
        "stages": [
            {"stage": "pipeline", "elapsed_seconds": 0.0, "status": "SUCCESS"},
        ],
        "provider": {
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
            "retry_count": 0,
            "total_elapsed_seconds": 0.0,
            "average_call_seconds": 0.0,
            "calls_by_source": {},
        },
        "duplicate_operations": [],
    }
    payload["regression"] = evaluate_performance_regression(payload)
    payload["budget"] = evaluate_provider_budget(payload)
    return payload


class PerformanceTracker:
    """Deterministic structured performance timer and diagnostics collector."""

    def __init__(self, enable_ci_budget: bool | None = None):
        self.t_pipeline_start = time.perf_counter()
        self.stage_collector = StageMetricsCollector()
        self.symbol_requests: dict[str, int] = {}
        self.enable_ci_budget = enable_ci_budget

    @property
    def stages(self) -> list[dict[str, Any]]:
        """Return stage records list for backward compatibility."""
        return self.stage_collector.get_stages()

    def record_request(self, symbol: str) -> None:
        """Record symbol request count for duplicate operation detection."""
        if symbol:
            sym_u = str(symbol).strip().upper()
            self.symbol_requests[sym_u] = self.symbol_requests.get(sym_u, 0) + 1

    def record_stage(
        self, stage: str, elapsed_seconds: float, status: str = "SUCCESS"
    ) -> dict[str, Any]:
        """Record stage execution time and status."""
        return self.stage_collector.record_stage(stage, elapsed_seconds, status)

    @contextmanager
    def measure_stage(self, stage: str):
        """Context manager to time a pipeline stage."""
        with self.stage_collector.measure_stage(stage):
            yield

    def get_performance_payload(
        self,
        pipeline_elapsed: float | None = None,
        pipeline_status: str = "SUCCESS",
        call_history: list[dict[str, Any]] | None = None,
        update_data: bool = False,
    ) -> dict[str, Any]:
        """Construct unified canonical performance payload.

        Enforces fail-safe isolation: if any metric extraction, budget, or validation error occurs,
        logs a warning and returns a valid fallback payload without interrupting business or quantitative pipeline processing.
        """
        from scripts.pipeline.validation import validate_performance_payload

        try:
            provider_summary = aggregate_provider_performance(call_history)
            duplicates = detect_duplicate_operations(call_history, self.symbol_requests)

            stages_list: list[dict[str, Any]] = []
            if pipeline_elapsed is not None:
                stages_list.append(
                    {
                        "stage": "pipeline",
                        "elapsed_seconds": round(max(0.0, float(pipeline_elapsed)), 4),
                        "status": str(pipeline_status),
                    }
                )

            stages_list.extend(self.stage_collector.get_stages())

            payload: dict[str, Any] = {
                "schema_version": "2.0",
                "stages": stages_list,
                "provider": provider_summary,
                "duplicate_operations": duplicates,
            }

            payload["regression"] = evaluate_performance_regression(
                payload, is_update_mode=update_data
            )
            payload["budget"] = evaluate_provider_budget(
                payload, enforce_ci_budget=self.enable_ci_budget
            )

            validate_performance_payload(payload)
            return payload
        except Exception as exc:  # noqa: BLE001
            logger.warning("Instrumentation error during get_performance_payload: %s", exc)
            fallback = create_default_performance_payload()
            try:
                validate_performance_payload(fallback)
            except Exception as fallback_exc:  # noqa: BLE001
                logger.error("Fallback performance payload validation error: %s", fallback_exc)
            return fallback


__all__ = ["PerformanceTracker", "create_default_performance_payload"]
