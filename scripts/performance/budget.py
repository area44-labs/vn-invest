"""Performance Budget Evaluator and Threshold Enforcement.

Evaluates provider and pipeline operation metrics against centralized performance budget thresholds.
Supports configurable budget overrides and optional CI budget enforcement toggles.
"""

import os
from typing import Any

PROVIDER_BUDGET = {
    "max_total_calls": 120,
    "max_duplicate_operations": 5,
    "max_total_elapsed_seconds": 60.0,
}


def evaluate_provider_budget(
    performance_data: dict[str, Any],
    budget_config_override: dict[str, Any] | None = None,
    enforce_ci_budget: bool | None = None,
) -> dict[str, Any]:
    """Evaluate provider operations metrics against performance budget thresholds.

    `duplicate_operations_count` is the count of duplicate operation symbol records
    present in the `duplicate_operations` list.

    Returns structured dict matching schemas/v2/performance.schema.json with overall_status
    ("PASS", "DEGRADED", or "FAILED") and violation details.
    """
    if not isinstance(performance_data, dict):
        raise TypeError(f"performance_data must be a dict, got {type(performance_data).__name__}")

    provider = performance_data.get("provider", {})
    duplicates = performance_data.get("duplicate_operations", [])

    total_calls = int(provider.get("total_calls", 0)) if isinstance(provider, dict) else 0
    duplicate_operations_count = len(duplicates) if isinstance(duplicates, list) else 0
    total_elapsed_seconds = (
        float(provider.get("total_elapsed_seconds", 0.0)) if isinstance(provider, dict) else 0.0
    )

    # Use budget overrides if provided, otherwise default to centralized PROVIDER_BUDGET config
    config = dict(PROVIDER_BUDGET)
    if budget_config_override:
        config.update(budget_config_override)

    max_calls_budget = int(config.get("max_total_calls", 120))
    max_duplicates_budget = int(config.get("max_duplicate_operations", 5))
    max_elapsed_budget_seconds = float(config.get("max_total_elapsed_seconds", 60.0))

    violations: list[str] = []
    if total_calls > max_calls_budget:
        violations.append(
            f"Total provider calls ({total_calls}) exceeded budget ({max_calls_budget})"
        )

    if duplicate_operations_count > max_duplicates_budget:
        violations.append(
            f"Duplicate operations count ({duplicate_operations_count}) exceeded budget ({max_duplicates_budget})"
        )

    if total_elapsed_seconds > max_elapsed_budget_seconds:
        violations.append(
            f"Total provider elapsed time ({total_elapsed_seconds:.4f}s) exceeded budget ({max_elapsed_budget_seconds:.4f}s)"
        )

    # Check whether CI budget enforcement is enabled
    # Explicit enforce_ci_budget parameter takes precedence over environment variable
    if enforce_ci_budget is None:
        is_ci_enforced = os.getenv("ENABLE_PERFORMANCE_BUDGETS", "").lower() in (
            "1",
            "true",
            "yes",
        )
    else:
        is_ci_enforced = bool(enforce_ci_budget)

    overall_status = ("FAILED" if is_ci_enforced else "DEGRADED") if violations else "PASS"

    return {
        "overall_status": overall_status,
        "total_calls": total_calls,
        "max_calls_budget": max_calls_budget,
        "duplicate_operations_count": duplicate_operations_count,
        "max_duplicates_budget": max_duplicates_budget,
        "total_elapsed_seconds": round(total_elapsed_seconds, 4),
        "max_elapsed_budget_seconds": max_elapsed_budget_seconds,
        "violations": violations,
    }


__all__ = ["evaluate_provider_budget"]
