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
        "workload": {
            "benchmark_request_count": 0,
            "stock_request_count": 0,
            "total_request_count": 0,
            "requested_symbols": [],
        },
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

    def get_workload_metadata(self) -> dict[str, Any]:
        """Construct canonical workload metadata from logical pipeline requests."""
        benchmarks = {"VNINDEX", "VN30"}
        requested_symbols = sorted(self.symbol_requests.keys())

        n_benchmarks = sum(
            count for sym, count in self.symbol_requests.items() if sym in benchmarks
        )
        n_stocks = sum(
            count for sym, count in self.symbol_requests.items() if sym not in benchmarks
        )

        return {
            "benchmark_request_count": n_benchmarks,
            "stock_request_count": n_stocks,
            "total_request_count": n_benchmarks + n_stocks,
            "requested_symbols": requested_symbols,
        }

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

        Enforces stage-segregated exception handling: provider instrumentation failures use
        safe fallbacks, while canonical workload metadata errors and payload schema validation errors
        in update mode fail closed.
        """
        import jsonschema

        from scripts.performance.regression import WorkloadMetadataError
        from scripts.pipeline.validation import validate_performance_payload
        from scripts.schema import SchemaResolutionError

        # 1. Non-critical provider call history instrumentation
        try:
            provider_summary = aggregate_provider_performance(call_history)
            duplicates = detect_duplicate_operations(call_history, self.symbol_requests)
        except Exception as provider_exc:  # noqa: BLE001
            logger.warning("Provider call history instrumentation error: %s", provider_exc)
            provider_summary = {
                "total_calls": 0,
                "successful_calls": 0,
                "failed_calls": 0,
                "retry_count": 0,
                "total_elapsed_seconds": 0.0,
                "average_call_seconds": 0.0,
                "calls_by_source": {},
            }
            duplicates = []

        # 2. Stage metrics & Workload metadata assembly
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
        workload_meta = self.get_workload_metadata()

        payload: dict[str, Any] = {
            "schema_version": "2.0",
            "stages": stages_list,
            "provider": provider_summary,
            "duplicate_operations": duplicates,
            "workload": workload_meta,
        }

        # 3. Performance regression evaluation
        try:
            payload["regression"] = evaluate_performance_regression(
                payload, is_update_mode=update_data
            )
        except WorkloadMetadataError as workload_exc:
            if update_data:
                logger.error("Canonical workload metadata error in update mode: %s", workload_exc)
                raise
            logger.warning("Workload metadata error in non-update mode: %s", workload_exc)
            payload["regression"] = {
                "overall_status": "PASS",
                "stage_evaluations": [],
            }

        # 4. Budget evaluation
        try:
            payload["budget"] = evaluate_provider_budget(
                payload, enforce_ci_budget=self.enable_ci_budget
            )
        except Exception as budget_exc:
            if update_data:
                logger.error("Provider budget evaluation error in update mode: %s", budget_exc)
                raise
            logger.warning("Provider budget evaluation error in non-update mode: %s", budget_exc)
            payload["budget"] = {
                "overall_status": "DEGRADED",
                "total_calls": provider_summary.get("total_calls", 0),
                "max_calls_budget": 120,
                "duplicate_operations_count": len(duplicates),
                "max_duplicates_budget": 5,
                "total_elapsed_seconds": provider_summary.get("total_elapsed_seconds", 0.0),
                "max_elapsed_budget_seconds": 60.0,
                "violations": [f"Provider budget evaluation error: {budget_exc}"],
            }

        # 5. Authoritative schema validation
        try:
            validate_performance_payload(payload)
        except (
            jsonschema.ValidationError,
            SchemaResolutionError,
            TypeError,
            ValueError,
        ) as val_exc:
            if update_data:
                logger.error(
                    "Performance payload schema validation error in update mode: %s", val_exc
                )
                raise
            logger.warning(
                "Performance payload schema validation error in non-update mode: %s", val_exc
            )
            fallback = create_default_performance_payload()
            return fallback

        return payload


__all__ = ["PerformanceTracker", "create_default_performance_payload"]
