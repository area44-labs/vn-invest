"""Performance payload validation, schemas, and fallback evaluation functions."""

import json
import os
from typing import Any

import jsonschema

from scripts.monitoring.models import DEFAULT_PERFORMANCE_SCHEMA_PATH
from scripts.performance.budget import evaluate_provider_budget
from scripts.performance.regression import evaluate_performance_regression


def load_performance_schema(
    schema_path: str | None = None,
) -> dict:
    """Load JSON Schema Draft 2020-12 from schemas/performance.schema.json."""
    if schema_path is None:
        schema_path = DEFAULT_PERFORMANCE_SCHEMA_PATH
    if not os.path.exists(schema_path):
        raise FileNotFoundError(f"Performance schema file not found at '{schema_path}'")
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_performance_payload(performance_data: dict, schema: dict | None = None) -> None:
    """Validate canonical performance object structure and schema.

    Raises jsonschema.ValidationError, TypeError, FileNotFoundError, or ValueError on validation failure.
    """
    if not isinstance(performance_data, dict):
        raise TypeError(
            f"Performance payload must be a dict, got {type(performance_data).__name__}"
        )

    if schema is None:
        schema = load_performance_schema()

    jsonschema.validate(instance=performance_data, schema=schema)


def create_default_performance_payload() -> dict[str, Any]:
    """Construct a minimal valid performance payload for test harness or explicit fallback contexts only.

    MUST NOT be used in production monitoring to swallow or replace missing performance data.
    """
    payload = {
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
