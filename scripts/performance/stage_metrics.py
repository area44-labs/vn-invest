"""Pipeline Stage Metrics Collector and timing instrumentation.

Provides deterministic stage-level timing measurement, exception recording,
and performance diagnostic aggregation for pipeline execution.
"""

import logging
import time
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)


class StageMetricsCollector:
    """Collector for pipeline stage timing metrics and execution status."""

    def __init__(self):
        self._stages: list[dict[str, Any]] = []

    def record_stage(
        self,
        stage: str,
        elapsed_seconds: float,
        status: str = "SUCCESS",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record timing and status for a completed or failed stage."""
        stage_name = str(stage).strip()
        elapsed = round(max(0.0, float(elapsed_seconds)), 4)
        exec_status = str(status).strip().upper() if status else "SUCCESS"

        record: dict[str, Any] = {
            "stage": stage_name,
            "elapsed_seconds": elapsed,
            "status": exec_status,
        }
        if metadata:
            record["metadata"] = dict(metadata)

        self._stages.append(record)
        return record

    @contextmanager
    def measure_stage(self, stage: str, metadata: dict[str, Any] | None = None):
        """Context manager to measure the execution time of a stage and handle exceptions.

        If an unhandled exception occurs inside the context, the stage status is recorded
        as 'FAILED' before re-raising the exception.
        """
        t0 = time.perf_counter()
        status = "SUCCESS"
        try:
            yield
        except Exception:
            status = "FAILED"
            raise
        finally:
            elapsed = time.perf_counter() - t0
            self.record_stage(stage, elapsed, status, metadata=metadata)

    def get_stages(self) -> list[dict[str, Any]]:
        """Return a detached copy of all recorded stage timing records."""
        return [dict(s) for s in self._stages]

    def get_slow_stages(self, threshold_seconds: float = 1.0) -> list[dict[str, Any]]:
        """Return recorded stages exceeding the given elapsed time threshold."""
        return [s for s in self.get_stages() if s.get("elapsed_seconds", 0.0) >= threshold_seconds]

    def reset(self) -> None:
        """Reset recorded stage metrics."""
        self._stages = []


__all__ = ["StageMetricsCollector"]
