"""Quantitative Recommendation Model Centralized Configuration / Parameters.

Contains all model parameters, threshold constants, signal component weights,
market regime classification thresholds, risk model factors, confidence score rules,
and trade plan rules for the VN Invest quantitative engine.

NOTE: All quantitative formulas and parameters in this file preserve exact current engine semantics.
"""

# Signal Model Version
SIGNAL_MODEL_VERSION = "2.0"

# Component weights for composite signal score
# Rationale:
# - Trend (30%): Primary direction vector based on price relative to moving averages (MA20, MA50).
# - Momentum (25%): RSI and MACD indicator confirmation evaluating move strength and momentum decay.
# - Volume (15%): Volume ratio confirming institutional participation vs lack of market liquidity.
# - Relative Strength (15%): Performance relative to benchmark (VN-Index) over 20 sessions.
# - Divergence (15%): Multi-timeframe bullish/bearish divergence signals indicating potential trend reversals.
SIGNAL_WEIGHTS = {
    "trend": 0.30,
    "momentum": 0.25,
    "volume": 0.15,
    "relative_strength": 0.15,
    "divergence": 0.15,
}

# Timeframe weights for multi-timeframe divergence component scoring.
# Rationale: Short-to-intermediate timeframes (1D, 1W) take precedence over monthly (1M) setups.
DIVERGENCE_TIMEFRAME_WEIGHTS = {
    "1D": 0.50,
    "1W": 0.30,
    "1M": 0.20,
}

# Supported market regime identifiers
VALID_MARKET_REGIMES = {
    "STRONG_BULL",
    "BULL",
    "NEUTRAL",
    "DEFENSIVE",
    "BEAR",
    "PANIC",
}

# Data requirement thresholds
MIN_HISTORY_SESSIONS = 20
MIN_COMPONENTS_FOR_SIGNAL = 3
MIN_COMPONENTS_FOR_SUFFICIENT_QUALITY = 5

# Indicator Default Parameters
ATR_DEFAULT_PERIOD = 14
MA_SHORT_PERIOD = 20
MA_LONG_PERIOD = 50
RSI_DEFAULT_PERIOD = 14
MACD_FAST_PERIOD = 12
MACD_SLOW_PERIOD = 26
MACD_SIGNAL_PERIOD = 9

# Trend Scoring Parameters
TREND_BASE_SCORE = 50.0
TREND_MA20_WEIGHT = 25.0
TREND_MA50_WEIGHT = 15.0
TREND_MA20_VS_MA50_WEIGHT = 10.0

# Momentum (RSI & MACD) Scoring Parameters
MOMENTUM_BASE_SCORE = 50.0

RSI_OVERBOUGHT_EXTREME = 78.0
RSI_OVERBOUGHT = 70.0
RSI_STRONG_MOMENTUM_LOWER = 65.0
RSI_SAFE_LOWER = 45.0
RSI_SAFE_UPPER = 65.0
RSI_WEAK_LOWER = 35.0

RSI_SCORE_OVERBOUGHT_EXTREME_PENALTY = 25.0
RSI_SCORE_OVERBOUGHT_PENALTY = 15.0
RSI_SCORE_STRONG_MOMENTUM_BONUS = 10.0
RSI_SCORE_SAFE_BONUS = 20.0
RSI_SCORE_WEAK_PENALTY = 10.0
RSI_SCORE_OVERSOLD_PENALTY = 20.0

MACD_SCORE_POS_EXPANDING = 25.0
MACD_SCORE_POS_CONTRACTING = 10.0
MACD_SCORE_NEG_EXPANDING = 25.0
MACD_SCORE_NEG_CONTRACTING = 10.0
MACD_SCORE_POS_SINGLE = 15.0
MACD_SCORE_NEG_SINGLE = 15.0

# Volume Scoring Parameters
VOLUME_RATIO_VERY_HIGH = 2.0
VOLUME_RATIO_HIGH = 1.5
VOLUME_RATIO_ABOVE_AVG = 1.2
VOLUME_RATIO_NORMAL = 0.8
VOLUME_RATIO_LOW = 0.5

VOLUME_SCORE_VERY_HIGH = 100.0
VOLUME_SCORE_HIGH = 85.0
VOLUME_SCORE_ABOVE_AVG = 70.0
VOLUME_SCORE_NORMAL = 50.0
VOLUME_SCORE_LOW = 35.0
VOLUME_SCORE_VERY_LOW = 20.0

# Relative Strength vs Benchmark Parameters
RS_DIFF_STRONG_OUTPERFORM = 0.10
RS_DIFF_OUTPERFORM = 0.05
RS_DIFF_MILD_OUTPERFORM = 0.02
RS_DIFF_NEUTRAL = -0.02
RS_DIFF_UNDERPERFORM = -0.05

RS_SCORE_STRONG_OUTPERFORM = 100.0
RS_SCORE_OUTPERFORM = 80.0
RS_SCORE_MILD_OUTPERFORM = 65.0
RS_SCORE_NEUTRAL = 50.0
RS_SCORE_UNDERPERFORM = 35.0
RS_SCORE_STRONG_UNDERPERFORM = 15.0

# Divergence Scoring Parameters
DIVERGENCE_SCORE_BULLISH = 90.0
DIVERGENCE_SCORE_BEARISH = 10.0
DIVERGENCE_SCORE_CONFLICT = 40.0
DIVERGENCE_SCORE_NEUTRAL = 50.0

DIVERGENCE_MIN_HISTORY = 15
DIVERGENCE_LOOKBACK_1D = 40
DIVERGENCE_LOOKBACK_1W = 30
DIVERGENCE_LOOKBACK_1M = 24
DIVERGENCE_TROUGH_PRICE_TOLERANCE = 1.01
DIVERGENCE_PEAK_PRICE_TOLERANCE = 0.99
DIVERGENCE_RSI_DELTA = 1.5
DIVERGENCE_MACD_DELTA = 0.05
DIVERGENCE_FALLBACK_RSI_DELTA = 3.0
DIVERGENCE_FALLBACK_RSI_MAX = 40.0

# Confidence Calculation Parameters
# Note on Semantics:
# "confidence" values are deterministic heuristic / model-confidence scores, not statistically
# calibrated probabilities. They represent internal model data completeness, signal agreement,
# and volatility bounds rules. The same inputs produce identical confidence outputs. A value
# of 0.80 does NOT imply an 80% statistical probability of recommendation accuracy.
CONFIDENCE_MIN = 0.10
CONFIDENCE_MAX = 0.95
CONFIDENCE_BASE_SUFFICIENT = 0.70
CONFIDENCE_BASE_PARTIAL = 0.55

DISPERSION_STD_VERY_LOW = 12.0
DISPERSION_STD_LOW = 18.0
DISPERSION_STD_HIGH = 30.0
DISPERSION_STD_MODERATE_HIGH = 22.0

CONFIDENCE_ADJ_VERY_LOW_DISPERSION = 0.10
CONFIDENCE_ADJ_LOW_DISPERSION = 0.05
CONFIDENCE_ADJ_HIGH_DISPERSION = -0.15
CONFIDENCE_ADJ_MODERATE_HIGH_DISPERSION = -0.08

RISK_VOLATILITY_HIGH = 0.35
RISK_DRAWDOWN_HIGH = 0.25
RISK_VOLATILITY_LOW = 0.22
RISK_DRAWDOWN_LOW = 0.12

CONFIDENCE_ADJ_HIGH_RISK = -0.05
CONFIDENCE_ADJ_LOW_RISK = 0.05
CONFIDENCE_ADJ_EXTREME_RSI = -0.05

# Risk-Adjusted Score Parameters
REGIME_SCORE_FACTORS = {
    "STRONG_BULL": 1.05,
    "BULL": 1.00,
    "NEUTRAL": 0.90,
    "DEFENSIVE": 0.90,
    "BEAR": 0.75,
    "PANIC": 0.50,
}

VOLATILITY_PENALTY_THRESHOLD = 0.20
VOLATILITY_PENALTY_FACTOR = 0.5
VOLATILITY_PENALTY_MAX = 0.25

DRAWDOWN_PENALTY_THRESHOLD = 0.15
DRAWDOWN_PENALTY_FACTOR = 0.5
DRAWDOWN_PENALTY_MAX = 0.25

LIQUIDITY_FACTOR_BASE = 0.85
LIQUIDITY_FACTOR_SCALE = 0.15

# Action Classification Parameters
SCORE_THRESHOLD_STRONG_BUY = 75.0
SCORE_THRESHOLD_BUY = 65.0
SCORE_THRESHOLD_WATCH = 55.0
SCORE_THRESHOLD_HOLD = 45.0
SCORE_THRESHOLD_SELL = 35.0

REGIMES_STRONG_BUY = {"STRONG_BULL", "BULL"}
REGIMES_BUY = {"STRONG_BULL", "BULL", "DEFENSIVE"}

# Trade Plan Generation Parameters
TRADE_PLAN_STOP_ATR_MULT = 1.8
TRADE_PLAN_DEFAULT_STOP_PCT = 0.95
TRADE_PLAN_MA20_STOP_PCT = 0.98
TRADE_PLAN_MAX_STOP_PCT = 0.93
TRADE_PLAN_STOP_CLAMP_CAP = 0.99
TRADE_PLAN_MIN_RISK_PCT = 0.03
TRADE_PLAN_ENTRY_HIGH_MULT = 1.02
TRADE_PLAN_TP1_RR_MULT = 2.0
TRADE_PLAN_TP2_RR_MULT = 3.0
TRADE_PLAN_DEFAULT_RR = 1.0
TRADE_PLAN_DEFAULT_STOP_DIST_PCT = 0.05
TRADE_PLAN_PORTFOLIO_RISK_BUDGET_PCT = 1.0
TRADE_PLAN_MAX_POSITION_BUY_PCT = 20.0
TRADE_PLAN_MAX_POSITION_WATCH_PCT = 10.0

# Market Regime Detection Parameters
REGIME_MIN_HISTORY = 20
REGIME_BASE_SCORE = 50.0

REGIME_TREND_MA20_WEIGHT = 15.0
REGIME_TREND_MA50_WEIGHT = 10.0

REGIME_RET_20D_STRONG_BULL = 5.0
REGIME_RET_20D_BULL = 1.0
REGIME_RET_20D_STRONG_BEAR = -5.0
REGIME_RET_20D_BEAR = -1.0

REGIME_RET_20D_STRONG_BULL_SCORE = 15.0
REGIME_RET_20D_BULL_SCORE = 8.0
REGIME_RET_20D_STRONG_BEAR_SCORE = -15.0
REGIME_RET_20D_BEAR_SCORE = -8.0

REGIME_BREADTH_HIGH = 0.65
REGIME_BREADTH_MED = 0.50
REGIME_BREADTH_LOW = 0.35

REGIME_BREADTH_HIGH_SCORE = 10.0
REGIME_BREADTH_MED_SCORE = 5.0
REGIME_BREADTH_LOW_SCORE = -10.0

REGIME_PANIC_VOLATILITY = 0.35
REGIME_PANIC_DAILY_DROP_PCT = -3.0
REGIME_PANIC_PENALTY = -15.0

REGIME_THRESHOLD_STRONG_BULL = 80.0
REGIME_THRESHOLD_BULL = 60.0
REGIME_THRESHOLD_DEFENSIVE = 40.0
REGIME_THRESHOLD_BEAR = 20.0

REGIME_CONFIDENCE_SUFFICIENT = 0.85
REGIME_CONFIDENCE_PARTIAL = 0.60
REGIME_CONFIDENCE_HISTORY_THRESHOLD = 50

# Temporal Data Consistency & Staleness Threshold Parameters
# MAX_STOCK_STALENESS_DAYS: Maximum allowed calendar day lag between a stock's latest date
# and VNINDEX data_as_of (7 calendar days allows up to 5 trading days / weekend gaps).
MAX_STOCK_STALENESS_DAYS = 7
MAX_BENCHMARK_FUTURE_DAYS = 0

# Production Update Provider Throttle Configuration
# DEFAULT_UPDATE_THROTTLE_DELAY: Throttle delay in seconds applied between requests during production update mode.
DEFAULT_UPDATE_THROTTLE_DELAY = 3.5

# Data / Model Drift Monitoring Configuration & Threshold Parameters
# Lookback and minimum baseline rules
DRIFT_LOOKBACK_REPORTS = 20
DRIFT_MIN_BASELINE_REPORTS = 5
DRIFT_MIN_PROCESSED_RATIO = 0.80

# Fixed threshold bounds: (warning_threshold, fail_threshold)
# Ratios & Distributions (Absolute differences in proportions or ratios)
DRIFT_THRESHOLD_PROCESSED_RATIO = (0.15, 0.30)
DRIFT_THRESHOLD_BREADTH_RATIO = (0.25, 0.40)
DRIFT_THRESHOLD_ACTION_DISTRIBUTION = (0.20, 0.35)
DRIFT_THRESHOLD_CONFIDENCE_DISTRIBUTION = (0.25, 0.40)

# Small deterministic boundary tolerance for action distribution drift monitoring.
# Rationale: Prevents numerical/boundary sensitivity on marginal shifts only slightly above
# the 0.35 FAIL threshold (e.g., 0.350340 in production) while ensuring genuine larger drift
# (e.g., > 0.3510) still produces FAIL.
DRIFT_BOUNDARY_TOLERANCE_ACTION_DISTRIBUTION = 0.001

# Scores & Change Metrics (Absolute numerical differences)
DRIFT_THRESHOLD_SIGNAL_SCORE_MEAN = (15.0, 25.0)
DRIFT_THRESHOLD_RISK_ADJUSTED_SCORE_MEAN = (15.0, 25.0)
DRIFT_THRESHOLD_CONFIDENCE_MEAN = (0.15, 0.25)
DRIFT_THRESHOLD_VNINDEX_CHANGE_PCT = (3.0, 5.0)

# Stable Pipeline Stages for Operational Observability
PIPELINE_STAGES = (
    "UNIVERSE_DISCOVERY",
    "BENCHMARK_FETCH",
    "STOCK_FETCH",
    "DATA_VALIDATION",
    "TEMPORAL_VALIDATION",
    "CALCULATION",
    "MONITORING",
    "OUTPUT_VALIDATION",
    "ARTIFACT_WRITE",
)

# Authoritative Pipeline Stages & Statuses for Performance Profiling (PR #156)
PERFORMANCE_PIPELINE_STAGES = (
    "pipeline",
    "benchmark_fetch",
    "stock_fetch",
    "temporal_validation",
    "market_calculation",
    "regime_calculation",
    "risk_calculation",
    "recommendation_calculation",
    "monitoring",
    "payload_validation",
)

VALID_STAGE_STATUSES = (
    "SUCCESS",
    "DEGRADED",
    "FAILED",
)

# Stable Failure & Classification Categories for Operational Observability
FAILURE_CATEGORIES = (
    "PROVIDER_FAILURE",
    "RATE_LIMIT",
    "INVALID_SYMBOL",
    "EXPLICITLY_INVALID",
    "INSUFFICIENT_HISTORICAL_DATA",
    "TEMPORAL_INVALID",
    "OUTPUT_VALIDATION_FAILURE",
    "MONITORING_FAILURE",
    "UNIVERSE_INCOMPLETE",
    "OTHER_VALIDATION_FAILURE",
    "MISSING_SYMBOL",
    "UNKNOWN",
)

RECOVERABLE_FAILURE_CATEGORIES = {
    "PROVIDER_FAILURE",
    "RATE_LIMIT",
}


def is_recoverable_category(category: str) -> bool:
    """Return True if failure category is considered transient/recoverable, False otherwise.

    - PROVIDER_FAILURE, RATE_LIMIT -> recoverable (transient network or rate limits)
    - INVALID_SYMBOL, EXPLICITLY_INVALID, INSUFFICIENT_HISTORICAL_DATA, TEMPORAL_INVALID,
      OUTPUT_VALIDATION_FAILURE, MONITORING_FAILURE, UNIVERSE_INCOMPLETE -> non-recoverable
    """
    return category in RECOVERABLE_FAILURE_CATEGORIES
