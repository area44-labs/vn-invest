"""Production Monitoring Module for VN Invest v2.

Provides deterministic, fail-closed operational monitoring for the production data-generation
and signal pipeline. Monitors data availability, freshness, processing counts, artifact integrity,
schema validation, numeric sanity (NaN/Inf safety), market regime status, and history index integrity.

This module provides operational and data-pipeline monitoring ONLY.
It does NOT establish model predictive validity, profitability, calibration, or statistical significance.
"""

import json
import logging
import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import jsonschema

from scripts.lib.config import SIGNAL_MODEL_VERSION, VALID_MARKET_REGIMES
from scripts.lib.vietnam_market import validate_ohlcv_data

logger = logging.getLogger(__name__)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_GENERATED_DIR = os.path.join(ROOT_DIR, "generated")
DEFAULT_SCHEMA_PATH = os.path.join(ROOT_DIR, "schemas", "recommendations.schema.json")

VALID_CHECK_STATUSES = {"PASS", "WARNING", "FAIL"}


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


def _sanitize_value_for_json(val: Any) -> Any:
    """Recursively sanitize Python objects for deterministic JSON serialization.

    Replaces float('nan') and float('inf') with string representations 'NaN' / 'Inf'
    so serialization does not break or produce invalid JSON.
    """
    if isinstance(val, float):
        if math.isnan(val):
            return "NaN"
        if math.isinf(val):
            return "Inf" if val > 0 else "-Inf"
        return val
    if isinstance(val, dict):
        return {k: _sanitize_value_for_json(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_sanitize_value_for_json(item) for item in val]
    if isinstance(val, tuple):
        return [_sanitize_value_for_json(item) for item in val]
    return val


def find_nan_or_inf(obj: Any, path: str = "") -> list[str]:
    """Recursively locate any NaN or Inf floating point values in nested data."""
    issues = []
    if isinstance(obj, float):
        if math.isnan(obj):
            issues.append(f"NaN at {path or 'root'}")
        elif math.isinf(obj):
            issues.append(f"Inf at {path or 'root'}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            issues.extend(find_nan_or_inf(v, f"{path}.{k}" if path else str(k)))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            issues.extend(find_nan_or_inf(item, f"{path}[{idx}]"))
    return issues


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


def check_required_artifacts(generated_dir: str, data_as_of: str | None = None) -> CheckResult:
    """Verify presence and accessibility of required generated JSON artifacts."""
    required_files = [
        os.path.join(generated_dir, "recommendations.json"),
        os.path.join(generated_dir, "market.json"),
        os.path.join(generated_dir, "history", "index.json"),
    ]
    if data_as_of:
        required_files.append(os.path.join(generated_dir, "history", f"{data_as_of}.json"))

    missing = []
    unreadable = []
    for fpath in required_files:
        if not os.path.exists(fpath):
            missing.append(os.path.basename(fpath))
        else:
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    unreadable.append(f"{os.path.basename(fpath)} (root is not object)")
            except Exception as e:  # noqa: BLE001
                unreadable.append(f"{os.path.basename(fpath)} ({e})")

    if missing or unreadable:
        msgs = []
        if missing:
            msgs.append(f"Missing files: {', '.join(missing)}")
        if unreadable:
            msgs.append(f"Unreadable files: {', '.join(unreadable)}")
        return CheckResult(
            check_name="artifact_existence",
            status="FAIL",
            measured_value={"missing": missing, "unreadable": unreadable},
            expected_condition="All required generated JSON artifacts exist and are valid JSON",
            message="; ".join(msgs),
        )

    return CheckResult(
        check_name="artifact_existence",
        status="PASS",
        measured_value={"required_count": len(required_files), "found_count": len(required_files)},
        expected_condition="All required generated JSON artifacts exist and are valid JSON",
        message=f"All {len(required_files)} required artifacts exist and are readable",
    )


def check_schema_validation(
    recommendations_payload: dict, schema_path: str = DEFAULT_SCHEMA_PATH
) -> CheckResult:
    """Validate recommendations payload against canonical JSON schema."""
    if not os.path.exists(schema_path):
        return CheckResult(
            check_name="schema_validation",
            status="FAIL",
            measured_value={"schema_path": schema_path},
            expected_condition=f"Schema file exists at {schema_path}",
            message=f"JSON Schema file not found at {schema_path}",
        )

    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
        jsonschema.validate(instance=recommendations_payload, schema=schema)
        return CheckResult(
            check_name="schema_validation",
            status="PASS",
            measured_value={"schema_version": recommendations_payload.get("schema_version")},
            expected_condition="Payload matches recommendations.schema.json",
            message="Recommendations payload passed JSON schema validation",
        )
    except jsonschema.ValidationError as err:
        return CheckResult(
            check_name="schema_validation",
            status="FAIL",
            measured_value={"error_path": list(err.absolute_path), "failed_keyword": err.validator},
            expected_condition="Payload matches recommendations.schema.json",
            message=f"Schema validation failed at path {list(err.absolute_path)}: {err.message}",
        )
    except Exception as err:  # noqa: BLE001
        return CheckResult(
            check_name="schema_validation",
            status="FAIL",
            measured_value={"error": str(err)},
            expected_condition="Payload matches recommendations.schema.json",
            message=f"Schema validation error: {err}",
        )


def check_data_freshness(data_as_of: str | None, reference_date: str | None = None) -> CheckResult:
    """Check data freshness / latest available date against explicit reference date.

    Fail-closed semantics:
    - Missing data_as_of when expected -> FAIL
    - Malformed date string -> FAIL
    - Future data_as_of relative to reference_date -> FAIL (anti-lookahead protection)
    - Staleness > 14 days -> FAIL
    - Staleness > 3 days -> WARNING
    - Staleness <= 3 days -> PASS
    """
    if not data_as_of:
        return CheckResult(
            check_name="data_freshness",
            status="FAIL",
            measured_value={"data_as_of": None},
            expected_condition="Valid YYYY-MM-DD date string for data_as_of",
            message="data_as_of is missing or None in production payload",
        )

    try:
        data_dt = datetime.strptime(data_as_of, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return CheckResult(
            check_name="data_freshness",
            status="FAIL",
            measured_value={"data_as_of": data_as_of},
            expected_condition="Valid YYYY-MM-DD date string",
            message=f"data_as_of '{data_as_of}' is not a valid YYYY-MM-DD date",
        )

    if reference_date:
        try:
            ref_dt = datetime.strptime(reference_date, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            return CheckResult(
                check_name="data_freshness",
                status="FAIL",
                measured_value={"reference_date": reference_date},
                expected_condition="Valid YYYY-MM-DD reference_date string",
                message=f"reference_date '{reference_date}' is not a valid YYYY-MM-DD date",
            )
    else:
        ref_dt = datetime.now(UTC)

    diff_days = (ref_dt.date() - data_dt.date()).days

    if diff_days < 0:
        return CheckResult(
            check_name="data_freshness",
            status="FAIL",
            measured_value={
                "data_as_of": data_as_of,
                "reference_date": ref_dt.strftime("%Y-%m-%d"),
                "future_days": -diff_days,
            },
            expected_condition="data_as_of <= reference_date",
            message=f"data_as_of ({data_as_of}) is in the future relative to reference_date ({ref_dt.strftime('%Y-%m-%d')})",
        )

    if diff_days > 14:
        return CheckResult(
            check_name="data_freshness",
            status="FAIL",
            measured_value={"data_as_of": data_as_of, "staleness_days": diff_days},
            expected_condition="staleness_days <= 14",
            message=f"Data is critically stale ({diff_days} days old relative to reference date)",
        )

    if diff_days > 3:
        return CheckResult(
            check_name="data_freshness",
            status="WARNING",
            measured_value={"data_as_of": data_as_of, "staleness_days": diff_days},
            expected_condition="staleness_days <= 3",
            message=f"Data is slightly stale ({diff_days} days old relative to reference date)",
        )

    return CheckResult(
        check_name="data_freshness",
        status="PASS",
        measured_value={"data_as_of": data_as_of, "staleness_days": diff_days},
        expected_condition="staleness_days <= 3",
        message=f"Data is fresh ({diff_days} days old as of {data_as_of})",
    )


def check_numeric_sanity(payload: dict) -> CheckResult:
    """Scan recommendations payload for NaN/Inf float values or out-of-bounds scores."""
    nan_inf_issues = find_nan_or_inf(payload)
    if nan_inf_issues:
        return CheckResult(
            check_name="numeric_sanity",
            status="FAIL",
            measured_value={"nan_inf_issues": nan_inf_issues[:10]},
            expected_condition="No NaN or Inf float values anywhere in payload",
            message=f"Found {len(nan_inf_issues)} NaN/Inf values: {'; '.join(nan_inf_issues[:3])}",
        )

    recs = payload.get("recommendations", [])
    out_of_bounds = []
    for r in recs:
        sym = r.get("symbol", "UNKNOWN")
        act = r.get("action")
        sig_score = r.get("signal_score")
        risk_adj = r.get("risk_adjusted_score")
        conf = r.get("confidence")

        if act != "AVOID":
            if sig_score is not None and not (0.0 <= sig_score <= 100.0):
                out_of_bounds.append(f"{sym}.signal_score={sig_score}")
            if risk_adj is not None and not (0.0 <= risk_adj <= 100.0):
                out_of_bounds.append(f"{sym}.risk_adjusted_score={risk_adj}")
            if conf is not None and not (0.0 <= conf <= 1.0):
                out_of_bounds.append(f"{sym}.confidence={conf}")

    if out_of_bounds:
        return CheckResult(
            check_name="numeric_sanity",
            status="FAIL",
            measured_value={"out_of_bounds": out_of_bounds},
            expected_condition="All scores strictly within allowed bounds [0..100] or [0..1]",
            message=f"Out-of-bounds score values detected: {'; '.join(out_of_bounds[:3])}",
        )

    return CheckResult(
        check_name="numeric_sanity",
        status="PASS",
        measured_value={"scanned_recommendations": len(recs)},
        expected_condition="No NaN/Inf values and scores strictly within allowed numeric bounds",
        message="All numeric values in recommendations payload are valid and within bounds",
    )


def check_symbol_processing_counts(payload: dict) -> CheckResult:
    """Verify symbol processing counts, summary invariants, and coverage ratios.

    Distinguishes:
    - Genuine pipeline failure: sum mismatch, 0 total scanned, or < 50% processed ratio.
    - Expected insufficient-data condition: individual stock with INSUFFICIENT data_quality / AVOID action, processed ratio >= 80%.
    - Warning condition: processed ratio between 50% and 80%.
    """
    recs = payload.get("recommendations", [])
    summary = payload.get("summary", {})

    total_scanned = summary.get("total_scanned", len(recs))
    buy_cnt = summary.get("buy_count", 0)
    watch_cnt = summary.get("watch_count", 0)
    hold_cnt = summary.get("hold_count", 0)
    sell_cnt = summary.get("sell_count", 0)
    avoid_cnt = summary.get("avoid_count", 0)

    sum_actions = buy_cnt + watch_cnt + hold_cnt + sell_cnt + avoid_cnt

    if total_scanned == 0 or len(recs) == 0:
        return CheckResult(
            check_name="symbol_processing_counts",
            status="FAIL",
            measured_value={"total_scanned": total_scanned, "len_recommendations": len(recs)},
            expected_condition="total_scanned > 0 and len(recommendations) > 0",
            message="Zero symbols were processed in recommendations payload",
        )

    if total_scanned != len(recs) or sum_actions != total_scanned:
        return CheckResult(
            check_name="symbol_processing_counts",
            status="FAIL",
            measured_value={
                "total_scanned": total_scanned,
                "len_recs": len(recs),
                "sum_actions": sum_actions,
            },
            expected_condition="summary counts sum to total_scanned and match recommendations length",
            message=f"Summary counts mismatch: total_scanned={total_scanned}, len_recs={len(recs)}, sum_actions={sum_actions}",
        )

    processed_count = sum(1 for r in recs if r.get("data_quality") in ("SUFFICIENT", "PARTIAL"))
    insufficient_count = sum(
        1 for r in recs if r.get("data_quality") == "INSUFFICIENT" or r.get("action") == "AVOID"
    )

    processed_ratio = processed_count / total_scanned if total_scanned > 0 else 0.0

    metrics_detail = {
        "total_scanned": total_scanned,
        "processed_count": processed_count,
        "insufficient_count": insufficient_count,
        "processed_ratio": round(processed_ratio, 4),
        "actions": {
            "BUY": buy_cnt,
            "WATCH": watch_cnt,
            "HOLD": hold_cnt,
            "SELL": sell_cnt,
            "AVOID": avoid_cnt,
        },
    }

    if processed_ratio < 0.50:
        return CheckResult(
            check_name="symbol_processing_counts",
            status="FAIL",
            measured_value=metrics_detail,
            expected_condition="processed_ratio >= 0.50",
            message=f"Critical coverage loss: only {processed_count}/{total_scanned} ({processed_ratio:.1%}) symbols successfully processed",
        )

    if processed_ratio < 0.80:
        return CheckResult(
            check_name="symbol_processing_counts",
            status="WARNING",
            measured_value=metrics_detail,
            expected_condition="processed_ratio >= 0.80",
            message=f"Moderate symbol processing warnings: {insufficient_count}/{total_scanned} symbols skipped or had insufficient data",
        )

    return CheckResult(
        check_name="symbol_processing_counts",
        status="PASS",
        measured_value=metrics_detail,
        expected_condition="processed_ratio >= 0.80",
        message=f"Successfully processed {processed_count}/{total_scanned} ({processed_ratio:.1%}) candidate universe symbols",
    )


def check_market_regime_status(market_payload: dict) -> CheckResult:
    """Validate market regime object, validity, confidence, and required metrics."""
    if not isinstance(market_payload, dict):
        return CheckResult(
            check_name="market_regime_status",
            status="FAIL",
            measured_value={"type": type(market_payload).__name__},
            expected_condition="market object is a dict",
            message="Market regime payload is not an object",
        )

    if "market" in market_payload and isinstance(market_payload["market"], dict):
        market_payload = market_payload["market"]

    regime = market_payload.get("regime")
    conf = market_payload.get("confidence")
    metrics = market_payload.get("metrics")

    if regime not in VALID_MARKET_REGIMES:
        return CheckResult(
            check_name="market_regime_status",
            status="FAIL",
            measured_value={"regime": regime},
            expected_condition=f"regime in {sorted(VALID_MARKET_REGIMES)}",
            message=f"Invalid market regime '{regime}'",
        )

    if conf is not None and not (0.0 <= conf <= 1.0):
        return CheckResult(
            check_name="market_regime_status",
            status="FAIL",
            measured_value={"confidence": conf},
            expected_condition="0.0 <= confidence <= 1.0",
            message=f"Market regime confidence out of bounds: {conf}",
        )

    if not isinstance(metrics, dict):
        return CheckResult(
            check_name="market_regime_status",
            status="FAIL",
            measured_value={"metrics": metrics},
            expected_condition="metrics is a dict",
            message="Market regime metrics object is missing or invalid",
        )

    vn_val = metrics.get("vnindex_value")
    vn_pct = metrics.get("vnindex_change_pct")
    breadth = metrics.get("market_breadth_ratio")

    if vn_val is None or vn_pct is None:
        return CheckResult(
            check_name="market_regime_status",
            status="FAIL",
            measured_value=metrics,
            expected_condition="vnindex_value and vnindex_change_pct present in metrics",
            message="Mandatory market regime metrics (vnindex_value/change_pct) are null",
        )

    if breadth is not None and not (0.0 <= breadth <= 1.0):
        return CheckResult(
            check_name="market_regime_status",
            status="FAIL",
            measured_value={"market_breadth_ratio": breadth},
            expected_condition="0.0 <= market_breadth_ratio <= 1.0",
            message=f"Market breadth ratio out of bounds: {breadth}",
        )

    return CheckResult(
        check_name="market_regime_status",
        status="PASS",
        measured_value={
            "regime": regime,
            "confidence": conf,
            "vnindex_value": vn_val,
            "market_breadth_ratio": breadth,
        },
        expected_condition="Valid regime, bounded confidence, and valid metrics",
        message=f"Market regime '{regime}' verified successfully",
    )


def check_history_index_status(generated_dir: str, data_as_of: str | None = None) -> CheckResult:
    """Validate history index (history/index.json) integrity, chronological ordering, and inclusion of data_as_of."""
    index_path = os.path.join(generated_dir, "history", "index.json")
    if not os.path.exists(index_path):
        return CheckResult(
            check_name="history_index_status",
            status="FAIL",
            measured_value={"index_path": index_path},
            expected_condition="history/index.json exists",
            message="History index file history/index.json does not exist",
        )

    try:
        with open(index_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as err:  # noqa: BLE001
        return CheckResult(
            check_name="history_index_status",
            status="FAIL",
            measured_value={"error": str(err)},
            expected_condition="history/index.json is valid JSON",
            message=f"Failed to read history index JSON: {err}",
        )

    if not isinstance(data, dict) or "dates" not in data:
        return CheckResult(
            check_name="history_index_status",
            status="FAIL",
            measured_value={"root_type": type(data).__name__},
            expected_condition="Dict root with 'dates' array",
            message="Invalid history index payload structure",
        )

    dates = data.get("dates")
    if not isinstance(dates, list):
        return CheckResult(
            check_name="history_index_status",
            status="FAIL",
            measured_value={"dates_type": type(dates).__name__},
            expected_condition="'dates' field is a list",
            message="History index 'dates' field is not a list",
        )

    invalid_date_items = [d for d in dates if not isinstance(d, str)]
    if invalid_date_items:
        return CheckResult(
            check_name="history_index_status",
            status="FAIL",
            measured_value={"invalid_items": invalid_date_items},
            expected_condition="All items in dates list are YYYY-MM-DD strings",
            message="History index contains non-string date entries",
        )

    # Check duplicate dates
    if len(dates) != len(set(dates)):
        return CheckResult(
            check_name="history_index_status",
            status="FAIL",
            measured_value={"total_dates": len(dates), "unique_dates": len(set(dates))},
            expected_condition="No duplicate dates in history index",
            message="History index contains duplicate date entries",
        )

    # Check sorting order (index.json requires reverse chronological order YYYY-MM-DD descending)
    sorted_desc = sorted(dates, reverse=True)
    if dates != sorted_desc:
        return CheckResult(
            check_name="history_index_status",
            status="FAIL",
            measured_value={"dates_sample": dates[:5]},
            expected_condition="Dates list sorted descending (newest first)",
            message="History index dates are not sorted in descending chronological order",
        )

    if data_as_of and data_as_of not in dates:
        return CheckResult(
            check_name="history_index_status",
            status="FAIL",
            measured_value={"data_as_of": data_as_of, "dates_count": len(dates)},
            expected_condition=f"data_as_of '{data_as_of}' present in history index dates",
            message=f"data_as_of '{data_as_of}' is missing from history/index.json dates list",
        )

    return CheckResult(
        check_name="history_index_status",
        status="PASS",
        measured_value={"total_reports": len(dates), "latest_date": dates[0] if dates else None},
        expected_condition="Valid sorted dates list containing data_as_of",
        message=f"History index verified with {len(dates)} historical report entries",
    )


def check_ohlcv_data_quality(df_ohlcv: Any, symbol_name: str) -> CheckResult:
    """Validate clean data boundary quality for an OHLCV dataset using validate_ohlcv_data."""
    val_res = validate_ohlcv_data(df_ohlcv, symbol_name)
    status_raw = val_res.get("status")
    issues = val_res.get("issues", [])

    if status_raw == "INSUFFICIENT":
        return CheckResult(
            check_name=f"ohlcv_quality_{symbol_name.lower()}",
            status="FAIL",
            measured_value={"status": status_raw, "issues": issues},
            expected_condition=f"OHLCV data for {symbol_name} is SUFFICIENT or PARTIAL",
            message=f"OHLCV data quality for '{symbol_name}' is INSUFFICIENT: {', '.join(issues)}",
        )

    if status_raw == "PARTIAL":
        return CheckResult(
            check_name=f"ohlcv_quality_{symbol_name.lower()}",
            status="WARNING",
            measured_value={"status": status_raw, "issues": issues},
            expected_condition=f"OHLCV data for {symbol_name} is SUFFICIENT",
            message=f"OHLCV data quality for '{symbol_name}' has partial warnings: {', '.join(issues)}",
        )

    return CheckResult(
        check_name=f"ohlcv_quality_{symbol_name.lower()}",
        status="PASS",
        measured_value={"status": status_raw, "valid_row_count": val_res.get("valid_row_count")},
        expected_condition=f"OHLCV data for {symbol_name} is SUFFICIENT",
        message=f"OHLCV data quality for '{symbol_name}' is SUFFICIENT ({val_res.get('valid_row_count')} valid rows)",
    )


def evaluate_production_monitoring(
    generated_dir: str | None = None,
    recommendations_payload: dict | None = None,
    market_payload: dict | None = None,
    reference_date: str | None = None,
    schema_path: str | None = None,
    stock_data_map: dict | None = None,
    df_vnindex: Any | None = None,
    df_vn30: Any | None = None,
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

    # 1. Artifact existence check
    if recommendations_payload is None:
        rec_file = os.path.join(g_dir, "recommendations.json")
        data_as_of_peek = None
        if os.path.exists(rec_file):
            try:
                with open(rec_file, "r", encoding="utf-8") as f:
                    rec_peek = json.load(f)
                    data_as_of_peek = rec_peek.get("data_as_of")
            except Exception:  # noqa: BLE001
                data_as_of_peek = None

        artifact_chk = check_required_artifacts(g_dir, data_as_of=data_as_of_peek)
        checks.append(artifact_chk)

        if artifact_chk.status == "PASS":
            with open(os.path.join(g_dir, "recommendations.json"), "r", encoding="utf-8") as f:
                recommendations_payload = json.load(f)
            with open(os.path.join(g_dir, "market.json"), "r", encoding="utf-8") as f:
                market_payload = json.load(f)

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

    if market_payload is None:
        market_payload = recommendations_payload.get("market", {})
    elif "market" in market_payload and isinstance(market_payload["market"], dict):
        market_payload = market_payload["market"]

    # 2. Schema validation check
    checks.append(check_schema_validation(recommendations_payload, schema_path=s_path))

    # 3. Data freshness check
    checks.append(check_data_freshness(data_as_of, reference_date=reference_date))

    # 4. Numeric sanity check (NaN/Inf safety)
    checks.append(check_numeric_sanity(recommendations_payload))

    # 5. Symbol processing counts check
    counts_chk = check_symbol_processing_counts(recommendations_payload)
    checks.append(counts_chk)

    # 6. Market regime status check
    checks.append(check_market_regime_status(market_payload))

    # 7. History index integrity check
    if os.path.exists(os.path.join(g_dir, "history", "index.json")):
        checks.append(check_history_index_status(g_dir, data_as_of=data_as_of))

    # 8. Benchmark OHLCV checks (if provided)
    if df_vnindex is not None:
        checks.append(check_ohlcv_data_quality(df_vnindex, "VNINDEX"))
    if df_vn30 is not None:
        checks.append(check_ohlcv_data_quality(df_vn30, "VN30"))

    # Aggregate overall status
    statuses = [c.status for c in checks]
    if "FAIL" in statuses:
        overall_status = "FAIL"
    elif "WARNING" in statuses:
        overall_status = "WARNING"
    else:
        overall_status = "PASS"

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
        "market_regime": market_payload.get("regime"),
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
