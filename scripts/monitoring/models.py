"""Data models and constants for the VN Invest v2 Monitoring Subsystem."""

import math
import os
from dataclasses import dataclass
from typing import Any

PIPELINE_STAGES = (
    "UNIVERSE_DISCOVERY",
    "BENCHMARK_FETCH",
    "STOCK_FETCH",
    "DATA_VALIDATION",
    "TEMPORAL_VALIDATION",
    "CALCULATION",
    "MONITORING",
    "OUTPUT_VALIDATION",
    "ARTIFACT_WRITE",
)

FAILURE_CATEGORIES = (
    "PROVIDER_FAILURE",
    "RATE_LIMIT",
    "INVALID_SYMBOL",
    "EXPLICITLY_INVALID",
    "INSUFFICIENT_HISTORICAL_DATA",
    "TEMPORAL_INVALID",
    "OUTPUT_VALIDATION_FAILURE",
    "MONITORING_FAILURE",
    "UNIVERSE_INCOMPLETE",
    "OTHER_VALIDATION_FAILURE",
    "MISSING_SYMBOL",
    "UNKNOWN",
)

RECOVERABLE_FAILURE_CATEGORIES = {
    "PROVIDER_FAILURE",
    "RATE_LIMIT",
}


def is_recoverable_category(category: str) -> bool:
    """Return True if failure category is considered transient/recoverable, False otherwise."""
    return category in RECOVERABLE_FAILURE_CATEGORIES


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_GENERATED_DIR = os.path.join(ROOT_DIR, "generated")
DEFAULT_SCHEMA_PATH = os.path.join(ROOT_DIR, "schemas", "v2", "recommendations.schema.json")
DEFAULT_PERFORMANCE_SCHEMA_PATH = os.path.join(ROOT_DIR, "schemas", "v2", "performance.schema.json")

VALID_CHECK_STATUSES = {"PASS", "WARNING", "FAIL"}

VALID_EXCLUSION_CATEGORIES = set(FAILURE_CATEGORIES)
VALID_PIPELINE_STAGES = set(PIPELINE_STAGES)

CANONICAL_CONFIDENCE_BUCKETS = [
    "0.0-0.1",
    "0.1-0.2",
    "0.2-0.3",
    "0.3-0.4",
    "0.4-0.5",
    "0.5-0.6",
    "0.6-0.7",
    "0.7-0.8",
    "0.8-0.9",
    "0.9-1.0",
]


def _sanitize_value_for_json(value: Any) -> Any:
    """Recursively sanitize Python objects for deterministic JSON serialization.

    Replaces float('nan') and float('inf') with string representations 'NaN' / 'Inf'
    so serialization does not break or produce invalid JSON.
    """
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Inf" if value > 0 else "-Inf"
        return value
    if isinstance(value, dict):
        return {k: _sanitize_value_for_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_value_for_json(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_value_for_json(item) for item in value]
    return value


def find_nan_or_inf(payload: Any, path: str = "") -> list[str]:
    """Recursively locate any NaN or Inf floating point values in nested data."""
    issues = []
    if isinstance(payload, float):
        if math.isnan(payload):
            issues.append(f"NaN at {path or 'root'}")
        elif math.isinf(payload):
            issues.append(f"Inf at {path or 'root'}")
    elif isinstance(payload, dict):
        for k, v in payload.items():
            issues.extend(find_nan_or_inf(v, f"{path}.{k}" if path else str(k)))
    elif isinstance(payload, list):
        for idx, item in enumerate(payload):
            issues.extend(find_nan_or_inf(item, f"{path}[{idx}]"))
    return issues


@dataclass(frozen=True)
class DriftObservation:
    """Individual data or model-output drift observation metric."""

    check_name: str
    baseline_period: dict[str, Any]
    current_period: str
    baseline_value: Any
    current_value: Any
    absolute_difference: Any
    threshold: Any
    status: str  # "PASS", "WARNING", "FAIL"
    message: str

    def __post_init__(self):
        if self.status not in VALID_CHECK_STATUSES:
            raise ValueError(
                f"Invalid check status '{self.status}'. Must be one of {sorted(VALID_CHECK_STATUSES)}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Return deterministic JSON-serializable dictionary representation."""
        return {
            "check_name": self.check_name,
            "baseline_period": _sanitize_value_for_json(self.baseline_period),
            "current_period": self.current_period,
            "baseline_value": _sanitize_value_for_json(self.baseline_value),
            "current_value": _sanitize_value_for_json(self.current_value),
            "absolute_difference": _sanitize_value_for_json(self.absolute_difference),
            "threshold": _sanitize_value_for_json(self.threshold),
            "status": self.status,
            "message": self.message,
        }


@dataclass(frozen=True)
class DriftCheckResult:
    """Drift check result holding observation detail and status."""

    check_name: str
    status: str  # "PASS", "WARNING", "FAIL"
    observation: DriftObservation

    def __post_init__(self):
        if self.status not in VALID_CHECK_STATUSES:
            raise ValueError(
                f"Invalid check status '{self.status}'. Must be one of {sorted(VALID_CHECK_STATUSES)}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Return deterministic JSON-serializable dictionary representation."""
        return {
            "check_name": self.check_name,
            "status": self.status,
            "observation": self.observation.to_dict(),
        }


@dataclass(frozen=True)
class DriftMonitoringResult:
    """Aggregated result of data and model-output drift monitoring."""

    overall_status: str  # "PASS", "WARNING", "FAIL"
    data_as_of: str | None
    baseline_summary: dict[str, Any]
    drift_checks: list[DriftCheckResult]

    def __post_init__(self):
        if self.overall_status not in VALID_CHECK_STATUSES:
            raise ValueError(
                f"Invalid overall_status '{self.overall_status}'. Must be one of {sorted(VALID_CHECK_STATUSES)}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Return deterministic JSON-serializable dictionary representation."""
        return {
            "overall_status": self.overall_status,
            "data_as_of": self.data_as_of,
            "baseline_summary": _sanitize_value_for_json(self.baseline_summary),
            "drift_checks": [check.to_dict() for check in self.drift_checks],
        }


@dataclass(frozen=True)
class CheckResult:
    """Individual production monitoring check result."""

    check_name: str
    status: str  # "PASS", "WARNING", "FAIL"
    measured_value: Any
    expected_condition: str
    message: str

    def __post_init__(self):
        if self.status not in VALID_CHECK_STATUSES:
            raise ValueError(
                f"Invalid check status '{self.status}'. Must be one of {sorted(VALID_CHECK_STATUSES)}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Return deterministic JSON-serializable dictionary representation."""
        return {
            "check_name": self.check_name,
            "status": self.status,
            "measured_value": _sanitize_value_for_json(self.measured_value),
            "expected_condition": self.expected_condition,
            "message": self.message,
        }


@dataclass(frozen=True)
class PipelineMonitoringResult:
    """Aggregated production pipeline monitoring result."""

    overall_status: str  # "PASS", "WARNING", "FAIL"
    generated_at: str
    data_as_of: str | None
    checks: list[CheckResult]
    metrics: dict[str, Any]

    def __post_init__(self):
        if self.overall_status not in VALID_CHECK_STATUSES:
            raise ValueError(
                f"Invalid overall_status '{self.overall_status}'. Must be one of {sorted(VALID_CHECK_STATUSES)}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Return deterministic JSON-serializable dictionary representation."""
        return {
            "overall_status": self.overall_status,
            "generated_at": self.generated_at,
            "data_as_of": self.data_as_of,
            "checks": [check.to_dict() for check in self.checks],
            "metrics": _sanitize_value_for_json(self.metrics),
        }


__all__ = [
    "CANONICAL_CONFIDENCE_BUCKETS",
    "DEFAULT_GENERATED_DIR",
    "DEFAULT_PERFORMANCE_SCHEMA_PATH",
    "DEFAULT_SCHEMA_PATH",
    "FAILURE_CATEGORIES",
    "PIPELINE_STAGES",
    "RECOVERABLE_FAILURE_CATEGORIES",
    "ROOT_DIR",
    "VALID_CHECK_STATUSES",
    "VALID_EXCLUSION_CATEGORIES",
    "VALID_PIPELINE_STAGES",
    "CheckResult",
    "DriftCheckResult",
    "DriftMonitoringResult",
    "DriftObservation",
    "PipelineMonitoringResult",
    "_sanitize_value_for_json",
    "find_nan_or_inf",
    "is_recoverable_category",
]
