"""Performance payload validation, schemas, and fallback evaluation functions."""

from typing import Any


from scripts.performance.budget import evaluate_provider_budget
from scripts.performance.regression import evaluate_performance_regression


def load_performance_schema(
    schema_path: str | None = None,
    version: str | None = None,
) -> dict:
    """Load performance JSON Schema via centralized registry."""
    from scripts.schema import SCHEMA_VERSION, load_schema_for_version

    ver = version or SCHEMA_VERSION
    return load_schema_for_version("performance", str(ver))


def validate_performance_payload(
    performance_data: dict, schema: dict | None = None, version: str | None = None
) -> None:
    """Validate canonical performance object structure and schema using version-aware registry.

    Raises jsonschema.ValidationError, TypeError, SchemaResolutionError, or ValueError on validation failure.
    """
    from scripts.pipeline.validation import validate_performance_payload as pipeline_val_perf

    pipeline_val_perf(performance_data, schema=schema, version=version)


def create_default_performance_payload() -> dict[str, Any]:
    """Construct a minimal valid performance payload for test harness or explicit fallback contexts only.

    MUST NOT be used in production monitoring to swallow or replace missing performance data.
    """
    payload = {
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


__all__ = [
    "create_default_performance_payload",
    "evaluate_performance_regression",
    "evaluate_provider_budget",
    "load_performance_schema",
    "validate_performance_payload",
]
