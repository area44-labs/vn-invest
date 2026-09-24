"""Production Monitoring Module for VN Invest v2.

Provides deterministic, fail-closed operational monitoring for the production data-generation
and signal pipeline. Monitors data availability, freshness, processing counts, artifact integrity,
schema validation, numeric sanity (NaN/Inf safety), market regime status, history index integrity,
and operational data/model drift detection against historical baseline.

This module provides operational and data-pipeline monitoring ONLY.
It does NOT establish model predictive validity, profitability, calibration, statistical significance,
or model error. Confidence scores are deterministic model-confidence heuristics, not probabilities.
"""

import json
import logging
import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import jsonschema

from scripts.lib.config import (
    DRIFT_LOOKBACK_REPORTS,
    DRIFT_MIN_BASELINE_REPORTS,
    DRIFT_MIN_PROCESSED_RATIO,
    DRIFT_THRESHOLD_ACTION_DISTRIBUTION,
    DRIFT_THRESHOLD_BREADTH_RATIO,
    DRIFT_THRESHOLD_CONFIDENCE_DISTRIBUTION,
    DRIFT_THRESHOLD_CONFIDENCE_MEAN,
    DRIFT_THRESHOLD_PROCESSED_RATIO,
    DRIFT_THRESHOLD_RISK_ADJUSTED_SCORE_MEAN,
    DRIFT_THRESHOLD_SIGNAL_SCORE_MEAN,
    DRIFT_THRESHOLD_VNINDEX_CHANGE_PCT,
    SIGNAL_MODEL_VERSION,
    VALID_MARKET_REGIMES,
)
from scripts.lib.vietnam_market import validate_ohlcv_data

logger = logging.getLogger(__name__)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_GENERATED_DIR = os.path.join(ROOT_DIR, "generated")
DEFAULT_SCHEMA_PATH = os.path.join(ROOT_DIR, "schemas", "recommendations.schema.json")

VALID_CHECK_STATUSES = {"PASS", "WARNING", "FAIL"}

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


def is_canonical_yyyy_mm_dd(val: Any) -> bool:
    """Validate if a value is strictly a canonical YYYY-MM-DD calendar date string.

    Rejects booleans, non-strings, single-digit months/days, time components,
    timezone offsets/suffixes, and invalid calendar dates.
    """
    if not isinstance(val, str) or isinstance(val, bool):
        return False
    if len(val) != 10:
        return False
    parts = val.split("-")
    if len(parts) != 3 or len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
        return False
    if not (parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit()):
        return False
    try:
        dt = datetime.strptime(val, "%Y-%m-%d").replace(tzinfo=UTC)
        return dt.strftime("%Y-%m-%d") == val
    except ValueError:
        return False


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


def classify_confidence_bucket(conf: float | None) -> str | None:
    """Classify numeric confidence score [0.0..1.0] into canonical bucket string."""
    if conf is None:
        return None
    if isinstance(conf, bool) or not isinstance(conf, (int, float)):
        raise TypeError(f"Confidence score must be numeric or None, got {type(conf).__name__}")
    if math.isnan(conf) or math.isinf(conf):
        raise ValueError(f"Invalid non-finite confidence score: {conf}")
    if not (0.0 <= conf <= 1.0):
        raise ValueError(f"Confidence score out of bounds [0.0..1.0]: {conf}")

    if conf == 1.0:
        return "0.9-1.0"

    bucket_idx = min(int(conf * 10), 9)
    lower = bucket_idx / 10.0
    upper = (bucket_idx + 1) / 10.0
    return f"{lower:.1f}-{upper:.1f}"


def _extract_market_metrics(
    market_payload: dict | None, fallback_payload: dict | None
) -> tuple[str | None, float | None, float | None]:
    """Extract (regime, vnindex_change_pct, market_breadth_ratio) prioritizing market_payload."""
    m_source = (
        market_payload
        if market_payload is not None
        else (fallback_payload.get("market", {}) if isinstance(fallback_payload, dict) else {})
    )

    if not isinstance(m_source, dict):
        return None, None, None

    if "market" in m_source and isinstance(m_source["market"], dict):
        m_source = m_source["market"]

    regime = m_source.get("regime")
    m_metrics = m_source.get("metrics", {})
    if not isinstance(m_metrics, dict):
        m_metrics = {}

    vnindex_change_pct = m_metrics.get("vnindex_change_pct")
    if vnindex_change_pct is not None:
        if isinstance(vnindex_change_pct, bool) or not isinstance(vnindex_change_pct, (int, float)):
            raise TypeError(
                f"vnindex_change_pct must be numeric, got {type(vnindex_change_pct).__name__}"
            )
        f_vn = float(vnindex_change_pct)
        if math.isnan(f_vn) or math.isinf(f_vn):
            raise ValueError(f"vnindex_change_pct must be finite, got {f_vn}")
        vnindex_change_pct = f_vn

    market_breadth_ratio = m_metrics.get("market_breadth_ratio")
    if market_breadth_ratio is not None:
        if isinstance(market_breadth_ratio, bool) or not isinstance(
            market_breadth_ratio, (int, float)
        ):
            raise TypeError(
                f"market_breadth_ratio must be numeric, got {type(market_breadth_ratio).__name__}"
            )
        f_b = float(market_breadth_ratio)
        if math.isnan(f_b) or math.isinf(f_b):
            raise ValueError(f"market_breadth_ratio must be finite, got {f_b}")
        if not (0.0 <= f_b <= 1.0):
            raise ValueError(f"market_breadth_ratio out of bounds [0.0, 1.0]: {f_b}")
        market_breadth_ratio = f_b

    return regime, vnindex_change_pct, market_breadth_ratio


def extract_recommendation_metrics(
    payload: dict, market_payload: dict | None = None
) -> dict[str, Any]:
    """Extract operational distribution and numeric metrics from a recommendation report payload.

    Market metrics (vnindex_change_pct, market_breadth_ratio) strictly prioritize market_payload
    when provided, falling back to payload.get("market") only when market_payload is None.

    Fails closed by raising ValueError or TypeError if payload, summary, recommendations items,
    or model metrics are malformed or non-finite.
    """
    if not isinstance(payload, dict):
        raise TypeError(f"Payload must be a dict, got {type(payload).__name__}")

    recs = payload.get("recommendations")
    if not isinstance(recs, list):
        raise TypeError(f"Recommendations must be a list, got {type(recs).__name__}")

    # 1. Validate each recommendation item
    valid_actions = {"BUY", "WATCH", "HOLD", "SELL", "AVOID"}
    for idx, r in enumerate(recs):
        if not isinstance(r, dict):
            raise TypeError(
                f"Recommendation item at index {idx} must be a dict, got {type(r).__name__}"
            )
        act = r.get("action")
        if not isinstance(act, str) or isinstance(act, bool) or act not in valid_actions:
            raise ValueError(
                f"Recommendation item at index {idx} has missing or invalid action: {act}"
            )

    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise TypeError(f"Summary must be a dict, got {type(summary).__name__}")

    # 2. Validate summary consistency
    total_scanned = summary.get("total_scanned")
    if isinstance(total_scanned, bool) or not isinstance(total_scanned, int) or total_scanned < 0:
        raise ValueError(
            f"Invalid summary total_scanned: {total_scanned}. Must be non-boolean non-negative integer"
        )

    if total_scanned != len(recs):
        raise ValueError(
            f"Summary total_scanned ({total_scanned}) does not match recommendations list count ({len(recs)})"
        )

    action_counts = {}
    for act_key, count_field in [
        ("BUY", "buy_count"),
        ("WATCH", "watch_count"),
        ("HOLD", "hold_count"),
        ("SELL", "sell_count"),
        ("AVOID", "avoid_count"),
    ]:
        cnt = summary.get(count_field)
        if isinstance(cnt, bool) or not isinstance(cnt, int) or cnt < 0:
            raise ValueError(
                f"Invalid summary {count_field}: {cnt}. Must be non-boolean non-negative integer"
            )
        action_counts[act_key] = cnt

    sum_action_counts = sum(action_counts.values())
    if sum_action_counts != total_scanned:
        raise ValueError(
            f"Summary action counts sum ({sum_action_counts}) does not equal total_scanned ({total_scanned})"
        )

    actual_action_counts = {act: 0 for act in valid_actions}
    for r in recs:
        actual_action_counts[r["action"]] += 1

    for act, expected_cnt in action_counts.items():
        actual_cnt = actual_action_counts[act]
        if actual_cnt != expected_cnt:
            raise ValueError(
                f"Summary action count mismatch for {act}: summary={expected_cnt} vs actual={actual_cnt}"
            )

    if total_scanned > 0:
        action_proportions = {
            act: round(cnt / total_scanned, 6) for act, cnt in action_counts.items()
        }
    else:
        action_proportions = {act: 0.0 for act in action_counts}

    for act, prop in action_proportions.items():
        if not (0.0 <= prop <= 1.0):
            raise ValueError(
                f"Action proportion for {act} ({prop}) is outside allowed bounds [0.0, 1.0]"
            )

    processed_count = sum(1 for r in recs if r.get("data_quality") in ("SUFFICIENT", "PARTIAL"))
    processed_ratio = round(processed_count / total_scanned, 6) if total_scanned > 0 else 0.0

    # 3. Validate confidence, signal_score, and risk_adjusted_score on each recommendation item
    conf_counts = {b: 0 for b in CANONICAL_CONFIDENCE_BUCKETS}
    valid_conf_vals = []
    sig_scores = []
    risk_scores = []

    for idx, r in enumerate(recs):
        sym = r.get("symbol", f"item_{idx}")

        conf = r.get("confidence")
        if conf is not None:
            if isinstance(conf, bool) or not isinstance(conf, (int, float)):
                raise TypeError(
                    f"Confidence score for '{sym}' must be numeric, got {type(conf).__name__}"
                )
            f_conf = float(conf)
            if math.isnan(f_conf) or math.isinf(f_conf):
                raise ValueError(f"Confidence score for '{sym}' must be finite, got {f_conf}")
            if not (0.0 <= f_conf <= 1.0):
                raise ValueError(f"Confidence score for '{sym}' out of bounds [0.0, 1.0]: {f_conf}")
            bucket = classify_confidence_bucket(f_conf)
            if bucket in conf_counts:
                conf_counts[bucket] += 1
                valid_conf_vals.append(f_conf)

        ss = r.get("signal_score")
        if ss is not None:
            if isinstance(ss, bool) or not isinstance(ss, (int, float)):
                raise TypeError(
                    f"Signal score for '{sym}' must be numeric, got {type(ss).__name__}"
                )
            f_ss = float(ss)
            if math.isnan(f_ss) or math.isinf(f_ss):
                raise ValueError(f"Signal score for '{sym}' must be finite, got {f_ss}")
            sig_scores.append(f_ss)

        rs = r.get("risk_adjusted_score")
        if rs is not None:
            if isinstance(rs, bool) or not isinstance(rs, (int, float)):
                raise TypeError(
                    f"Risk-adjusted score for '{sym}' must be numeric, got {type(rs).__name__}"
                )
            f_rs = float(rs)
            if math.isnan(f_rs) or math.isinf(f_rs):
                raise ValueError(f"Risk-adjusted score for '{sym}' must be finite, got {f_rs}")
            risk_scores.append(f_rs)

    total_valid_conf = len(valid_conf_vals)
    if total_valid_conf > 0:
        conf_bucket_proportions = {
            b: round(conf_counts[b] / total_valid_conf, 6) for b in CANONICAL_CONFIDENCE_BUCKETS
        }
    else:
        conf_bucket_proportions = {b: 0.0 for b in CANONICAL_CONFIDENCE_BUCKETS}

    sig_mean = round(sum(sig_scores) / len(sig_scores), 4) if sig_scores else None
    sig_median = round(sorted(sig_scores)[len(sig_scores) // 2], 4) if sig_scores else None

    risk_mean = round(sum(risk_scores) / len(risk_scores), 4) if risk_scores else None
    risk_median = round(sorted(risk_scores)[len(risk_scores) // 2], 4) if risk_scores else None

    conf_mean = round(sum(valid_conf_vals) / len(valid_conf_vals), 4) if valid_conf_vals else None

    regime, vnindex_change_pct, market_breadth_ratio = _extract_market_metrics(
        market_payload, payload
    )

    return {
        "total_scanned": total_scanned,
        "processed_count": processed_count,
        "processed_ratio": processed_ratio,
        "action_counts": action_counts,
        "action_proportions": action_proportions,
        "confidence_bucket_counts": conf_counts,
        "confidence_bucket_proportions": conf_bucket_proportions,
        "signal_score_mean": sig_mean,
        "signal_score_median": sig_median,
        "risk_adjusted_score_mean": risk_mean,
        "risk_adjusted_score_median": risk_median,
        "confidence_mean": conf_mean,
        "market_regime": regime,
        "vnindex_change_pct": vnindex_change_pct,
        "market_breadth_ratio": market_breadth_ratio,
    }


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

    # Validate drift threshold configurations dynamically from module globals
    thresh_configs = [
        (
            "DRIFT_THRESHOLD_PROCESSED_RATIO",
            globals().get("DRIFT_THRESHOLD_PROCESSED_RATIO", DRIFT_THRESHOLD_PROCESSED_RATIO),
        ),
        (
            "DRIFT_THRESHOLD_BREADTH_RATIO",
            globals().get("DRIFT_THRESHOLD_BREADTH_RATIO", DRIFT_THRESHOLD_BREADTH_RATIO),
        ),
        (
            "DRIFT_THRESHOLD_VNINDEX_CHANGE_PCT",
            globals().get("DRIFT_THRESHOLD_VNINDEX_CHANGE_PCT", DRIFT_THRESHOLD_VNINDEX_CHANGE_PCT),
        ),
        (
            "DRIFT_THRESHOLD_ACTION_DISTRIBUTION",
            globals().get(
                "DRIFT_THRESHOLD_ACTION_DISTRIBUTION", DRIFT_THRESHOLD_ACTION_DISTRIBUTION
            ),
        ),
        (
            "DRIFT_THRESHOLD_CONFIDENCE_DISTRIBUTION",
            globals().get(
                "DRIFT_THRESHOLD_CONFIDENCE_DISTRIBUTION", DRIFT_THRESHOLD_CONFIDENCE_DISTRIBUTION
            ),
        ),
        (
            "DRIFT_THRESHOLD_SIGNAL_SCORE_MEAN",
            globals().get("DRIFT_THRESHOLD_SIGNAL_SCORE_MEAN", DRIFT_THRESHOLD_SIGNAL_SCORE_MEAN),
        ),
        (
            "DRIFT_THRESHOLD_RISK_ADJUSTED_SCORE_MEAN",
            globals().get(
                "DRIFT_THRESHOLD_RISK_ADJUSTED_SCORE_MEAN", DRIFT_THRESHOLD_RISK_ADJUSTED_SCORE_MEAN
            ),
        ),
        (
            "DRIFT_THRESHOLD_CONFIDENCE_MEAN",
            globals().get("DRIFT_THRESHOLD_CONFIDENCE_MEAN", DRIFT_THRESHOLD_CONFIDENCE_MEAN),
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

    if baseline_reports is not None:
        # Injected baseline reports (e.g., unit test fixtures)
        for idx, r in enumerate(baseline_reports):
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
                "available_reports": num_baseline_reports,
                "required_reports": min_baseline_reports,
                "considered_reports_count": len(considered_dates),
                "excluded_reports_count": len(excluded_dates),
                "qualified_reports_count": num_baseline_reports,
                "min_processed_ratio_threshold": min_processed_ratio,
                "baseline_dates": baseline_dates_used,
                "excluded_dates": excluded_dates,
                "considered_dates": considered_dates,
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
                "report_count": num_baseline_reports,
                "available_reports": num_baseline_reports,
                "considered_reports_count": len(considered_dates),
                "excluded_reports_count": len(excluded_dates),
                "qualified_reports_count": num_baseline_reports,
                "required_reports": min_baseline_reports,
                "min_processed_ratio_threshold": min_processed_ratio,
                "baseline_dates": baseline_dates_used,
                "excluded_dates": excluded_dates,
                "considered_dates": considered_dates,
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
        "report_count": num_baseline_reports,
        "considered_reports_count": len(considered_dates),
        "excluded_reports_count": len(excluded_dates),
        "qualified_reports_count": num_baseline_reports,
        "min_processed_ratio_threshold": min_processed_ratio,
        "start_date": baseline_dates_used[-1] if baseline_dates_used else None,
        "end_date": baseline_dates_used[0] if baseline_dates_used else None,
        "baseline_dates": baseline_dates_used,
        "excluded_dates": excluded_dates,
        "considered_dates": considered_dates,
    }

    drift_checks: list[DriftCheckResult] = []

    # 1. Processed ratio drift
    proc_warn, proc_fail = globals().get(
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
    b_warn, b_fail = globals().get("DRIFT_THRESHOLD_BREADTH_RATIO", DRIFT_THRESHOLD_BREADTH_RATIO)
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
    v_warn, v_fail = globals().get(
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
    a_warn, a_fail = globals().get(
        "DRIFT_THRESHOLD_ACTION_DISTRIBUTION", DRIFT_THRESHOLD_ACTION_DISTRIBUTION
    )
    curr_action_props = current_metrics["action_proportions"]
    action_diffs = {
        act: round(abs(curr_action_props[act] - baseline_action_props[act]), 6)
        for act in ["BUY", "WATCH", "HOLD", "SELL", "AVOID"]
    }
    max_action_diff = max(action_diffs.values())
    if max_action_diff > a_fail:
        a_status = "FAIL"
    elif max_action_diff > a_warn:
        a_status = "WARNING"
    else:
        a_status = "PASS"

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
        message=f"Action distribution max proportion shift is {max_action_diff:.4f} across actions",
    )
    drift_checks.append(
        DriftCheckResult(check_name="drift_action_distribution", status=a_status, observation=a_obs)
    )

    # 5. Confidence bucket distribution drift
    c_warn, c_fail = globals().get(
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
    s_warn, s_fail = globals().get(
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
    r_warn, r_fail = globals().get(
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
    cm_warn, cm_fail = globals().get(
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
        "report_count": num_baseline_reports,
        "considered_reports_count": len(considered_dates),
        "excluded_reports_count": len(excluded_dates),
        "qualified_reports_count": num_baseline_reports,
        "min_processed_ratio_threshold": min_processed_ratio,
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


def check_numeric_sanity(payload: dict, market_payload: dict | None = None) -> CheckResult:
    """Scan recommendations payload and market payload for NaN/Inf float values or out-of-bounds scores."""
    nan_inf_issues = find_nan_or_inf(payload, path="recommendations_payload")
    if market_payload:
        nan_inf_issues.extend(find_nan_or_inf(market_payload, path="market_payload"))

    if nan_inf_issues:
        return CheckResult(
            check_name="numeric_sanity",
            status="FAIL",
            measured_value={"nan_inf_issues": nan_inf_issues[:10]},
            expected_condition="No NaN or Inf float values anywhere in recommendations or market payload",
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
    - Genuine pipeline failure: sum mismatch, total_scanned mismatch, action mismatch, 0 total scanned, or < 50% processed ratio.
    - Expected insufficient-data condition: individual stock with INSUFFICIENT data_quality (decoupled from AVOID action), processed ratio >= 80%.
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

    # Compute actual action counts directly from recommendation items
    actual_buy = sum(1 for r in recs if r.get("action") == "BUY")
    actual_watch = sum(1 for r in recs if r.get("action") == "WATCH")
    actual_hold = sum(1 for r in recs if r.get("action") == "HOLD")
    actual_sell = sum(1 for r in recs if r.get("action") == "SELL")
    actual_avoid = sum(1 for r in recs if r.get("action") == "AVOID")

    action_mismatches = []
    if buy_cnt != actual_buy:
        action_mismatches.append(f"buy_count: summary={buy_cnt} vs actual={actual_buy}")
    if watch_cnt != actual_watch:
        action_mismatches.append(f"watch_count: summary={watch_cnt} vs actual={actual_watch}")
    if hold_cnt != actual_hold:
        action_mismatches.append(f"hold_count: summary={hold_cnt} vs actual={actual_hold}")
    if sell_cnt != actual_sell:
        action_mismatches.append(f"sell_count: summary={sell_cnt} vs actual={actual_sell}")
    if avoid_cnt != actual_avoid:
        action_mismatches.append(f"avoid_count: summary={avoid_cnt} vs actual={actual_avoid}")

    if action_mismatches:
        return CheckResult(
            check_name="symbol_processing_counts",
            status="FAIL",
            measured_value={
                "summary": summary,
                "actual_actions": {
                    "BUY": actual_buy,
                    "WATCH": actual_watch,
                    "HOLD": actual_hold,
                    "SELL": actual_sell,
                    "AVOID": actual_avoid,
                },
            },
            expected_condition="summary action counts strictly match actual recommendation actions",
            message=f"Summary action count mismatch: {'; '.join(action_mismatches)}",
        )

    processed_count = sum(1 for r in recs if r.get("data_quality") in ("SUFFICIENT", "PARTIAL"))
    insufficient_count = sum(1 for r in recs if r.get("data_quality") == "INSUFFICIENT")

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

    invalid_date_items = []
    for d in dates:
        if not isinstance(d, str):
            invalid_date_items.append(str(d))
        else:
            try:
                datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=UTC)
            except ValueError:
                invalid_date_items.append(d)

    if invalid_date_items:
        return CheckResult(
            check_name="history_index_status",
            status="FAIL",
            measured_value={"invalid_items": invalid_date_items},
            expected_condition="All items in dates list are valid canonical YYYY-MM-DD calendar date strings",
            message=f"History index contains invalid date entries: {', '.join(invalid_date_items[:5])}",
        )

    # Check that corresponding history date JSON files exist on disk
    missing_history_files = []
    for d in dates:
        file_path = os.path.join(generated_dir, "history", f"{d}.json")
        if not os.path.exists(file_path):
            missing_history_files.append(f"history/{d}.json")

    if missing_history_files:
        return CheckResult(
            check_name="history_index_status",
            status="FAIL",
            measured_value={"missing_files": missing_history_files[:10]},
            expected_condition="Every date in history index has a corresponding history/YYYY-MM-DD.json artifact file",
            message=f"History index references missing report files: {', '.join(missing_history_files[:3])}",
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

    # 1. Artifact existence check (ALWAYS executed on disk)
    artifact_chk = check_required_artifacts(g_dir, data_as_of=data_as_of_peek)
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

    if market_payload is None:
        market_payload = recommendations_payload.get("market", {})
    elif "market" in market_payload and isinstance(market_payload["market"], dict):
        market_payload = market_payload["market"]

    # 2. Schema validation check
    checks.append(check_schema_validation(recommendations_payload, schema_path=s_path))

    # 3. Data freshness check
    checks.append(check_data_freshness(data_as_of, reference_date=reference_date))

    # 4. Numeric sanity check (NaN/Inf safety) across recommendations and market payloads
    checks.append(check_numeric_sanity(recommendations_payload, market_payload=market_payload))

    # 5. Symbol processing counts check
    counts_chk = check_symbol_processing_counts(recommendations_payload)
    checks.append(counts_chk)

    # 6. Market regime status check
    checks.append(check_market_regime_status(market_payload))

    # 7. History index integrity check (ALWAYS executed, fails closed if history/index.json is missing)
    checks.append(check_history_index_status(g_dir, data_as_of=data_as_of))

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
        "drift_monitoring": drift_res.to_dict(),
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
