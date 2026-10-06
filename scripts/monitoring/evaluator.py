"""Evaluator engine for production monitoring pipeline."""

import json
import os
from datetime import UTC, datetime
from typing import Any

from scripts.lib.config import SIGNAL_MODEL_VERSION
from scripts.monitoring.checks import (
    check_data_freshness,
    check_history_index_status,
    check_market_regime_status,
    check_numeric_sanity,
    check_ohlcv_data_quality,
    check_required_artifacts,
    check_schema_validation,
    check_symbol_processing_counts,
    check_universe_audit_invariants,
)
from scripts.monitoring.drift import evaluate_data_and_model_drift
from scripts.monitoring.metrics import normalize_market_payload
from scripts.monitoring.models import (
    DEFAULT_GENERATED_DIR,
    DEFAULT_SCHEMA_PATH,
    VALID_CHECK_STATUSES,
    CheckResult,
    PipelineMonitoringResult,
    _sanitize_value_for_json,
)
from scripts.monitoring.performance import (
    validate_performance_payload,
)
from scripts.performance.budget import evaluate_provider_budget
from scripts.performance.regression import evaluate_performance_regression


def validate_monitoring_payload(payload: dict) -> bool:
    """Validate structure and invariants of a monitoring output dictionary.

    Fails closed by raising ValueError or TypeError if required fields are missing
    or if status fields contain invalid values.
    """
    if not isinstance(payload, dict):
        raise TypeError(f"Monitoring payload must be a dict, got {type(payload).__name__}")

    required_keys = ["overall_status", "generated_at", "data_as_of", "checks", "metrics"]
    for k in required_keys:
        if k not in payload:
            raise ValueError(f"Missing required key '{k}' in monitoring payload")

    if payload["overall_status"] not in VALID_CHECK_STATUSES:
        raise ValueError(
            f"Invalid overall_status '{payload['overall_status']}' in monitoring payload"
        )

    checks = payload["checks"]
    if not isinstance(checks, list):
        raise TypeError("Monitoring 'checks' must be a list")

    check_keys = ["check_name", "status", "measured_value", "expected_condition", "message"]
    for idx, ck in enumerate(checks):
        if not isinstance(ck, dict):
            raise TypeError(f"Check at index {idx} must be a dict")
        for key in check_keys:
            if key not in ck:
                raise ValueError(f"Check at index {idx} missing required key '{key}'")
        if ck["status"] not in VALID_CHECK_STATUSES:
            raise ValueError(f"Check '{ck['check_name']}' has invalid status '{ck['status']}'")

    if not isinstance(payload["metrics"], dict):
        raise TypeError("Monitoring 'metrics' must be a dict")

    return True


def evaluate_production_monitoring(
    generated_dir: str | None = None,
    recommendations_payload: dict | None = None,
    market_payload: dict | None = None,
    reference_date: str | None = None,
    schema_path: str | None = None,
    stock_data_map: dict | None = None,
    df_vnindex: Any | None = None,
    df_vn30: Any | None = None,
    universe_audit: dict | None = None,
    in_memory_artifacts: dict | None = None,
) -> PipelineMonitoringResult:
    """Execute operational production monitoring across the pipeline and generated artifacts.

    Deterministically executes all checks, aggregates check results, and assigns an explicit
    overall status ("PASS", "WARNING", "FAIL").

    Fail-Closed Rule:
    - If ANY check status is "FAIL", overall_status is "FAIL".
    - Else if ANY check status is "WARNING", overall_status is "WARNING".
    - Otherwise overall_status is "PASS".
    """
    g_dir = generated_dir or DEFAULT_GENERATED_DIR
    s_path = schema_path or DEFAULT_SCHEMA_PATH

    checks: list[CheckResult] = []

    # Determine data_as_of peek for artifact existence check
    data_as_of_peek = None
    if recommendations_payload is not None:
        data_as_of_peek = recommendations_payload.get("data_as_of")
    else:
        rec_file = os.path.join(g_dir, "recommendations.json")
        if os.path.exists(rec_file):
            try:
                with open(rec_file, "r", encoding="utf-8") as f:
                    rec_peek = json.load(f)
                    data_as_of_peek = rec_peek.get("data_as_of")
            except Exception:  # noqa: BLE001
                data_as_of_peek = None

    # 1. Artifact existence check (executed in-memory or on disk)
    artifact_chk = check_required_artifacts(
        g_dir, data_as_of=data_as_of_peek, in_memory_artifacts=in_memory_artifacts
    )
    checks.append(artifact_chk)

    # Load payloads if not provided in memory
    if recommendations_payload is None:
        rec_file = os.path.join(g_dir, "recommendations.json")
        if os.path.exists(rec_file):
            try:
                with open(rec_file, "r", encoding="utf-8") as f:
                    recommendations_payload = json.load(f)
            except Exception:  # noqa: BLE001
                recommendations_payload = None

        mkt_file = os.path.join(g_dir, "market.json")
        if os.path.exists(mkt_file):
            try:
                with open(mkt_file, "r", encoding="utf-8") as f:
                    market_payload = json.load(f)
            except Exception:  # noqa: BLE001
                market_payload = None

    if recommendations_payload is None:
        # Cannot proceed with deep payload checks
        generated_at = datetime.now(UTC).isoformat()
        metrics = {"error": "Missing or unreadable recommendations payload"}
        return PipelineMonitoringResult(
            overall_status="FAIL",
            generated_at=generated_at,
            data_as_of=None,
            checks=checks,
            metrics=metrics,
        )

    data_as_of = recommendations_payload.get("data_as_of")
    generated_at = recommendations_payload.get("generated_at", datetime.now(UTC).isoformat())

    raw_market = (
        market_payload if market_payload is not None else recommendations_payload.get("market")
    )
    market_payload = normalize_market_payload(raw_market, data_as_of=data_as_of)

    # 2. Schema validation check
    checks.append(check_schema_validation(recommendations_payload, schema_path=s_path))

    # 3. Data freshness check
    checks.append(check_data_freshness(data_as_of, reference_date=reference_date))

    # 4. Numeric sanity check (NaN/Inf safety) across recommendations and market payloads
    checks.append(check_numeric_sanity(recommendations_payload, market_payload=market_payload))

    # 5. Symbol processing counts check
    counts_chk = check_symbol_processing_counts(recommendations_payload)
    checks.append(counts_chk)

    # 5b. Universe audit invariants check
    if universe_audit is None:
        recs = recommendations_payload.get("recommendations", [])
        cand_proc = [
            r["symbol"]
            for r in recs
            if isinstance(r, dict) and r.get("data_quality") in ("SUFFICIENT", "PARTIAL")
        ]
        cand_insuf = [
            r["symbol"]
            for r in recs
            if isinstance(r, dict) and r.get("data_quality") == "INSUFFICIENT"
        ]
        benchmarks = ["VNINDEX", "VN30"]
        exp_list = sorted(
            set(benchmarks) | {r["symbol"] for r in recs if isinstance(r, dict) and r.get("symbol")}
        )
        proc_list = sorted(set(benchmarks) | set(cand_proc))
        insuf_list = sorted(set(cand_insuf))

        ex_list = [
            {
                "symbol": s,
                "category": "INSUFFICIENT_HISTORICAL_DATA",
                "reason": f"Symbol {s} has INSUFFICIENT data quality in recommendations",
            }
            for s in insuf_list
        ]

        universe_audit = {
            "expected_symbols": exp_list,
            "processed_symbols": proc_list,
            "invalid_symbols": [],
            "insufficient_history_symbols": insuf_list,
            "failed_symbols": [],
            "missing_symbols": [],
            "counts": {
                "expected_count": len(exp_list),
                "processed_count": len(proc_list),
                "invalid_count": 0,
                "insufficient_history_count": len(insuf_list),
                "failed_count": 0,
                "missing_count": 0,
            },
            "exclusions": ex_list,
            "performance": recommendations_payload.get("performance")
            if isinstance(recommendations_payload, dict)
            and "performance" in recommendations_payload
            else None,
        }

    audit_chk = check_universe_audit_invariants(universe_audit, recommendations_payload)
    checks.append(audit_chk)

    # 6. Market regime status check
    checks.append(check_market_regime_status(market_payload))

    # 7. History index integrity check (ALWAYS executed, fails closed if history/index.json is missing)
    checks.append(
        check_history_index_status(
            g_dir, data_as_of=data_as_of, in_memory_artifacts=in_memory_artifacts
        )
    )

    # 8. Benchmark OHLCV checks (if provided)
    if df_vnindex is not None:
        checks.append(check_ohlcv_data_quality(df_vnindex, "VNINDEX"))
    if df_vn30 is not None:
        checks.append(check_ohlcv_data_quality(df_vn30, "VN30"))

    # 9. Operational Data and Model Drift Detection check
    drift_res = evaluate_data_and_model_drift(
        generated_dir=g_dir,
        data_as_of=data_as_of,
        current_payload=recommendations_payload,
        market_payload=market_payload,
    )
    for d_chk in drift_res.drift_checks:
        c_res = CheckResult(
            check_name=d_chk.check_name,
            status=d_chk.status,
            measured_value=d_chk.observation.current_value,
            expected_condition=f"Within threshold of baseline ({d_chk.observation.baseline_value})",
            message=d_chk.observation.message,
        )
        checks.append(c_res)

    # 10. Performance Regression & Provider Budget checks
    if isinstance(universe_audit, dict):
        perf_data = universe_audit.get("performance")
    else:
        perf_data = None

    if perf_data is None:
        checks.append(
            CheckResult(
                check_name="performance_payload_integrity",
                status="FAIL",
                measured_value={"performance": None},
                expected_condition="Valid performance payload conforming to schemas/performance.schema.json",
                message="Performance payload is explicitly None or missing from universe audit",
            )
        )
        checks.append(
            CheckResult(
                check_name="performance_regression",
                status="FAIL",
                measured_value=None,
                expected_condition="Stage durations stay within performance baseline thresholds",
                message="Cannot evaluate performance regression because performance payload is missing",
            )
        )
        checks.append(
            CheckResult(
                check_name="provider_budget",
                status="FAIL",
                measured_value=None,
                expected_condition="Provider operations stay within allocated budget",
                message="Cannot evaluate provider budget because performance payload is missing",
            )
        )
    else:
        try:
            validate_performance_payload(perf_data)
            checks.append(
                CheckResult(
                    check_name="performance_payload_integrity",
                    status="PASS",
                    measured_value={"stages_count": len(perf_data.get("stages", []))},
                    expected_condition="Valid performance payload conforming to schemas/performance.schema.json",
                    message="Performance payload passed JSON schema validation",
                )
            )

            reg_eval = evaluate_performance_regression(perf_data)
            perf_data["regression"] = reg_eval

            if reg_eval["overall_status"] == "FAILED":
                reg_status = "FAIL"
                failed_msgs = [
                    e["message"] for e in reg_eval["stage_evaluations"] if e["status"] == "FAILED"
                ]
                reg_msg = f"Performance regression detected: {'; '.join(failed_msgs)}"
            elif reg_eval["overall_status"] == "DEGRADED":
                reg_status = "WARNING"
                deg_msgs = [
                    e["message"] for e in reg_eval["stage_evaluations"] if e["status"] == "DEGRADED"
                ]
                reg_msg = f"Performance degradation detected: {'; '.join(deg_msgs)}"
            else:
                reg_status = "PASS"
                reg_msg = "All pipeline stage durations are within performance baseline thresholds"

            checks.append(
                CheckResult(
                    check_name="performance_regression",
                    status=reg_status,
                    measured_value=reg_eval,
                    expected_condition="All pipeline stage durations stay within performance baseline thresholds",
                    message=reg_msg,
                )
            )

            bud_eval = evaluate_provider_budget(perf_data)
            perf_data["budget"] = bud_eval

            if bud_eval["overall_status"] in ("DEGRADED", "FAILED") or bud_eval.get("violations"):
                bud_status = "WARNING"
                bud_msg = f"Provider budget exceeded: {'; '.join(bud_eval['violations'])}"
            else:
                bud_status = "PASS"
                bud_msg = (
                    f"Provider budget check passed ({bud_eval['total_calls']}/{bud_eval['max_calls_budget']} calls, "
                    f"{bud_eval['duplicate_operations_count']}/{bud_eval['max_duplicates_budget']} duplicates, "
                    f"{bud_eval['total_elapsed_seconds']:.2f}s/{bud_eval['max_elapsed_budget_seconds']:.2f}s elapsed)"
                )

            checks.append(
                CheckResult(
                    check_name="provider_budget",
                    status=bud_status,
                    measured_value=bud_eval,
                    expected_condition="Provider operations stay within allocated call, duplicate, and time budgets",
                    message=bud_msg,
                )
            )
        except Exception as err:  # noqa: BLE001
            checks.append(
                CheckResult(
                    check_name="performance_payload_integrity",
                    status="FAIL",
                    measured_value={"error": str(err)},
                    expected_condition="Valid performance payload conforming to schemas/performance.schema.json",
                    message=f"Performance payload schema validation failed: {err}",
                )
            )
            checks.append(
                CheckResult(
                    check_name="performance_regression",
                    status="FAIL",
                    measured_value=None,
                    expected_condition="Stage durations stay within performance baseline thresholds",
                    message=f"Cannot evaluate performance regression due to malformed payload: {err}",
                )
            )
            checks.append(
                CheckResult(
                    check_name="provider_budget",
                    status="FAIL",
                    measured_value=None,
                    expected_condition="Provider operations stay within allocated budget",
                    message=f"Cannot evaluate provider budget due to malformed payload: {err}",
                )
            )

    # Aggregate overall status
    statuses = [c.status for c in checks]
    if "FAIL" in statuses:
        overall_status = "FAIL"
    elif "WARNING" in statuses:
        overall_status = "WARNING"
    else:
        overall_status = "PASS"

    failed_monitoring_diagnostics = [
        {
            "stage": "MONITORING",
            "category": "MONITORING_FAILURE",
            "check": c.check_name,
            "status": "FAIL",
            "measured_value": _sanitize_value_for_json(c.measured_value),
            "expected_condition": c.expected_condition,
            "reason": c.message,
        }
        for c in checks
        if c.status == "FAIL"
    ]

    summary = recommendations_payload.get("summary", {})
    metrics = {
        "signal_model_version": recommendations_payload.get(
            "signal_model_version", SIGNAL_MODEL_VERSION
        ),
        "total_scanned": summary.get(
            "total_scanned", len(recommendations_payload.get("recommendations", []))
        ),
        "buy_count": summary.get("buy_count", 0),
        "watch_count": summary.get("watch_count", 0),
        "hold_count": summary.get("hold_count", 0),
        "sell_count": summary.get("sell_count", 0),
        "avoid_count": summary.get("avoid_count", 0),
        "market_regime": market_payload.get("market", {}).get("regime"),
        "universe_audit": universe_audit,
        "performance": universe_audit.get("performance")
        if isinstance(universe_audit, dict)
        else None,
        "drift_monitoring": drift_res.to_dict(),
        "monitoring_diagnostics": failed_monitoring_diagnostics,
        "failed_checks": failed_monitoring_diagnostics,
        "check_counts": {
            "total_checks": len(checks),
            "pass_count": statuses.count("PASS"),
            "warning_count": statuses.count("WARNING"),
            "fail_count": statuses.count("FAIL"),
        },
    }

    result = PipelineMonitoringResult(
        overall_status=overall_status,
        generated_at=generated_at,
        data_as_of=data_as_of,
        checks=checks,
        metrics=metrics,
    )

    validate_monitoring_payload(result.to_dict())

    return result


__all__ = ["evaluate_production_monitoring", "validate_monitoring_payload"]
