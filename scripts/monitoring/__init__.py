"""VN Invest v2 Monitoring Subsystem.

Provides operational monitoring, schema validation, metric extraction, data freshness,
and operational data/model drift evaluation.
"""

from scripts.lib.config import (
    DRIFT_BOUNDARY_TOLERANCE_ACTION_DISTRIBUTION,
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
)
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
from scripts.monitoring.evaluator import (
    evaluate_production_monitoring,
    validate_monitoring_payload,
)
from scripts.monitoring.metrics import (
    _extract_market_metrics,
    classify_confidence_bucket,
    extract_recommendation_metrics,
    is_canonical_yyyy_mm_dd,
    normalize_market_payload,
)
from scripts.monitoring.models import (
    CANONICAL_CONFIDENCE_BUCKETS,
    DEFAULT_GENERATED_DIR,
    DEFAULT_PERFORMANCE_SCHEMA_PATH,
    DEFAULT_SCHEMA_PATH,
    ROOT_DIR,
    VALID_CHECK_STATUSES,
    VALID_EXCLUSION_CATEGORIES,
    VALID_PIPELINE_STAGES,
    CheckResult,
    DriftCheckResult,
    DriftMonitoringResult,
    DriftObservation,
    PipelineMonitoringResult,
    _sanitize_value_for_json,
    find_nan_or_inf,
)
from scripts.monitoring.performance import (
    create_default_performance_payload,
    load_performance_schema,
    validate_performance_payload,
)
from scripts.performance.budget import evaluate_provider_budget
from scripts.performance.regression import evaluate_performance_regression

__all__ = [
    "CANONICAL_CONFIDENCE_BUCKETS",
    "DEFAULT_GENERATED_DIR",
    "DEFAULT_PERFORMANCE_SCHEMA_PATH",
    "DEFAULT_SCHEMA_PATH",
    "DRIFT_BOUNDARY_TOLERANCE_ACTION_DISTRIBUTION",
    "DRIFT_LOOKBACK_REPORTS",
    "DRIFT_MIN_BASELINE_REPORTS",
    "DRIFT_MIN_PROCESSED_RATIO",
    "DRIFT_THRESHOLD_ACTION_DISTRIBUTION",
    "DRIFT_THRESHOLD_BREADTH_RATIO",
    "DRIFT_THRESHOLD_CONFIDENCE_DISTRIBUTION",
    "DRIFT_THRESHOLD_CONFIDENCE_MEAN",
    "DRIFT_THRESHOLD_PROCESSED_RATIO",
    "DRIFT_THRESHOLD_RISK_ADJUSTED_SCORE_MEAN",
    "DRIFT_THRESHOLD_SIGNAL_SCORE_MEAN",
    "DRIFT_THRESHOLD_VNINDEX_CHANGE_PCT",
    "ROOT_DIR",
    "VALID_CHECK_STATUSES",
    "VALID_EXCLUSION_CATEGORIES",
    "VALID_PIPELINE_STAGES",
    "CheckResult",
    "DriftCheckResult",
    "DriftMonitoringResult",
    "DriftObservation",
    "PipelineMonitoringResult",
    "_extract_market_metrics",
    "_sanitize_value_for_json",
    "check_data_freshness",
    "check_history_index_status",
    "check_market_regime_status",
    "check_numeric_sanity",
    "check_ohlcv_data_quality",
    "check_required_artifacts",
    "check_schema_validation",
    "check_symbol_processing_counts",
    "check_universe_audit_invariants",
    "classify_confidence_bucket",
    "create_default_performance_payload",
    "evaluate_data_and_model_drift",
    "evaluate_performance_regression",
    "evaluate_production_monitoring",
    "evaluate_provider_budget",
    "extract_recommendation_metrics",
    "find_nan_or_inf",
    "is_canonical_yyyy_mm_dd",
    "load_performance_schema",
    "normalize_market_payload",
    "validate_monitoring_payload",
    "validate_performance_payload",
]
