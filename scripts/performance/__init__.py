"""VN Invest Performance Tracking Subsystem.

Provides performance profiling, stage duration measurement, provider metrics aggregation,
duplicate operation detection, performance budget checking, and regression detection.
"""

from typing import Any

from scripts.performance.budget import evaluate_provider_budget
from scripts.performance.provider_metrics import (
    aggregate_provider_performance,
    detect_duplicate_operations,
)
from scripts.performance.regression import evaluate_performance_regression
from scripts.performance.stage_metrics import StageMetricsCollector
from scripts.performance.tracker import PerformanceTracker, create_default_performance_payload


def validate_performance_payload(performance_data: dict[str, Any]) -> None:
    """Validate canonical performance object structure and schema."""
    from scripts.pipeline.validation import validate_performance_payload as _validate

    _validate(performance_data)


__all__ = [
    "PerformanceTracker",
    "StageMetricsCollector",
    "aggregate_provider_performance",
    "create_default_performance_payload",
    "detect_duplicate_operations",
    "evaluate_performance_regression",
    "evaluate_provider_budget",
    "validate_performance_payload",
]
