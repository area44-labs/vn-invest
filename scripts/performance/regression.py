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


def extract_update_workload_counts(
    performance_data: dict[str, Any],
) -> tuple[int, int]:
    """Extract actual benchmark and stock request/call counts from workload metadata.

    Returns tuple of (n_benchmarks, n_stocks).
    Raises ValueError if required workload metadata is missing or incomplete.
    """
    benchmarks = {"VNINDEX", "VN30"}
    n_benchmarks = 0
    n_stocks = 0

    # 1. Inspect global provider call history
    call_history = []
    try:
        from scripts.data_provider import VnstockDataProvider

        call_history = VnstockDataProvider.get_global_call_history()
    except ImportError:
        pass

    if call_history:
        for c in call_history:
            if not isinstance(c, dict):
                continue
            sym = str(c.get("symbol") or "").strip().upper()
            if not sym:
                continue
            if sym in benchmarks:
                n_benchmarks += 1
            else:
                n_stocks += 1

    # 2. Inspect duplicate_operations or call records in performance_data if call_history is empty
    if n_benchmarks == 0 or n_stocks == 0:
        duplicates = performance_data.get("duplicate_operations", [])
        if isinstance(duplicates, list) and duplicates:
            for d in duplicates:
                if not isinstance(d, dict):
                    continue
                sym = str(d.get("symbol") or "").strip().upper()
                req_cnt = int(d.get("request_count") or d.get("provider_call_count") or 1)
                if sym in benchmarks:
                    n_benchmarks += req_cnt
                elif sym:
                    n_stocks += req_cnt

    if n_benchmarks <= 0 or n_stocks <= 0:
        raise ValueError(
            f"Missing required workload metadata in performance_data for live update regression evaluation "
            f"(n_benchmarks={n_benchmarks}, n_stocks={n_stocks})"
        )

    return n_benchmarks, n_stocks


def compute_live_update_baselines(
    performance_data: dict[str, Any],
) -> tuple[dict[str, float], dict[str, tuple[float, float, float]]]:
    """Compute dynamic live update baselines based on actual workload and DEFAULT_UPDATE_THROTTLE_DELAY."""
    from scripts.pipeline.constants import DEFAULT_UPDATE_THROTTLE_DELAY

    n_benchmarks, n_stocks = extract_update_workload_counts(performance_data)

    # Throttle delay (3.5s) + average network roundtrip latency (~0.8s) per request
    per_call_expected_seconds = DEFAULT_UPDATE_THROTTLE_DELAY + 0.8

    bench_baseline = max(1.0, round(n_benchmarks * per_call_expected_seconds, 1))
    stock_baseline = max(5.0, round(n_stocks * per_call_expected_seconds, 1))
    pipeline_baseline = max(10.0, round(bench_baseline + stock_baseline + 5.0, 1))

    baselines = dict(PERFORMANCE_STAGE_BASELINES)
    baselines["benchmark_fetch"] = bench_baseline
    baselines["stock_fetch"] = stock_baseline
    baselines["pipeline"] = pipeline_baseline

    thresholds = dict(PERFORMANCE_STAGE_THRESHOLDS)
    thresholds["benchmark_fetch"] = (2.0, 3.0, 2.0)
    thresholds["stock_fetch"] = (1.3, 2.5, 10.0)
    thresholds["pipeline"] = (1.3, 2.0, 10.0)

    return baselines, thresholds


def evaluate_performance_regression(
    performance_data: dict[str, Any],
    baselines_override: dict[str, float] | None = None,
    thresholds_override: dict[str, tuple[float, float, float]] | None = None,
    is_update_mode: bool = False,
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

    if is_update_mode:
        default_baselines, default_thresholds = compute_live_update_baselines(performance_data)
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
