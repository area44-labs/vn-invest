"""Operational data and model-output drift detection module."""

import json
import math
import os
from typing import Any

from scripts.monitoring.metrics import extract_recommendation_metrics, is_canonical_yyyy_mm_dd
from scripts.monitoring.models import (
    CANONICAL_CONFIDENCE_BUCKETS,
    DEFAULT_GENERATED_DIR,
    DriftCheckResult,
    DriftMonitoringResult,
    DriftObservation,
    find_nan_or_inf,
)

DRIFT_LOOKBACK_REPORTS = 20
DRIFT_MIN_BASELINE_REPORTS = 5
DRIFT_MIN_PROCESSED_RATIO = 0.80

DRIFT_THRESHOLD_PROCESSED_RATIO = (0.15, 0.30)
DRIFT_THRESHOLD_BREADTH_RATIO = (0.25, 0.40)
DRIFT_THRESHOLD_ACTION_DISTRIBUTION = (0.20, 0.35)
DRIFT_THRESHOLD_CONFIDENCE_DISTRIBUTION = (0.25, 0.40)
DRIFT_BOUNDARY_TOLERANCE_ACTION_DISTRIBUTION = 0.001

DRIFT_THRESHOLD_SIGNAL_SCORE_MEAN = (15.0, 25.0)
DRIFT_THRESHOLD_RISK_ADJUSTED_SCORE_MEAN = (15.0, 25.0)
DRIFT_THRESHOLD_CONFIDENCE_MEAN = (0.15, 0.25)
DRIFT_THRESHOLD_VNINDEX_CHANGE_PCT = (3.0, 5.0)


def evaluate_data_and_model_drift(
    generated_dir: str | None = None,
    data_as_of: str | None = None,
    current_payload: dict | None = None,
    market_payload: dict | None = None,
    history_index_data: dict | None = None,
    baseline_reports: list[dict] | None = None,
    lookback_reports: int = DRIFT_LOOKBACK_REPORTS,
    min_baseline_reports: int = DRIFT_MIN_BASELINE_REPORTS,
    min_processed_ratio: float = DRIFT_MIN_PROCESSED_RATIO,
) -> DriftMonitoringResult:
    """Evaluate operational data drift and model-output drift against historical baseline.

    Strict Temporal Safety:
    - At evaluation date T, baseline reports MUST strictly have data_as_of < T.
    - Future artifacts (> T) or chronologically invalid index ordering fail closed (FAIL status).
    - If baseline reports count < min_baseline_reports, returns INSUFFICIENT baseline status (WARNING).
    - Operational monitoring layer ONLY: does NOT evaluate model error, predictive validity, or profitability.
    """
    g_dir = generated_dir or DEFAULT_GENERATED_DIR

    # 0. Validate baseline configuration parameters and thresholds fail closed with exceptions
    if isinstance(lookback_reports, bool) or not isinstance(lookback_reports, int):
        raise TypeError(
            f"lookback_reports must be an integer, got {type(lookback_reports).__name__}"
        )
    if lookback_reports <= 0:
        raise ValueError(f"lookback_reports must be positive, got {lookback_reports}")

    if isinstance(min_baseline_reports, bool) or not isinstance(min_baseline_reports, int):
        raise TypeError(
            f"min_baseline_reports must be an integer, got {type(min_baseline_reports).__name__}"
        )
    if min_baseline_reports <= 0:
        raise ValueError(f"min_baseline_reports must be positive, got {min_baseline_reports}")

    if min_baseline_reports > lookback_reports:
        raise ValueError(
            f"min_baseline_reports ({min_baseline_reports}) cannot exceed lookback_reports ({lookback_reports})"
        )

    if isinstance(min_processed_ratio, bool) or not isinstance(min_processed_ratio, (int, float)):
        raise TypeError(
            f"min_processed_ratio must be a numeric float, got {type(min_processed_ratio).__name__}"
        )
    if math.isnan(min_processed_ratio) or math.isinf(min_processed_ratio):
        raise ValueError(f"min_processed_ratio must be finite, got {min_processed_ratio}")
    if not (0.0 < min_processed_ratio <= 1.0):
        raise ValueError(f"min_processed_ratio must be in (0.0, 1.0], got {min_processed_ratio}")

    # Validate drift threshold configurations dynamically from module globals and scripts.monitoring
    import sys

    mon_sub = sys.modules.get("scripts.monitoring")

    def _get_thresh(name, default):
        if mon_sub and hasattr(mon_sub, name):
            return getattr(mon_sub, name)
        return globals().get(name, default)

    thresh_configs = [
        (
            "DRIFT_THRESHOLD_PROCESSED_RATIO",
            _get_thresh("DRIFT_THRESHOLD_PROCESSED_RATIO", DRIFT_THRESHOLD_PROCESSED_RATIO),
        ),
        (
            "DRIFT_THRESHOLD_BREADTH_RATIO",
            _get_thresh("DRIFT_THRESHOLD_BREADTH_RATIO", DRIFT_THRESHOLD_BREADTH_RATIO),
        ),
        (
            "DRIFT_THRESHOLD_VNINDEX_CHANGE_PCT",
            _get_thresh("DRIFT_THRESHOLD_VNINDEX_CHANGE_PCT", DRIFT_THRESHOLD_VNINDEX_CHANGE_PCT),
        ),
        (
            "DRIFT_THRESHOLD_ACTION_DISTRIBUTION",
            _get_thresh("DRIFT_THRESHOLD_ACTION_DISTRIBUTION", DRIFT_THRESHOLD_ACTION_DISTRIBUTION),
        ),
        (
            "DRIFT_THRESHOLD_CONFIDENCE_DISTRIBUTION",
            _get_thresh(
                "DRIFT_THRESHOLD_CONFIDENCE_DISTRIBUTION", DRIFT_THRESHOLD_CONFIDENCE_DISTRIBUTION
            ),
        ),
        (
            "DRIFT_THRESHOLD_SIGNAL_SCORE_MEAN",
            _get_thresh("DRIFT_THRESHOLD_SIGNAL_SCORE_MEAN", DRIFT_THRESHOLD_SIGNAL_SCORE_MEAN),
        ),
        (
            "DRIFT_THRESHOLD_RISK_ADJUSTED_SCORE_MEAN",
            _get_thresh(
                "DRIFT_THRESHOLD_RISK_ADJUSTED_SCORE_MEAN", DRIFT_THRESHOLD_RISK_ADJUSTED_SCORE_MEAN
            ),
        ),
        (
            "DRIFT_THRESHOLD_CONFIDENCE_MEAN",
            _get_thresh("DRIFT_THRESHOLD_CONFIDENCE_MEAN", DRIFT_THRESHOLD_CONFIDENCE_MEAN),
        ),
    ]
    for thresh_name, thresh_tuple in thresh_configs:
        if not isinstance(thresh_tuple, (tuple, list)) or len(thresh_tuple) != 2:
            raise TypeError(
                f"Threshold configuration {thresh_name} must be a tuple or list of length 2"
            )
        warn, fail = thresh_tuple
        if (
            isinstance(warn, bool)
            or not isinstance(warn, (int, float))
            or math.isnan(warn)
            or math.isinf(warn)
            or warn < 0
        ):
            raise ValueError(
                f"Threshold configuration {thresh_name} warning value is invalid: {warn}"
            )
        if (
            isinstance(fail, bool)
            or not isinstance(fail, (int, float))
            or math.isnan(fail)
            or math.isinf(fail)
            or fail < warn
        ):
            raise ValueError(
                f"Threshold configuration {thresh_name} fail value ({fail}) must be >= warning value ({warn})"
            )

    # Load current payload if not provided
    if current_payload is None:
        rec_file = os.path.join(g_dir, "recommendations.json")
        if os.path.exists(rec_file):
            try:
                with open(rec_file, "r", encoding="utf-8") as f:
                    current_payload = json.load(f)
            except Exception as err:  # noqa: BLE001
                obs = DriftObservation(
                    check_name="drift_current_payload",
                    baseline_period={"status": "NO_CURRENT_PAYLOAD"},
                    current_period=data_as_of or "UNKNOWN",
                    baseline_value=None,
                    current_value=None,
                    absolute_difference=None,
                    threshold=None,
                    status="FAIL",
                    message=f"Failed to read current recommendations payload: {err}",
                )
                chk = DriftCheckResult(
                    check_name="drift_current_payload", status="FAIL", observation=obs
                )
                return DriftMonitoringResult(
                    overall_status="FAIL",
                    data_as_of=data_as_of,
                    baseline_summary={"status": "FAIL", "reason": str(err)},
                    drift_checks=[chk],
                )

    if not current_payload or not isinstance(current_payload, dict):
        obs = DriftObservation(
            check_name="drift_current_payload",
            baseline_period={"status": "INVALID_CURRENT_PAYLOAD"},
            current_period=data_as_of or "UNKNOWN",
            baseline_value=None,
            current_value=None,
            absolute_difference=None,
            threshold=None,
            status="FAIL",
            message="Current recommendations payload is missing or not a dict",
        )
        chk = DriftCheckResult(check_name="drift_current_payload", status="FAIL", observation=obs)
        return DriftMonitoringResult(
            overall_status="FAIL",
            data_as_of=data_as_of,
            baseline_summary={"status": "FAIL", "reason": "Invalid payload"},
            drift_checks=[chk],
        )

    curr_payload_date = current_payload.get("data_as_of")

    if data_as_of is not None:
        if not is_canonical_yyyy_mm_dd(data_as_of):
            obs = DriftObservation(
                check_name="drift_data_as_of_format",
                baseline_period={"status": "INVALID_DATA_AS_OF"},
                current_period=str(data_as_of),
                baseline_value=None,
                current_value=data_as_of,
                absolute_difference=None,
                threshold=None,
                status="FAIL",
                message=f"Provided data_as_of '{data_as_of}' is not a valid canonical YYYY-MM-DD date string",
            )
            chk = DriftCheckResult(
                check_name="drift_data_as_of_format", status="FAIL", observation=obs
            )
            return DriftMonitoringResult(
                overall_status="FAIL",
                data_as_of=None,
                baseline_summary={"status": "FAIL", "reason": "Invalid data_as_of format"},
                drift_checks=[chk],
            )

        if curr_payload_date != data_as_of:
            obs = DriftObservation(
                check_name="drift_data_as_of_mismatch",
                baseline_period={"expected_data_as_of": data_as_of},
                current_period=str(curr_payload_date),
                baseline_value=data_as_of,
                current_value=curr_payload_date,
                absolute_difference=None,
                threshold=None,
                status="FAIL",
                message=f"Current recommendations payload data_as_of '{curr_payload_date}' does not match evaluation data_as_of '{data_as_of}'",
            )
            chk = DriftCheckResult(
                check_name="drift_data_as_of_mismatch", status="FAIL", observation=obs
            )
            return DriftMonitoringResult(
                overall_status="FAIL",
                data_as_of=data_as_of,
                baseline_summary={
                    "status": "FAIL",
                    "reason": "data_as_of mismatch between payload and evaluation date",
                },
                drift_checks=[chk],
            )
    else:
        if not is_canonical_yyyy_mm_dd(curr_payload_date):
            obs = DriftObservation(
                check_name="drift_data_as_of_format",
                baseline_period={"status": "MISSING_OR_INVALID_DATA_AS_OF"},
                current_period=str(curr_payload_date),
                baseline_value=None,
                current_value=curr_payload_date,
                absolute_difference=None,
                threshold=None,
                status="FAIL",
                message=f"Current recommendations payload data_as_of '{curr_payload_date}' is missing or not a canonical YYYY-MM-DD date string",
            )
            chk = DriftCheckResult(
                check_name="drift_data_as_of_format", status="FAIL", observation=obs
            )
            return DriftMonitoringResult(
                overall_status="FAIL",
                data_as_of=None,
                baseline_summary={
                    "status": "FAIL",
                    "reason": "Missing or invalid data_as_of in payload",
                },
                drift_checks=[chk],
            )
        data_as_of = curr_payload_date

    # Validate market_payload temporal consistency if provided
    if market_payload is not None:
        if not isinstance(market_payload, dict):
            obs = DriftObservation(
                check_name="drift_market_payload_temporal_safety",
                baseline_period={"status": "INVALID_MARKET_PAYLOAD"},
                current_period=data_as_of,
                baseline_value=None,
                current_value=type(market_payload).__name__,
                absolute_difference=None,
                threshold=None,
                status="FAIL",
                message="Explicit market_payload provided is not a dict",
            )
            chk = DriftCheckResult(
                check_name="drift_market_payload_temporal_safety", status="FAIL", observation=obs
            )
            return DriftMonitoringResult(
                overall_status="FAIL",
                data_as_of=data_as_of,
                baseline_summary={"status": "FAIL", "reason": "Invalid market_payload type"},
                drift_checks=[chk],
            )

        m_date = market_payload.get("data_as_of")
        if not m_date and "market" in market_payload and isinstance(market_payload["market"], dict):
            m_date = market_payload["market"].get("data_as_of")

        if m_date is not None:
            if not is_canonical_yyyy_mm_dd(m_date):
                obs = DriftObservation(
                    check_name="drift_market_payload_temporal_safety",
                    baseline_period={"status": "INVALID_MARKET_DATE"},
                    current_period=data_as_of,
                    baseline_value=data_as_of,
                    current_value=m_date,
                    absolute_difference=None,
                    threshold=None,
                    status="FAIL",
                    message=f"Explicit market_payload data_as_of '{m_date}' is not a canonical YYYY-MM-DD date string",
                )
                chk = DriftCheckResult(
                    check_name="drift_market_payload_temporal_safety",
                    status="FAIL",
                    observation=obs,
                )
                return DriftMonitoringResult(
                    overall_status="FAIL",
                    data_as_of=data_as_of,
                    baseline_summary={
                        "status": "FAIL",
                        "reason": "Invalid market_payload date format",
                    },
                    drift_checks=[chk],
                )

            if m_date != data_as_of:
                obs = DriftObservation(
                    check_name="drift_market_payload_temporal_safety",
                    baseline_period={"expected_data_as_of": data_as_of},
                    current_period=str(m_date),
                    baseline_value=data_as_of,
                    current_value=m_date,
                    absolute_difference=None,
                    threshold=None,
                    status="FAIL",
                    message=f"Temporal safety violation: explicit market_payload date '{m_date}' does not match evaluation date '{data_as_of}'",
                )
                chk = DriftCheckResult(
                    check_name="drift_market_payload_temporal_safety",
                    status="FAIL",
                    observation=obs,
                )
                return DriftMonitoringResult(
                    overall_status="FAIL",
                    data_as_of=data_as_of,
                    baseline_summary={"status": "FAIL", "reason": "Market payload date mismatch"},
                    drift_checks=[chk],
                )
        else:
            is_inner_market = isinstance(
                current_payload, dict
            ) and market_payload is current_payload.get("market")
            if not is_inner_market:
                obs = DriftObservation(
                    check_name="drift_market_payload_temporal_safety",
                    baseline_period={"status": "MISSING_MARKET_DATE"},
                    current_period=data_as_of,
                    baseline_value=data_as_of,
                    current_value=None,
                    absolute_difference=None,
                    threshold=None,
                    status="FAIL",
                    message="Explicit standalone market_payload missing required data_as_of date field",
                )
                chk = DriftCheckResult(
                    check_name="drift_market_payload_temporal_safety",
                    status="FAIL",
                    observation=obs,
                )
                return DriftMonitoringResult(
                    overall_status="FAIL",
                    data_as_of=data_as_of,
                    baseline_summary={"status": "FAIL", "reason": "Missing market_payload date"},
                    drift_checks=[chk],
                )

    try:
        current_metrics = extract_recommendation_metrics(
            current_payload, market_payload=market_payload
        )
    except (ValueError, TypeError) as err:
        obs = DriftObservation(
            check_name="drift_current_payload_malformed",
            baseline_period={"status": "MALFORMED_CURRENT_PAYLOAD"},
            current_period=data_as_of,
            baseline_value=None,
            current_value=None,
            absolute_difference=None,
            threshold=None,
            status="FAIL",
            message=f"Current recommendation payload metrics extraction failed: {err}",
        )
        chk = DriftCheckResult(
            check_name="drift_current_payload_malformed", status="FAIL", observation=obs
        )
        return DriftMonitoringResult(
            overall_status="FAIL",
            data_as_of=data_as_of,
            baseline_summary={"status": "FAIL", "reason": f"Malformed current payload: {err}"},
            drift_checks=[chk],
        )

    # Resolve baseline historical reports with strict temporal safety and quality filtering
    loaded_baseline_reports: list[dict] = []
    baseline_dates_used: list[str] = []
    considered_dates: list[str] = []
    excluded_dates: list[str] = []
    exclusions: list[dict[str, Any]] = []

    if baseline_reports is not None:
        # Injected baseline reports (e.g., unit test fixtures)
        for idx, r in enumerate(baseline_reports):
            if len(loaded_baseline_reports) >= lookback_reports:
                break
            if not isinstance(r, dict):
                obs = DriftObservation(
                    check_name="drift_baseline_reports_injected",
                    baseline_period={"index": idx},
                    current_period=data_as_of,
                    baseline_value=None,
                    current_value=None,
                    absolute_difference=None,
                    threshold=None,
                    status="FAIL",
                    message=f"Injected baseline report at index {idx} is not a dict",
                )
                chk = DriftCheckResult(
                    check_name="drift_baseline_reports_injected",
                    status="FAIL",
                    observation=obs,
                )
                return DriftMonitoringResult(
                    overall_status="FAIL",
                    data_as_of=data_as_of,
                    baseline_summary={"status": "FAIL", "reason": "Invalid injected report"},
                    drift_checks=[chk],
                )

            r_date = r.get("data_as_of")
            if not r_date or not isinstance(r_date, str) or isinstance(r_date, bool):
                obs = DriftObservation(
                    check_name="drift_baseline_reports_injected",
                    baseline_period={"index": idx},
                    current_period=data_as_of,
                    baseline_value=None,
                    current_value=r_date,
                    absolute_difference=None,
                    threshold=None,
                    status="FAIL",
                    message=f"Injected baseline report at index {idx} missing valid YYYY-MM-DD string data_as_of",
                )
                chk = DriftCheckResult(
                    check_name="drift_baseline_reports_injected",
                    status="FAIL",
                    observation=obs,
                )
                return DriftMonitoringResult(
                    overall_status="FAIL",
                    data_as_of=data_as_of,
                    baseline_summary={
                        "status": "FAIL",
                        "reason": "Missing or invalid data_as_of string in injected report",
                    },
                    drift_checks=[chk],
                )

            if not is_canonical_yyyy_mm_dd(r_date):
                obs = DriftObservation(
                    check_name="drift_baseline_reports_injected",
                    baseline_period={"index": idx, "injected_date": r_date},
                    current_period=data_as_of,
                    baseline_value=None,
                    current_value=r_date,
                    absolute_difference=None,
                    threshold=None,
                    status="FAIL",
                    message=f"Injected baseline report at index {idx} has invalid canonical YYYY-MM-DD format: '{r_date}'",
                )
                chk = DriftCheckResult(
                    check_name="drift_baseline_reports_injected",
                    status="FAIL",
                    observation=obs,
                )
                return DriftMonitoringResult(
                    overall_status="FAIL",
                    data_as_of=data_as_of,
                    baseline_summary={
                        "status": "FAIL",
                        "reason": f"Invalid date format '{r_date}' in injected report",
                    },
                    drift_checks=[chk],
                )

            # Temporal safety check: baseline report date must be strictly < data_as_of
            if r_date >= data_as_of:
                obs = DriftObservation(
                    check_name="drift_temporal_safety",
                    baseline_period={"injected_date": r_date},
                    current_period=data_as_of,
                    baseline_value=r_date,
                    current_value=data_as_of,
                    absolute_difference=None,
                    threshold=None,
                    status="FAIL",
                    message=f"Temporal safety violation: baseline report date '{r_date}' is not strictly less than current evaluation date '{data_as_of}'",
                )
                chk = DriftCheckResult(
                    check_name="drift_temporal_safety", status="FAIL", observation=obs
                )
                return DriftMonitoringResult(
                    overall_status="FAIL",
                    data_as_of=data_as_of,
                    baseline_summary={"status": "FAIL", "reason": "Temporal safety violation"},
                    drift_checks=[chk],
                )

            considered_dates.append(r_date)

            try:
                b_metrics = extract_recommendation_metrics(
                    r, market_payload=r.get("market") if isinstance(r, dict) else None
                )
            except (ValueError, TypeError) as err:
                obs = DriftObservation(
                    check_name="drift_baseline_report_malformed",
                    baseline_period={"index": idx, "report_date": r_date},
                    current_period=data_as_of,
                    baseline_value=None,
                    current_value=None,
                    absolute_difference=None,
                    threshold=None,
                    status="FAIL",
                    message=f"Baseline historical report '{r_date}' metrics extraction failed: {err}",
                )
                chk = DriftCheckResult(
                    check_name="drift_baseline_report_malformed", status="FAIL", observation=obs
                )
                return DriftMonitoringResult(
                    overall_status="FAIL",
                    data_as_of=data_as_of,
                    baseline_summary={
                        "status": "FAIL",
                        "reason": f"Malformed baseline report {r_date}: {err}",
                    },
                    drift_checks=[chk],
                )

            if b_metrics["processed_ratio"] >= min_processed_ratio:
                baseline_dates_used.append(r_date)
                loaded_baseline_reports.append(r)
            else:
                excluded_dates.append(r_date)
                exclusions.append(
                    {
                        "date": r_date,
                        "reason": "processed_ratio_below_threshold",
                        "processed_ratio": b_metrics["processed_ratio"],
                        "min_processed_ratio": min_processed_ratio,
                    }
                )

        # Check for duplicate dates in injected baseline reports
        if len(considered_dates) != len(set(considered_dates)):
            obs = DriftObservation(
                check_name="drift_baseline_reports_duplicates",
                baseline_period={
                    "total_reports": len(considered_dates),
                    "unique_dates": len(set(considered_dates)),
                },
                current_period=data_as_of,
                baseline_value=len(considered_dates),
                current_value=len(set(considered_dates)),
                absolute_difference=len(considered_dates) - len(set(considered_dates)),
                threshold=0,
                status="FAIL",
                message="Injected baseline reports contain duplicate data_as_of dates",
            )
            chk = DriftCheckResult(
                check_name="drift_baseline_reports_duplicates",
                status="FAIL",
                observation=obs,
            )
            return DriftMonitoringResult(
                overall_status="FAIL",
                data_as_of=data_as_of,
                baseline_summary={
                    "status": "FAIL",
                    "reason": "Duplicate dates in injected baseline reports",
                },
                drift_checks=[chk],
            )

        # Check descending order in injected baseline reports
        if considered_dates != sorted(considered_dates, reverse=True):
            obs = DriftObservation(
                check_name="drift_baseline_reports_order",
                baseline_period={"dates_sample": considered_dates[:5]},
                current_period=data_as_of,
                baseline_value=None,
                current_value=None,
                absolute_difference=None,
                threshold=None,
                status="FAIL",
                message="Injected baseline reports dates are not in descending chronological order",
            )
            chk = DriftCheckResult(
                check_name="drift_baseline_reports_order",
                status="FAIL",
                observation=obs,
            )
            return DriftMonitoringResult(
                overall_status="FAIL",
                data_as_of=data_as_of,
                baseline_summary={
                    "status": "FAIL",
                    "reason": "Unsorted dates in injected baseline reports",
                },
                drift_checks=[chk],
            )
    else:
        # Load history index
        if history_index_data is None:
            index_path = os.path.join(g_dir, "history", "index.json")
            if not os.path.exists(index_path):
                obs = DriftObservation(
                    check_name="drift_history_index",
                    baseline_period={"status": "MISSING_INDEX", "path": index_path},
                    current_period=data_as_of,
                    baseline_value=None,
                    current_value=None,
                    absolute_difference=None,
                    threshold=None,
                    status="FAIL",
                    message=f"History index file missing at {index_path}; fail closed",
                )
                chk = DriftCheckResult(
                    check_name="drift_history_index", status="FAIL", observation=obs
                )
                return DriftMonitoringResult(
                    overall_status="FAIL",
                    data_as_of=data_as_of,
                    baseline_summary={"status": "FAIL", "reason": "Missing history index file"},
                    drift_checks=[chk],
                )

            try:
                with open(index_path, "r", encoding="utf-8") as f:
                    history_index_data = json.load(f)
            except Exception as err:  # noqa: BLE001
                obs = DriftObservation(
                    check_name="drift_history_index",
                    baseline_period={"path": index_path},
                    current_period=data_as_of,
                    baseline_value=None,
                    current_value=None,
                    absolute_difference=None,
                    threshold=None,
                    status="FAIL",
                    message=f"Failed to read or decode history index JSON: {err}",
                )
                chk = DriftCheckResult(
                    check_name="drift_history_index", status="FAIL", observation=obs
                )
                return DriftMonitoringResult(
                    overall_status="FAIL",
                    data_as_of=data_as_of,
                    baseline_summary={
                        "status": "FAIL",
                        "reason": f"Malformed history index JSON: {err}",
                    },
                    drift_checks=[chk],
                )

        if not history_index_data or not isinstance(history_index_data, dict):
            obs = DriftObservation(
                check_name="drift_history_index",
                baseline_period={"status": "INVALID_INDEX_TYPE"},
                current_period=data_as_of,
                baseline_value=None,
                current_value=type(history_index_data).__name__,
                absolute_difference=None,
                threshold=None,
                status="FAIL",
                message="History index data is missing or not a dict; fail closed",
            )
            chk = DriftCheckResult(check_name="drift_history_index", status="FAIL", observation=obs)
            return DriftMonitoringResult(
                overall_status="FAIL",
                data_as_of=data_as_of,
                baseline_summary={"status": "FAIL", "reason": "Invalid history index type"},
                drift_checks=[chk],
            )

        dates = history_index_data.get("dates")
        if not isinstance(dates, list):
            obs = DriftObservation(
                check_name="drift_history_index",
                baseline_period={"dates_type": type(dates).__name__},
                current_period=data_as_of,
                baseline_value=None,
                current_value=None,
                absolute_difference=None,
                threshold=None,
                status="FAIL",
                message="History index 'dates' field is not a list",
            )
            chk = DriftCheckResult(check_name="drift_history_index", status="FAIL", observation=obs)
            return DriftMonitoringResult(
                overall_status="FAIL",
                data_as_of=data_as_of,
                baseline_summary={"status": "FAIL", "reason": "Invalid dates field"},
                drift_checks=[chk],
            )

        # Validate date strings and canonical YYYY-MM-DD
        invalid_dates = [str(d) for d in dates if not is_canonical_yyyy_mm_dd(d)]

        if invalid_dates:
            obs = DriftObservation(
                check_name="drift_history_index_format",
                baseline_period={"invalid_dates": invalid_dates[:5]},
                current_period=data_as_of,
                baseline_value=None,
                current_value=None,
                absolute_difference=None,
                threshold=None,
                status="FAIL",
                message=f"History index contains invalid YYYY-MM-DD date entries: {', '.join(invalid_dates[:3])}",
            )
            chk = DriftCheckResult(
                check_name="drift_history_index_format", status="FAIL", observation=obs
            )
            return DriftMonitoringResult(
                overall_status="FAIL",
                data_as_of=data_as_of,
                baseline_summary={"status": "FAIL", "reason": "Invalid date strings in index"},
                drift_checks=[chk],
            )

        # Check for duplicate dates
        if len(dates) != len(set(dates)):
            obs = DriftObservation(
                check_name="drift_history_index_duplicates",
                baseline_period={"total_dates": len(dates), "unique": len(set(dates))},
                current_period=data_as_of,
                baseline_value=len(dates),
                current_value=len(set(dates)),
                absolute_difference=len(dates) - len(set(dates)),
                threshold=0,
                status="FAIL",
                message="History index contains duplicate date entries; fail closed on temporal corruption",
            )
            chk = DriftCheckResult(
                check_name="drift_history_index_duplicates", status="FAIL", observation=obs
            )
            return DriftMonitoringResult(
                overall_status="FAIL",
                data_as_of=data_as_of,
                baseline_summary={"status": "FAIL", "reason": "Duplicate dates in history index"},
                drift_checks=[chk],
            )

        # Check strict reverse chronological order (descending)
        if dates != sorted(dates, reverse=True):
            obs = DriftObservation(
                check_name="drift_history_index_order",
                baseline_period={"dates_sample": dates[:5]},
                current_period=data_as_of,
                baseline_value=None,
                current_value=None,
                absolute_difference=None,
                threshold=None,
                status="FAIL",
                message="History index dates are not in descending chronological order; fail closed on temporal structure violation",
            )
            chk = DriftCheckResult(
                check_name="drift_history_index_order", status="FAIL", observation=obs
            )
            return DriftMonitoringResult(
                overall_status="FAIL",
                data_as_of=data_as_of,
                baseline_summary={
                    "status": "FAIL",
                    "reason": "Unsorted history index dates",
                },
                drift_checks=[chk],
            )

        # Check temporal safety: if dates in physical index dataset contain future dates >= data_as_of out of chronological order
        # Specifically, check if any date >= data_as_of appears AFTER a baseline candidate date (< data_as_of)
        first_future_idx = next((i for i, d in enumerate(dates) if d >= data_as_of), None)
        first_past_idx = next((i for i, d in enumerate(dates) if d < data_as_of), None)
        if (
            first_future_idx is not None
            and first_past_idx is not None
            and first_future_idx > first_past_idx
        ):
            obs = DriftObservation(
                check_name="drift_temporal_safety",
                baseline_period={"future_idx": first_future_idx, "past_idx": first_past_idx},
                current_period=data_as_of,
                baseline_value=dates[first_future_idx],
                current_value=data_as_of,
                absolute_difference=None,
                threshold=None,
                status="FAIL",
                message=f"Temporal safety violation: future observation '{dates[first_future_idx]}' appears after past date '{dates[first_past_idx]}' in history index dataset",
            )
            chk = DriftCheckResult(
                check_name="drift_temporal_safety", status="FAIL", observation=obs
            )
            return DriftMonitoringResult(
                overall_status="FAIL",
                data_as_of=data_as_of,
                baseline_summary={
                    "status": "FAIL",
                    "reason": "Future observation in physical dataset before T",
                },
                drift_checks=[chk],
            )

        # Filter baseline candidates strictly < data_as_of
        baseline_candidate_dates = [d for d in dates if d < data_as_of]

        for d in baseline_candidate_dates:
            if len(loaded_baseline_reports) >= lookback_reports:
                break
            fpath = os.path.join(g_dir, "history", f"{d}.json")
            if not os.path.exists(fpath):
                obs = DriftObservation(
                    check_name="drift_history_artifact_missing",
                    baseline_period={"history_date": d, "file_path": fpath},
                    current_period=data_as_of,
                    baseline_value=d,
                    current_value=None,
                    absolute_difference=None,
                    threshold=None,
                    status="FAIL",
                    message=f"Baseline historical artifact file history/{d}.json is missing from disk; fail closed",
                )
                chk = DriftCheckResult(
                    check_name="drift_history_artifact_missing", status="FAIL", observation=obs
                )
                return DriftMonitoringResult(
                    overall_status="FAIL",
                    data_as_of=data_as_of,
                    baseline_summary={
                        "status": "FAIL",
                        "reason": f"Missing baseline artifact history/{d}.json",
                    },
                    drift_checks=[chk],
                )

            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    b_payload = json.load(f)
            except Exception as err:  # noqa: BLE001
                obs = DriftObservation(
                    check_name="drift_history_artifact_corrupted",
                    baseline_period={"history_date": d, "file_path": fpath},
                    current_period=data_as_of,
                    baseline_value=d,
                    current_value=None,
                    absolute_difference=None,
                    threshold=None,
                    status="FAIL",
                    message=f"Failed to read or decode baseline history artifact history/{d}.json: {err}",
                )
                chk = DriftCheckResult(
                    check_name="drift_history_artifact_corrupted",
                    status="FAIL",
                    observation=obs,
                )
                return DriftMonitoringResult(
                    overall_status="FAIL",
                    data_as_of=data_as_of,
                    baseline_summary={
                        "status": "FAIL",
                        "reason": f"Corrupted baseline artifact history/{d}.json",
                    },
                    drift_checks=[chk],
                )

            if not isinstance(b_payload, dict):
                obs = DriftObservation(
                    check_name="drift_history_artifact_corrupted",
                    baseline_period={"history_date": d, "file_path": fpath},
                    current_period=data_as_of,
                    baseline_value=d,
                    current_value=type(b_payload).__name__,
                    absolute_difference=None,
                    threshold=None,
                    status="FAIL",
                    message=f"Baseline history artifact history/{d}.json root is not a dict",
                )
                chk = DriftCheckResult(
                    check_name="drift_history_artifact_corrupted",
                    status="FAIL",
                    observation=obs,
                )
                return DriftMonitoringResult(
                    overall_status="FAIL",
                    data_as_of=data_as_of,
                    baseline_summary={
                        "status": "FAIL",
                        "reason": f"Non-dict root in history/{d}.json",
                    },
                    drift_checks=[chk],
                )

            b_date = b_payload.get("data_as_of")
            if not is_canonical_yyyy_mm_dd(b_date):
                obs = DriftObservation(
                    check_name="drift_history_artifact_format",
                    baseline_period={"history_date": d, "payload_date": b_date},
                    current_period=data_as_of,
                    baseline_value=d,
                    current_value=b_date,
                    absolute_difference=None,
                    threshold=None,
                    status="FAIL",
                    message=f"Baseline history artifact history/{d}.json payload data_as_of '{b_date}' is missing or not a canonical YYYY-MM-DD date string",
                )
                chk = DriftCheckResult(
                    check_name="drift_history_artifact_format",
                    status="FAIL",
                    observation=obs,
                )
                return DriftMonitoringResult(
                    overall_status="FAIL",
                    data_as_of=data_as_of,
                    baseline_summary={
                        "status": "FAIL",
                        "reason": f"Missing or non-canonical date in history/{d}.json",
                    },
                    drift_checks=[chk],
                )

            if b_date != d:
                obs = DriftObservation(
                    check_name="drift_history_artifact_mismatch",
                    baseline_period={"history_date": d, "payload_date": b_date},
                    current_period=data_as_of,
                    baseline_value=d,
                    current_value=b_date,
                    absolute_difference=None,
                    threshold=None,
                    status="FAIL",
                    message=f"Baseline history artifact history/{d}.json payload data_as_of '{b_date}' does not match index date '{d}'",
                )
                chk = DriftCheckResult(
                    check_name="drift_history_artifact_mismatch",
                    status="FAIL",
                    observation=obs,
                )
                return DriftMonitoringResult(
                    overall_status="FAIL",
                    data_as_of=data_as_of,
                    baseline_summary={
                        "status": "FAIL",
                        "reason": f"Artifact date mismatch in history/{d}.json",
                    },
                    drift_checks=[chk],
                )

            if b_date >= data_as_of:
                obs = DriftObservation(
                    check_name="drift_temporal_safety",
                    baseline_period={"history_date": d, "payload_date": b_date},
                    current_period=data_as_of,
                    baseline_value=b_date,
                    current_value=data_as_of,
                    absolute_difference=None,
                    threshold=None,
                    status="FAIL",
                    message=f"Temporal safety violation: baseline history artifact date '{b_date}' is not strictly less than current evaluation date '{data_as_of}'",
                )
                chk = DriftCheckResult(
                    check_name="drift_temporal_safety", status="FAIL", observation=obs
                )
                return DriftMonitoringResult(
                    overall_status="FAIL",
                    data_as_of=data_as_of,
                    baseline_summary={
                        "status": "FAIL",
                        "reason": "Temporal safety violation in history artifact",
                    },
                    drift_checks=[chk],
                )

            considered_dates.append(d)

            try:
                b_metrics = extract_recommendation_metrics(
                    b_payload,
                    market_payload=b_payload.get("market") if isinstance(b_payload, dict) else None,
                )
            except (ValueError, TypeError) as err:
                obs = DriftObservation(
                    check_name="drift_baseline_report_malformed",
                    baseline_period={"report_date": d},
                    current_period=data_as_of,
                    baseline_value=None,
                    current_value=None,
                    absolute_difference=None,
                    threshold=None,
                    status="FAIL",
                    message=f"Baseline historical report '{d}' metrics extraction failed: {err}",
                )
                chk = DriftCheckResult(
                    check_name="drift_baseline_report_malformed", status="FAIL", observation=obs
                )
                return DriftMonitoringResult(
                    overall_status="FAIL",
                    data_as_of=data_as_of,
                    baseline_summary={
                        "status": "FAIL",
                        "reason": f"Malformed baseline report {d}: {err}",
                    },
                    drift_checks=[chk],
                )

            if b_metrics["processed_ratio"] >= min_processed_ratio:
                loaded_baseline_reports.append(b_payload)
                baseline_dates_used.append(d)
            else:
                excluded_dates.append(d)
                exclusions.append(
                    {
                        "date": d,
                        "reason": "processed_ratio_below_threshold",
                        "processed_ratio": b_metrics["processed_ratio"],
                        "min_processed_ratio": min_processed_ratio,
                    }
                )

    num_baseline_reports = len(loaded_baseline_reports)

    # Validate baseline report contents before calculating aggregates
    for idx, b_p in enumerate(loaded_baseline_reports):
        b_issues = find_nan_or_inf(b_p, path=f"baseline_report[{idx}]")
        if b_issues:
            obs = DriftObservation(
                check_name="drift_baseline_numeric_sanity",
                baseline_period={"index": idx, "report_date": baseline_dates_used[idx]},
                current_period=data_as_of,
                baseline_value=None,
                current_value=b_issues[:5],
                absolute_difference=None,
                threshold=None,
                status="FAIL",
                message=f"Baseline historical report '{baseline_dates_used[idx]}' contains non-finite NaN/Inf values: {'; '.join(b_issues[:3])}",
            )
            chk = DriftCheckResult(
                check_name="drift_baseline_numeric_sanity", status="FAIL", observation=obs
            )
            return DriftMonitoringResult(
                overall_status="FAIL",
                data_as_of=data_as_of,
                baseline_summary={
                    "status": "FAIL",
                    "reason": f"Non-finite values in baseline report {baseline_dates_used[idx]}",
                },
                drift_checks=[chk],
            )

    # Check minimum baseline sufficiency
    if num_baseline_reports < min_baseline_reports:
        obs = DriftObservation(
            check_name="drift_baseline_sufficiency",
            baseline_period={
                "status": "INSUFFICIENT",
                "baseline_status": "INSUFFICIENT",
                "available_reports": num_baseline_reports,
                "required_reports": min_baseline_reports,
                "lookback_reports": lookback_reports,
                "min_baseline_reports": min_baseline_reports,
                "min_processed_ratio": min_processed_ratio,
                "min_processed_ratio_threshold": min_processed_ratio,
                "considered_reports_count": len(considered_dates),
                "excluded_reports_count": len(excluded_dates),
                "qualified_reports_count": num_baseline_reports,
                "considered_dates": considered_dates,
                "excluded_dates": excluded_dates,
                "qualified_dates": baseline_dates_used,
                "baseline_dates": baseline_dates_used,
                "exclusions": exclusions,
            },
            current_period=data_as_of,
            baseline_value=num_baseline_reports,
            current_value=min_baseline_reports,
            absolute_difference=min_baseline_reports - num_baseline_reports,
            threshold=min_baseline_reports,
            status="WARNING",
            message=(
                f"INSUFFICIENT baseline historical data: considered {len(considered_dates)} "
                f"historical reports < {data_as_of}, excluded {len(excluded_dates)} for insufficient "
                f"coverage (< {min_processed_ratio:.1%}), leaving {num_baseline_reports} qualified reports "
                f"(minimum required is {min_baseline_reports})"
            ),
        )
        chk = DriftCheckResult(
            check_name="drift_baseline_sufficiency", status="WARNING", observation=obs
        )
        return DriftMonitoringResult(
            overall_status="WARNING",
            data_as_of=data_as_of,
            baseline_summary={
                "status": "INSUFFICIENT",
                "baseline_status": "INSUFFICIENT",
                "report_count": num_baseline_reports,
                "available_reports": num_baseline_reports,
                "lookback_reports": lookback_reports,
                "min_baseline_reports": min_baseline_reports,
                "min_processed_ratio": min_processed_ratio,
                "min_processed_ratio_threshold": min_processed_ratio,
                "required_reports": min_baseline_reports,
                "considered_reports_count": len(considered_dates),
                "excluded_reports_count": len(excluded_dates),
                "qualified_reports_count": num_baseline_reports,
                "considered_dates": considered_dates,
                "excluded_dates": excluded_dates,
                "qualified_dates": baseline_dates_used,
                "baseline_dates": baseline_dates_used,
                "exclusions": exclusions,
            },
            drift_checks=[chk],
        )

    # Extract baseline metrics for all qualified baseline reports
    all_baseline_metrics = [
        extract_recommendation_metrics(
            b_p, market_payload=b_p.get("market") if isinstance(b_p, dict) else None
        )
        for b_p in loaded_baseline_reports
    ]

    # Compute baseline aggregated metric values using pooled recommendation observations
    # for recommendation metrics, and report/day-level mean for market metrics.
    pooled_total_scanned = sum(m["total_scanned"] for m in all_baseline_metrics)
    pooled_processed_count = sum(m["processed_count"] for m in all_baseline_metrics)

    baseline_processed_ratio = (
        round(pooled_processed_count / pooled_total_scanned, 6) if pooled_total_scanned > 0 else 0.0
    )

    # Market metrics remain report/day-level mean aggregation
    breadth_vals = [
        m["market_breadth_ratio"]
        for m in all_baseline_metrics
        if m["market_breadth_ratio"] is not None
    ]
    baseline_breadth_ratio = (
        round(sum(breadth_vals) / len(breadth_vals), 6) if breadth_vals else None
    )

    vn_vals = [
        m["vnindex_change_pct"] for m in all_baseline_metrics if m["vnindex_change_pct"] is not None
    ]
    baseline_vnindex_change_pct = round(sum(vn_vals) / len(vn_vals), 4) if vn_vals else None

    # Aggregated action proportions from pooled counts
    pooled_action_counts = {
        act: sum(m["action_counts"][act] for m in all_baseline_metrics)
        for act in ["BUY", "WATCH", "HOLD", "SELL", "AVOID"]
    }
    if pooled_total_scanned > 0:
        baseline_action_props = {
            act: round(cnt / pooled_total_scanned, 6) for act, cnt in pooled_action_counts.items()
        }
    else:
        baseline_action_props = {act: 0.0 for act in pooled_action_counts}

    # Aggregated confidence bucket proportions from pooled counts
    pooled_bucket_counts = {
        b: sum(m["confidence_bucket_counts"][b] for m in all_baseline_metrics)
        for b in CANONICAL_CONFIDENCE_BUCKETS
    }
    pooled_valid_conf_count = sum(pooled_bucket_counts.values())
    if pooled_valid_conf_count > 0:
        baseline_conf_bucket_props = {
            b: round(cnt / pooled_valid_conf_count, 6) for b, cnt in pooled_bucket_counts.items()
        }
    else:
        baseline_conf_bucket_props = {b: 0.0 for b in CANONICAL_CONFIDENCE_BUCKETS}

    # Pooled numeric means across all individual recommendations in baseline reports
    all_sig_scores = []
    all_risk_scores = []
    all_conf_vals = []

    for b_p in loaded_baseline_reports:
        for r in b_p.get("recommendations", []):
            if isinstance(r, dict):
                ss = r.get("signal_score")
                if ss is not None and not isinstance(ss, bool) and isinstance(ss, (int, float)):
                    f_ss = float(ss)
                    if not (math.isnan(f_ss) or math.isinf(f_ss)):
                        all_sig_scores.append(f_ss)

                rs = r.get("risk_adjusted_score")
                if rs is not None and not isinstance(rs, bool) and isinstance(rs, (int, float)):
                    f_rs = float(rs)
                    if not (math.isnan(f_rs) or math.isinf(f_rs)):
                        all_risk_scores.append(f_rs)

                conf = r.get("confidence")
                if (
                    conf is not None
                    and not isinstance(conf, bool)
                    and isinstance(conf, (int, float))
                ):
                    f_conf = float(conf)
                    if not (math.isnan(f_conf) or math.isinf(f_conf)) and 0.0 <= f_conf <= 1.0:
                        all_conf_vals.append(f_conf)

    baseline_signal_score_mean = (
        round(sum(all_sig_scores) / len(all_sig_scores), 4) if all_sig_scores else None
    )
    baseline_risk_score_mean = (
        round(sum(all_risk_scores) / len(all_risk_scores), 4) if all_risk_scores else None
    )
    baseline_confidence_mean = (
        round(sum(all_conf_vals) / len(all_conf_vals), 4) if all_conf_vals else None
    )

    baseline_period_info = {
        "status": "SUFFICIENT",
        "baseline_status": "SUFFICIENT",
        "report_count": num_baseline_reports,
        "lookback_reports": lookback_reports,
        "min_baseline_reports": min_baseline_reports,
        "min_processed_ratio": min_processed_ratio,
        "min_processed_ratio_threshold": min_processed_ratio,
        "considered_reports_count": len(considered_dates),
        "excluded_reports_count": len(excluded_dates),
        "qualified_reports_count": num_baseline_reports,
        "start_date": baseline_dates_used[-1] if baseline_dates_used else None,
        "end_date": baseline_dates_used[0] if baseline_dates_used else None,
        "considered_dates": considered_dates,
        "excluded_dates": excluded_dates,
        "qualified_dates": baseline_dates_used,
        "baseline_dates": baseline_dates_used,
        "exclusions": exclusions,
    }

    drift_checks: list[DriftCheckResult] = []

    # 1. Processed ratio drift
    proc_warn, proc_fail = _get_thresh(
        "DRIFT_THRESHOLD_PROCESSED_RATIO", DRIFT_THRESHOLD_PROCESSED_RATIO
    )
    curr_proc = current_metrics["processed_ratio"]
    proc_diff = round(abs(curr_proc - baseline_processed_ratio), 6)
    if proc_diff > proc_fail:
        proc_status = "FAIL"
    elif proc_diff > proc_warn:
        proc_status = "WARNING"
    else:
        proc_status = "PASS"

    proc_obs = DriftObservation(
        check_name="drift_processed_ratio",
        baseline_period=baseline_period_info,
        current_period=data_as_of,
        baseline_value=baseline_processed_ratio,
        current_value=curr_proc,
        absolute_difference=proc_diff,
        threshold={"warning": proc_warn, "fail": proc_fail},
        status=proc_status,
        message=f"Processed ratio diff is {proc_diff:.4f} (current={curr_proc:.4f}, baseline={baseline_processed_ratio:.4f})",
    )
    drift_checks.append(
        DriftCheckResult(
            check_name="drift_processed_ratio", status=proc_status, observation=proc_obs
        )
    )

    # 2. Market breadth drift
    b_warn, b_fail = _get_thresh("DRIFT_THRESHOLD_BREADTH_RATIO", DRIFT_THRESHOLD_BREADTH_RATIO)
    curr_breadth = current_metrics["market_breadth_ratio"]
    if curr_breadth is not None and baseline_breadth_ratio is not None:
        breadth_diff = round(abs(curr_breadth - baseline_breadth_ratio), 6)
        if breadth_diff > b_fail:
            b_status = "FAIL"
        elif breadth_diff > b_warn:
            b_status = "WARNING"
        else:
            b_status = "PASS"

        b_msg = f"Market breadth ratio diff is {breadth_diff:.4f} (current={curr_breadth:.4f}, baseline={baseline_breadth_ratio:.4f})"
    else:
        breadth_diff = None
        b_status = "WARNING"
        b_msg = "Market breadth ratio is missing in current payload or baseline"

    b_obs = DriftObservation(
        check_name="drift_market_breadth",
        baseline_period=baseline_period_info,
        current_period=data_as_of,
        baseline_value=baseline_breadth_ratio,
        current_value=curr_breadth,
        absolute_difference=breadth_diff,
        threshold={"warning": b_warn, "fail": b_fail},
        status=b_status,
        message=b_msg,
    )
    drift_checks.append(
        DriftCheckResult(check_name="drift_market_breadth", status=b_status, observation=b_obs)
    )

    # 3. VNINDEX change pct drift
    v_warn, v_fail = _get_thresh(
        "DRIFT_THRESHOLD_VNINDEX_CHANGE_PCT", DRIFT_THRESHOLD_VNINDEX_CHANGE_PCT
    )
    curr_vn = current_metrics["vnindex_change_pct"]
    if curr_vn is not None and baseline_vnindex_change_pct is not None:
        vn_diff = round(abs(curr_vn - baseline_vnindex_change_pct), 4)
        if vn_diff > v_fail:
            v_status = "FAIL"
        elif vn_diff > v_warn:
            v_status = "WARNING"
        else:
            v_status = "PASS"

        v_msg = f"VNINDEX change pct diff is {vn_diff:.4f}% (current={curr_vn:.4f}%, baseline={baseline_vnindex_change_pct:.4f}%)"
    else:
        vn_diff = None
        v_status = "WARNING"
        v_msg = "VNINDEX change pct is missing in current payload or baseline"

    v_obs = DriftObservation(
        check_name="drift_vnindex_change_pct",
        baseline_period=baseline_period_info,
        current_period=data_as_of,
        baseline_value=baseline_vnindex_change_pct,
        current_value=curr_vn,
        absolute_difference=vn_diff,
        threshold={"warning": v_warn, "fail": v_fail},
        status=v_status,
        message=v_msg,
    )
    drift_checks.append(
        DriftCheckResult(check_name="drift_vnindex_change_pct", status=v_status, observation=v_obs)
    )

    # 4. Action distribution drift
    a_warn, a_fail = _get_thresh(
        "DRIFT_THRESHOLD_ACTION_DISTRIBUTION", DRIFT_THRESHOLD_ACTION_DISTRIBUTION
    )
    a_tolerance = _get_thresh(
        "DRIFT_BOUNDARY_TOLERANCE_ACTION_DISTRIBUTION",
        DRIFT_BOUNDARY_TOLERANCE_ACTION_DISTRIBUTION,
    )
    if (
        isinstance(a_tolerance, bool)
        or not isinstance(a_tolerance, (int, float))
        or math.isnan(a_tolerance)
        or math.isinf(a_tolerance)
        or a_tolerance < 0
    ):
        raise ValueError(f"DRIFT_BOUNDARY_TOLERANCE_ACTION_DISTRIBUTION is invalid: {a_tolerance}")

    curr_action_props = current_metrics["action_proportions"]
    curr_regime = current_metrics.get("market_regime")
    action_diffs = {
        act: round(abs(curr_action_props[act] - baseline_action_props[act]), 6)
        for act in ["BUY", "WATCH", "HOLD", "SELL", "AVOID"]
    }
    max_action_diff = max(action_diffs.values())

    # Regime-driven check: When Market Regime == "PANIC", classify_action() sets all valid actions to "AVOID"
    is_panic_regime_shift = curr_regime == "PANIC" and curr_action_props.get("AVOID", 0.0) == 1.0

    if is_panic_regime_shift:
        a_status = "PASS"
        a_msg = (
            f"Action distribution shift (max shift={max_action_diff:.4f}) is valid and expected "
            f"due to extreme market regime PANIC (100% AVOID per quantitative signal rules)"
        )
    elif max_action_diff > a_fail + a_tolerance:
        a_status = "FAIL"
        a_msg = f"Action distribution max proportion shift is {max_action_diff:.4f} across actions"
    elif max_action_diff > a_warn:
        a_status = "WARNING"
        a_msg = f"Action distribution max proportion shift is {max_action_diff:.4f} across actions"
    else:
        a_status = "PASS"
        a_msg = f"Action distribution max proportion shift is {max_action_diff:.4f} across actions"

    a_obs = DriftObservation(
        check_name="drift_action_distribution",
        baseline_period=baseline_period_info,
        current_period=data_as_of,
        baseline_value=baseline_action_props,
        current_value=curr_action_props,
        absolute_difference={
            "max_difference": max_action_diff,
            "per_action": action_diffs,
        },
        threshold={"warning": a_warn, "fail": a_fail},
        status=a_status,
        message=a_msg,
    )
    drift_checks.append(
        DriftCheckResult(check_name="drift_action_distribution", status=a_status, observation=a_obs)
    )

    # 5. Confidence bucket distribution drift
    c_warn, c_fail = _get_thresh(
        "DRIFT_THRESHOLD_CONFIDENCE_DISTRIBUTION", DRIFT_THRESHOLD_CONFIDENCE_DISTRIBUTION
    )
    curr_conf_bucket_props = current_metrics["confidence_bucket_proportions"]
    conf_bucket_diffs = {
        b: round(abs(curr_conf_bucket_props[b] - baseline_conf_bucket_props[b]), 6)
        for b in CANONICAL_CONFIDENCE_BUCKETS
    }
    max_conf_bucket_diff = max(conf_bucket_diffs.values())
    if max_conf_bucket_diff > c_fail:
        c_status = "FAIL"
    elif max_conf_bucket_diff > c_warn:
        c_status = "WARNING"
    else:
        c_status = "PASS"

    c_obs = DriftObservation(
        check_name="drift_confidence_distribution",
        baseline_period=baseline_period_info,
        current_period=data_as_of,
        baseline_value=baseline_conf_bucket_props,
        current_value=curr_conf_bucket_props,
        absolute_difference={
            "max_difference": max_conf_bucket_diff,
            "per_bucket": conf_bucket_diffs,
        },
        threshold={"warning": c_warn, "fail": c_fail},
        status=c_status,
        message=f"Confidence bucket distribution max proportion shift is {max_conf_bucket_diff:.4f}",
    )
    drift_checks.append(
        DriftCheckResult(
            check_name="drift_confidence_distribution", status=c_status, observation=c_obs
        )
    )

    # 6. Signal score mean drift
    s_warn, s_fail = _get_thresh(
        "DRIFT_THRESHOLD_SIGNAL_SCORE_MEAN", DRIFT_THRESHOLD_SIGNAL_SCORE_MEAN
    )
    curr_sig_mean = current_metrics["signal_score_mean"]
    if curr_sig_mean is not None and baseline_signal_score_mean is not None:
        sig_diff = round(abs(curr_sig_mean - baseline_signal_score_mean), 4)
        if sig_diff > s_fail:
            s_status = "FAIL"
        elif sig_diff > s_warn:
            s_status = "WARNING"
        else:
            s_status = "PASS"

        s_msg = f"Signal score mean diff is {sig_diff:.4f} (current={curr_sig_mean:.4f}, baseline={baseline_signal_score_mean:.4f})"
    else:
        sig_diff = None
        s_status = "WARNING"
        s_msg = "Signal score mean is missing in current payload or baseline"

    s_obs = DriftObservation(
        check_name="drift_signal_score",
        baseline_period=baseline_period_info,
        current_period=data_as_of,
        baseline_value=baseline_signal_score_mean,
        current_value=curr_sig_mean,
        absolute_difference=sig_diff,
        threshold={"warning": s_warn, "fail": s_fail},
        status=s_status,
        message=s_msg,
    )
    drift_checks.append(
        DriftCheckResult(check_name="drift_signal_score", status=s_status, observation=s_obs)
    )

    # 7. Risk-adjusted score mean drift
    r_warn, r_fail = _get_thresh(
        "DRIFT_THRESHOLD_RISK_ADJUSTED_SCORE_MEAN", DRIFT_THRESHOLD_RISK_ADJUSTED_SCORE_MEAN
    )
    curr_risk_mean = current_metrics["risk_adjusted_score_mean"]
    if curr_risk_mean is not None and baseline_risk_score_mean is not None:
        risk_diff = round(abs(curr_risk_mean - baseline_risk_score_mean), 4)
        if risk_diff > r_fail:
            r_status = "FAIL"
        elif risk_diff > r_warn:
            r_status = "WARNING"
        else:
            r_status = "PASS"

        r_msg = f"Risk-adjusted score mean diff is {risk_diff:.4f} (current={curr_risk_mean:.4f}, baseline={baseline_risk_score_mean:.4f})"
    else:
        risk_diff = None
        r_status = "WARNING"
        r_msg = "Risk-adjusted score mean is missing in current payload or baseline"

    r_obs = DriftObservation(
        check_name="drift_risk_adjusted_score",
        baseline_period=baseline_period_info,
        current_period=data_as_of,
        baseline_value=baseline_risk_score_mean,
        current_value=curr_risk_mean,
        absolute_difference=risk_diff,
        threshold={"warning": r_warn, "fail": r_fail},
        status=r_status,
        message=r_msg,
    )
    drift_checks.append(
        DriftCheckResult(check_name="drift_risk_adjusted_score", status=r_status, observation=r_obs)
    )

    # 8. Confidence mean drift
    cm_warn, cm_fail = _get_thresh(
        "DRIFT_THRESHOLD_CONFIDENCE_MEAN", DRIFT_THRESHOLD_CONFIDENCE_MEAN
    )
    curr_conf_mean = current_metrics["confidence_mean"]
    if curr_conf_mean is not None and baseline_confidence_mean is not None:
        conf_mean_diff = round(abs(curr_conf_mean - baseline_confidence_mean), 4)
        if conf_mean_diff > cm_fail:
            cm_status = "FAIL"
        elif conf_mean_diff > cm_warn:
            cm_status = "WARNING"
        else:
            cm_status = "PASS"

        cm_msg = f"Confidence mean diff is {conf_mean_diff:.4f} (current={curr_conf_mean:.4f}, baseline={baseline_confidence_mean:.4f})"
    else:
        conf_mean_diff = None
        cm_status = "WARNING"
        cm_msg = "Confidence mean is missing in current payload or baseline"

    cm_obs = DriftObservation(
        check_name="drift_confidence_mean",
        baseline_period=baseline_period_info,
        current_period=data_as_of,
        baseline_value=baseline_confidence_mean,
        current_value=curr_conf_mean,
        absolute_difference=conf_mean_diff,
        threshold={"warning": cm_warn, "fail": cm_fail},
        status=cm_status,
        message=cm_msg,
    )
    drift_checks.append(
        DriftCheckResult(check_name="drift_confidence_mean", status=cm_status, observation=cm_obs)
    )

    # Determine overall drift status
    check_statuses = [chk.status for chk in drift_checks]
    if "FAIL" in check_statuses:
        overall_status = "FAIL"
    elif "WARNING" in check_statuses:
        overall_status = "WARNING"
    else:
        overall_status = "PASS"

    baseline_summary_dict = {
        "status": "SUFFICIENT",
        "baseline_status": "SUFFICIENT",
        "report_count": num_baseline_reports,
        "lookback_reports": lookback_reports,
        "min_baseline_reports": min_baseline_reports,
        "min_processed_ratio": min_processed_ratio,
        "min_processed_ratio_threshold": min_processed_ratio,
        "considered_reports_count": len(considered_dates),
        "excluded_reports_count": len(excluded_dates),
        "qualified_reports_count": num_baseline_reports,
        "considered_dates": considered_dates,
        "excluded_dates": excluded_dates,
        "qualified_dates": baseline_dates_used,
        "baseline_dates": baseline_dates_used,
        "exclusions": exclusions,
        "baseline_period": baseline_period_info,
        "baseline_metrics": {
            "processed_ratio": baseline_processed_ratio,
            "market_breadth_ratio": baseline_breadth_ratio,
            "vnindex_change_pct": baseline_vnindex_change_pct,
            "signal_score_mean": baseline_signal_score_mean,
            "risk_adjusted_score_mean": baseline_risk_score_mean,
            "confidence_mean": baseline_confidence_mean,
            "action_proportions": baseline_action_props,
            "confidence_bucket_proportions": baseline_conf_bucket_props,
        },
    }

    return DriftMonitoringResult(
        overall_status=overall_status,
        data_as_of=data_as_of,
        baseline_summary=baseline_summary_dict,
        drift_checks=drift_checks,
    )


__all__ = ["evaluate_data_and_model_drift"]
