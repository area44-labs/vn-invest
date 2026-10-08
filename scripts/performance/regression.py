"""Performance Regression Detection Engine.

Evaluates pipeline stage timing records against centralized stage baselines and thresholds
to detect significant performance degradation.
"""

from typing import Any

PERFORMANCE_STAGE_BASELINES = {
    "pipeline": 10.0,
    "benchmark_fetch": 1.0,
    "stock_fetch": 5.0,
    "temporal_validation": 0.5,
    "market_calculation": 0.5,
    "regime_calculation": 0.5,
    "risk_calculation": 1.0,
    "recommendation_calculation": 2.0,
    "monitoring": 1.5,
    "payload_validation": 0.5,
}

PERFORMANCE_STAGE_THRESHOLDS = {
    "pipeline": (1.5, 2.5, 5.0),
    "benchmark_fetch": (2.0, 4.0, 1.0),
    "stock_fetch": (1.5, 3.0, 3.0),
    "temporal_validation": (2.0, 4.0, 0.5),
    "market_calculation": (2.0, 4.0, 0.5),
    "regime_calculation": (2.0, 4.0, 0.5),
    "risk_calculation": (2.0, 4.0, 1.0),
    "recommendation_calculation": (2.0, 4.0, 1.0),
    "monitoring": (2.0, 4.0, 1.0),
    "payload_validation": (2.0, 4.0, 0.5),
}

# Production Live Update Baselines & Thresholds
# Account for DEFAULT_UPDATE_THROTTLE_DELAY = 3.5s per symbol and 44 candidate + 2 benchmark symbols
PRODUCTION_UPDATE_PERFORMANCE_BASELINES = {
    "pipeline": 200.0,
    "benchmark_fetch": 10.0,
    "stock_fetch": 185.0,
    "temporal_validation": 0.5,
    "market_calculation": 0.5,
    "regime_calculation": 0.5,
    "risk_calculation": 1.0,
    "recommendation_calculation": 2.0,
    "monitoring": 1.5,
    "payload_validation": 0.5,
}

PRODUCTION_UPDATE_PERFORMANCE_THRESHOLDS = {
    "pipeline": (1.3, 1.6, 10.0),
    "benchmark_fetch": (2.0, 3.0, 2.0),
    "stock_fetch": (1.3, 1.6, 10.0),
    "temporal_validation": (2.0, 4.0, 0.5),
    "market_calculation": (2.0, 4.0, 0.5),
    "regime_calculation": (2.0, 4.0, 0.5),
    "risk_calculation": (2.0, 4.0, 1.0),
    "recommendation_calculation": (2.0, 4.0, 1.0),
    "monitoring": (2.0, 4.0, 1.0),
    "payload_validation": (2.0, 4.0, 0.5),
}


def evaluate_performance_regression(
    performance_data: dict[str, Any],
    baselines_override: dict[str, float] | None = None,
    thresholds_override: dict[str, tuple[float, float, float]] | None = None,
    is_update_mode: bool | None = None,
) -> dict[str, Any]:
    """Evaluate pipeline stage timing records against centralized stage baselines and thresholds.

    Returns structured dict with overall_status ("PASS", "DEGRADED", "FAILED")
    and stage_evaluations list.
    """
    if not isinstance(performance_data, dict):
        raise TypeError(f"performance_data must be a dict, got {type(performance_data).__name__}")

    stages = performance_data.get("stages", [])
    if not isinstance(stages, list):
        raise TypeError(f"stages must be a list, got {type(stages).__name__}")

    if is_update_mode is None:
        stock_fetch_elapsed = next(
            (
                float(st.get("elapsed_seconds", 0.0))
                for st in stages
                if isinstance(st, dict) and st.get("stage") == "stock_fetch"
            ),
            0.0,
        )
        provider = (
            performance_data.get("provider", {})
            if isinstance(performance_data.get("provider"), dict)
            else {}
        )
        provider_elapsed = float(provider.get("total_elapsed_seconds", 0.0))
        is_update_mode = stock_fetch_elapsed > 30.0 or provider_elapsed > 30.0

    if is_update_mode:
        default_baselines = PRODUCTION_UPDATE_PERFORMANCE_BASELINES
        default_thresholds = PRODUCTION_UPDATE_PERFORMANCE_THRESHOLDS
    else:
        default_baselines = PERFORMANCE_STAGE_BASELINES
        default_thresholds = PERFORMANCE_STAGE_THRESHOLDS

    baselines = dict(default_baselines)
    if baselines_override:
        baselines.update(baselines_override)

    thresholds = dict(default_thresholds)
    if thresholds_override:
        thresholds.update(thresholds_override)

    stage_evaluations: list[dict[str, Any]] = []
    overall_status = "PASS"

    for st in stages:
        if not isinstance(st, dict):
            continue
        stage_name = str(st.get("stage", "unknown"))
        actual_seconds = float(st.get("elapsed_seconds", 0.0))
        exec_status = str(st.get("status", "SUCCESS"))

        if stage_name in baselines:
            baseline_seconds = float(baselines[stage_name])
            deg_mult, fail_mult, noise_floor = thresholds.get(stage_name, (2.0, 4.0, 1.0))

            deg_threshold = max(baseline_seconds * deg_mult, noise_floor)
            fail_threshold = max(baseline_seconds * fail_mult, noise_floor)

            exceeded_ratio = (
                round(actual_seconds / baseline_seconds, 4) if baseline_seconds > 0 else 1.0
            )

            if exec_status == "FAILED":
                status = "FAILED"
                message = f"Stage '{stage_name}' failed during execution"
            elif actual_seconds > fail_threshold:
                status = "FAILED"
                message = (
                    f"Stage '{stage_name}' duration {actual_seconds:.4f}s exceeded FAILED threshold "
                    f"{fail_threshold:.4f}s (baseline={baseline_seconds:.4f}s, exceeded_ratio={exceeded_ratio:.2f}x)"
                )
            elif actual_seconds > deg_threshold:
                status = "DEGRADED"
                message = (
                    f"Stage '{stage_name}' duration {actual_seconds:.4f}s exceeded DEGRADED threshold "
                    f"{deg_threshold:.4f}s (baseline={baseline_seconds:.4f}s, exceeded_ratio={exceeded_ratio:.2f}x)"
                )
            elif exec_status == "DEGRADED":
                status = "DEGRADED"
                message = f"Stage '{stage_name}' marked DEGRADED during execution"
            else:
                status = "PASS"
                message = (
                    f"Stage '{stage_name}' duration {actual_seconds:.4f}s within thresholds "
                    f"(baseline={baseline_seconds:.4f}s)"
                )
        else:
            baseline_seconds = 0.0
            exceeded_ratio = 1.0
            if exec_status == "FAILED":
                status = "FAILED"
                message = f"Stage '{stage_name}' failed during execution"
            else:
                status = "UNBASELINED"
                message = f"Stage '{stage_name}' has no baseline defined"

        if status == "FAILED":
            overall_status = "FAILED"
        elif status == "DEGRADED" and overall_status != "FAILED":
            overall_status = "DEGRADED"

        stage_evaluations.append(
            {
                "stage": stage_name,
                "baseline_seconds": baseline_seconds,
                "actual_seconds": round(actual_seconds, 4),
                "exceeded_ratio": exceeded_ratio,
                "status": status,
                "message": message,
            }
        )

    return {
        "overall_status": overall_status,
        "stage_evaluations": stage_evaluations,
    }


__all__ = ["evaluate_performance_regression"]
