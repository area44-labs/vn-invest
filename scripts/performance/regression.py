"""Performance Regression Detection Engine.

Evaluates pipeline stage timing records against centralized stage baselines and thresholds
to detect significant performance degradation.
"""

from typing import Any

from scripts.lib.config import (
    PERFORMANCE_STAGE_BASELINES,
    PERFORMANCE_STAGE_THRESHOLDS,
)


def evaluate_performance_regression(
    performance_data: dict[str, Any],
    baselines_override: dict[str, float] | None = None,
    thresholds_override: dict[str, tuple[float, float, float]] | None = None,
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

    baselines = dict(PERFORMANCE_STAGE_BASELINES)
    if baselines_override:
        baselines.update(baselines_override)

    thresholds = dict(PERFORMANCE_STAGE_THRESHOLDS)
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
