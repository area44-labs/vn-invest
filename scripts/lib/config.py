"""Quantitative Recommendation Model Centralized Configuration / Parameters.

Contains all model parameters, threshold constants, signal component weights,
market regime classification thresholds, risk model factors, confidence score rules,
and trade plan rules for the VN Invest quantitative engine.

NOTE: All quantitative formulas and parameters delegate directly to DEFAULT_QUANT_CONFIG from scripts.quant.config.
"""

from scripts.schema import SCHEMA_VERSION
from scripts.quant.config import DEFAULT_QUANT_CONFIG, QuantConfig

# Signal, Pipeline, and Schema Version Contracts
QUANT_VERSION = DEFAULT_QUANT_CONFIG.quant_version
SIGNAL_MODEL_VERSION = DEFAULT_QUANT_CONFIG.model_version
PIPELINE_VERSION = "2.0.0"
QUANT_VERSION_CONTRACT = DEFAULT_QUANT_CONFIG.version_contract

# Component weights for composite signal score
SIGNAL_WEIGHTS = DEFAULT_QUANT_CONFIG.signal_weights

# Timeframe weights for multi-timeframe divergence component scoring.
DIVERGENCE_TIMEFRAME_WEIGHTS = DEFAULT_QUANT_CONFIG.divergence_timeframe_weights

# Supported market regime identifiers
VALID_MARKET_REGIMES = set(DEFAULT_QUANT_CONFIG.valid_market_regimes)

# Data requirement thresholds
MIN_HISTORY_SESSIONS = DEFAULT_QUANT_CONFIG.ma_short_period
MIN_COMPONENTS_FOR_SIGNAL = DEFAULT_QUANT_CONFIG.min_components_for_signal
MIN_COMPONENTS_FOR_SUFFICIENT_QUALITY = DEFAULT_QUANT_CONFIG.min_components_for_sufficient_quality

# Indicator Default Parameters
ATR_DEFAULT_PERIOD = DEFAULT_QUANT_CONFIG.atr_period
MA_SHORT_PERIOD = DEFAULT_QUANT_CONFIG.ma_short_period
MA_LONG_PERIOD = DEFAULT_QUANT_CONFIG.ma_long_period
RSI_DEFAULT_PERIOD = DEFAULT_QUANT_CONFIG.rsi_period
MACD_FAST_PERIOD = DEFAULT_QUANT_CONFIG.macd_fast_period
MACD_SLOW_PERIOD = DEFAULT_QUANT_CONFIG.macd_slow_period
MACD_SIGNAL_PERIOD = DEFAULT_QUANT_CONFIG.macd_signal_period

# Trend Scoring Parameters
TREND_BASE_SCORE = DEFAULT_QUANT_CONFIG.trend_base_score
TREND_MA20_WEIGHT = DEFAULT_QUANT_CONFIG.trend_ma20_weight
TREND_MA50_WEIGHT = DEFAULT_QUANT_CONFIG.trend_ma50_weight
TREND_MA20_VS_MA50_WEIGHT = DEFAULT_QUANT_CONFIG.trend_ma20_vs_ma50_weight

# Momentum (RSI & MACD) Scoring Parameters
MOMENTUM_BASE_SCORE = DEFAULT_QUANT_CONFIG.momentum_base_score

RSI_OVERBOUGHT_EXTREME = DEFAULT_QUANT_CONFIG.rsi_overbought_extreme
RSI_OVERBOUGHT = DEFAULT_QUANT_CONFIG.rsi_overbought
RSI_STRONG_MOMENTUM_LOWER = DEFAULT_QUANT_CONFIG.rsi_strong_momentum_lower
RSI_SAFE_LOWER = DEFAULT_QUANT_CONFIG.rsi_safe_lower
RSI_SAFE_UPPER = DEFAULT_QUANT_CONFIG.rsi_safe_upper
RSI_WEAK_LOWER = DEFAULT_QUANT_CONFIG.rsi_weak_lower

RSI_SCORE_OVERBOUGHT_EXTREME_PENALTY = DEFAULT_QUANT_CONFIG.rsi_score_overbought_extreme_penalty
RSI_SCORE_OVERBOUGHT_PENALTY = DEFAULT_QUANT_CONFIG.rsi_score_overbought_penalty
RSI_SCORE_STRONG_MOMENTUM_BONUS = DEFAULT_QUANT_CONFIG.rsi_score_strong_momentum_bonus
RSI_SCORE_SAFE_BONUS = DEFAULT_QUANT_CONFIG.rsi_score_safe_bonus
RSI_SCORE_WEAK_PENALTY = DEFAULT_QUANT_CONFIG.rsi_score_weak_penalty
RSI_SCORE_OVERSOLD_PENALTY = DEFAULT_QUANT_CONFIG.rsi_score_oversold_penalty

MACD_SCORE_POS_EXPANDING = DEFAULT_QUANT_CONFIG.macd_score_pos_expanding
MACD_SCORE_POS_CONTRACTING = DEFAULT_QUANT_CONFIG.macd_score_pos_contracting
MACD_SCORE_NEG_EXPANDING = DEFAULT_QUANT_CONFIG.macd_score_neg_expanding
MACD_SCORE_NEG_CONTRACTING = DEFAULT_QUANT_CONFIG.macd_score_neg_contracting
MACD_SCORE_POS_SINGLE = DEFAULT_QUANT_CONFIG.macd_score_pos_single
MACD_SCORE_NEG_SINGLE = DEFAULT_QUANT_CONFIG.macd_score_neg_single

# Volume Scoring Parameters
VOLUME_RATIO_VERY_HIGH = DEFAULT_QUANT_CONFIG.volume_ratio_very_high
VOLUME_RATIO_HIGH = DEFAULT_QUANT_CONFIG.volume_ratio_high
VOLUME_RATIO_ABOVE_AVG = DEFAULT_QUANT_CONFIG.volume_ratio_above_avg
VOLUME_RATIO_NORMAL = DEFAULT_QUANT_CONFIG.volume_ratio_normal
VOLUME_RATIO_LOW = DEFAULT_QUANT_CONFIG.volume_ratio_low

VOLUME_SCORE_VERY_HIGH = DEFAULT_QUANT_CONFIG.volume_score_very_high
VOLUME_SCORE_HIGH = DEFAULT_QUANT_CONFIG.volume_score_high
VOLUME_SCORE_ABOVE_AVG = DEFAULT_QUANT_CONFIG.volume_score_above_avg
VOLUME_SCORE_NORMAL = DEFAULT_QUANT_CONFIG.volume_score_normal
VOLUME_SCORE_LOW = DEFAULT_QUANT_CONFIG.volume_score_low
VOLUME_SCORE_VERY_LOW = DEFAULT_QUANT_CONFIG.volume_score_very_low

# Relative Strength vs Benchmark Parameters
RS_DIFF_STRONG_OUTPERFORM = DEFAULT_QUANT_CONFIG.rs_diff_strong_outperform
RS_DIFF_OUTPERFORM = DEFAULT_QUANT_CONFIG.rs_diff_outperform
RS_DIFF_MILD_OUTPERFORM = DEFAULT_QUANT_CONFIG.rs_diff_mild_outperform
RS_DIFF_NEUTRAL = DEFAULT_QUANT_CONFIG.rs_diff_neutral
RS_DIFF_UNDERPERFORM = DEFAULT_QUANT_CONFIG.rs_diff_underperform

RS_SCORE_STRONG_OUTPERFORM = DEFAULT_QUANT_CONFIG.rs_score_strong_outperform
RS_SCORE_OUTPERFORM = DEFAULT_QUANT_CONFIG.rs_score_outperform
RS_SCORE_MILD_OUTPERFORM = DEFAULT_QUANT_CONFIG.rs_score_mild_outperform
RS_SCORE_NEUTRAL = DEFAULT_QUANT_CONFIG.rs_score_neutral
RS_SCORE_UNDERPERFORM = DEFAULT_QUANT_CONFIG.rs_score_underperform
RS_SCORE_STRONG_UNDERPERFORM = DEFAULT_QUANT_CONFIG.rs_score_strong_underperform

# Divergence Scoring Parameters
DIVERGENCE_SCORE_BULLISH = DEFAULT_QUANT_CONFIG.divergence_score_bullish
DIVERGENCE_SCORE_BEARISH = DEFAULT_QUANT_CONFIG.divergence_score_bearish
DIVERGENCE_SCORE_CONFLICT = DEFAULT_QUANT_CONFIG.divergence_score_conflict
DIVERGENCE_SCORE_NEUTRAL = DEFAULT_QUANT_CONFIG.divergence_score_neutral

DIVERGENCE_MIN_HISTORY = DEFAULT_QUANT_CONFIG.divergence_min_history
DIVERGENCE_LOOKBACK_1D = DEFAULT_QUANT_CONFIG.divergence_lookback_1d
DIVERGENCE_LOOKBACK_1W = DEFAULT_QUANT_CONFIG.divergence_lookback_1w
DIVERGENCE_LOOKBACK_1M = DEFAULT_QUANT_CONFIG.divergence_lookback_1m
DIVERGENCE_TROUGH_PRICE_TOLERANCE = DEFAULT_QUANT_CONFIG.divergence_trough_price_tolerance
DIVERGENCE_PEAK_PRICE_TOLERANCE = DEFAULT_QUANT_CONFIG.divergence_peak_price_tolerance
DIVERGENCE_RSI_DELTA = DEFAULT_QUANT_CONFIG.divergence_rsi_delta
DIVERGENCE_MACD_DELTA = DEFAULT_QUANT_CONFIG.divergence_macd_delta
DIVERGENCE_FALLBACK_RSI_DELTA = DEFAULT_QUANT_CONFIG.divergence_fallback_rsi_delta
DIVERGENCE_FALLBACK_RSI_MAX = DEFAULT_QUANT_CONFIG.divergence_fallback_rsi_max

# Confidence Calculation Parameters
CONFIDENCE_MIN = DEFAULT_QUANT_CONFIG.confidence_min
CONFIDENCE_MAX = DEFAULT_QUANT_CONFIG.confidence_max
CONFIDENCE_BASE_SUFFICIENT = DEFAULT_QUANT_CONFIG.confidence_base_sufficient
CONFIDENCE_BASE_PARTIAL = DEFAULT_QUANT_CONFIG.confidence_base_partial

DISPERSION_STD_VERY_LOW = DEFAULT_QUANT_CONFIG.dispersion_std_very_low
DISPERSION_STD_LOW = DEFAULT_QUANT_CONFIG.dispersion_std_low
DISPERSION_STD_HIGH = DEFAULT_QUANT_CONFIG.dispersion_std_high
DISPERSION_STD_MODERATE_HIGH = DEFAULT_QUANT_CONFIG.dispersion_std_moderate_high

CONFIDENCE_ADJ_VERY_LOW_DISPERSION = DEFAULT_QUANT_CONFIG.confidence_adj_very_low_dispersion
CONFIDENCE_ADJ_LOW_DISPERSION = DEFAULT_QUANT_CONFIG.confidence_adj_low_dispersion
CONFIDENCE_ADJ_HIGH_DISPERSION = DEFAULT_QUANT_CONFIG.confidence_adj_high_dispersion
CONFIDENCE_ADJ_MODERATE_HIGH_DISPERSION = (
    DEFAULT_QUANT_CONFIG.confidence_adj_moderate_high_dispersion
)

RISK_VOLATILITY_HIGH = DEFAULT_QUANT_CONFIG.risk_volatility_high
RISK_DRAWDOWN_HIGH = DEFAULT_QUANT_CONFIG.risk_drawdown_high
RISK_VOLATILITY_LOW = DEFAULT_QUANT_CONFIG.risk_volatility_low
RISK_DRAWDOWN_LOW = DEFAULT_QUANT_CONFIG.risk_drawdown_low

CONFIDENCE_ADJ_HIGH_RISK = DEFAULT_QUANT_CONFIG.confidence_adj_high_risk
CONFIDENCE_ADJ_LOW_RISK = DEFAULT_QUANT_CONFIG.confidence_adj_low_risk
CONFIDENCE_ADJ_EXTREME_RSI = DEFAULT_QUANT_CONFIG.confidence_adj_extreme_rsi

# Risk-Adjusted Score Parameters
REGIME_SCORE_FACTORS = DEFAULT_QUANT_CONFIG.regime_score_factors

VOLATILITY_PENALTY_THRESHOLD = DEFAULT_QUANT_CONFIG.volatility_penalty_threshold
VOLATILITY_PENALTY_FACTOR = DEFAULT_QUANT_CONFIG.volatility_penalty_factor
VOLATILITY_PENALTY_MAX = DEFAULT_QUANT_CONFIG.volatility_penalty_max

DRAWDOWN_PENALTY_THRESHOLD = DEFAULT_QUANT_CONFIG.drawdown_penalty_threshold
DRAWDOWN_PENALTY_FACTOR = DEFAULT_QUANT_CONFIG.drawdown_penalty_factor
DRAWDOWN_PENALTY_MAX = DEFAULT_QUANT_CONFIG.drawdown_penalty_max

LIQUIDITY_FACTOR_BASE = DEFAULT_QUANT_CONFIG.liquidity_factor_base
LIQUIDITY_FACTOR_SCALE = DEFAULT_QUANT_CONFIG.liquidity_factor_scale

# Action Classification Parameters
SCORE_THRESHOLD_STRONG_BUY = DEFAULT_QUANT_CONFIG.score_threshold_strong_buy
SCORE_THRESHOLD_BUY = DEFAULT_QUANT_CONFIG.score_threshold_buy
SCORE_THRESHOLD_WATCH = DEFAULT_QUANT_CONFIG.score_threshold_watch
SCORE_THRESHOLD_HOLD = DEFAULT_QUANT_CONFIG.score_threshold_hold
SCORE_THRESHOLD_SELL = DEFAULT_QUANT_CONFIG.score_threshold_sell

REGIMES_STRONG_BUY = set(DEFAULT_QUANT_CONFIG.regimes_strong_buy)
REGIMES_BUY = set(DEFAULT_QUANT_CONFIG.regimes_buy)

# Trade Plan Generation Parameters
TRADE_PLAN_STOP_ATR_MULT = DEFAULT_QUANT_CONFIG.trade_plan_stop_atr_mult
TRADE_PLAN_DEFAULT_STOP_PCT = DEFAULT_QUANT_CONFIG.trade_plan_default_stop_pct
TRADE_PLAN_MA20_STOP_PCT = DEFAULT_QUANT_CONFIG.trade_plan_ma20_stop_pct
TRADE_PLAN_MAX_STOP_PCT = DEFAULT_QUANT_CONFIG.trade_plan_max_stop_pct
TRADE_PLAN_STOP_CLAMP_CAP = DEFAULT_QUANT_CONFIG.trade_plan_stop_clamp_cap
TRADE_PLAN_MIN_RISK_PCT = DEFAULT_QUANT_CONFIG.trade_plan_min_risk_pct
TRADE_PLAN_ENTRY_HIGH_MULT = DEFAULT_QUANT_CONFIG.trade_plan_entry_high_mult
TRADE_PLAN_TP1_RR_MULT = DEFAULT_QUANT_CONFIG.trade_plan_tp1_rr_mult
TRADE_PLAN_TP2_RR_MULT = DEFAULT_QUANT_CONFIG.trade_plan_tp2_rr_mult
TRADE_PLAN_DEFAULT_RR = DEFAULT_QUANT_CONFIG.trade_plan_default_rr
TRADE_PLAN_DEFAULT_STOP_DIST_PCT = DEFAULT_QUANT_CONFIG.trade_plan_default_stop_dist_pct
TRADE_PLAN_PORTFOLIO_RISK_BUDGET_PCT = DEFAULT_QUANT_CONFIG.trade_plan_portfolio_risk_budget_pct
TRADE_PLAN_MAX_POSITION_BUY_PCT = DEFAULT_QUANT_CONFIG.trade_plan_max_position_buy_pct
TRADE_PLAN_MAX_POSITION_WATCH_PCT = DEFAULT_QUANT_CONFIG.trade_plan_max_position_watch_pct

# Market Regime Detection Parameters
REGIME_MIN_HISTORY = DEFAULT_QUANT_CONFIG.regime_min_history
REGIME_BASE_SCORE = DEFAULT_QUANT_CONFIG.regime_base_score

REGIME_TREND_MA20_WEIGHT = DEFAULT_QUANT_CONFIG.regime_trend_ma20_weight
REGIME_TREND_MA50_WEIGHT = DEFAULT_QUANT_CONFIG.regime_trend_ma50_weight

REGIME_RET_20D_STRONG_BULL = DEFAULT_QUANT_CONFIG.regime_ret_20d_strong_bull
REGIME_RET_20D_BULL = DEFAULT_QUANT_CONFIG.regime_ret_20d_bull
REGIME_RET_20D_STRONG_BEAR = DEFAULT_QUANT_CONFIG.regime_ret_20d_strong_bear
REGIME_RET_20D_BEAR = DEFAULT_QUANT_CONFIG.regime_ret_20d_bear

REGIME_RET_20D_STRONG_BULL_SCORE = DEFAULT_QUANT_CONFIG.regime_ret_20d_strong_bull_score
REGIME_RET_20D_BULL_SCORE = DEFAULT_QUANT_CONFIG.regime_ret_20d_bull_score
REGIME_RET_20D_STRONG_BEAR_SCORE = DEFAULT_QUANT_CONFIG.regime_ret_20d_strong_bear_score
REGIME_RET_20D_BEAR_SCORE = DEFAULT_QUANT_CONFIG.regime_ret_20d_bear_score

REGIME_BREADTH_HIGH = DEFAULT_QUANT_CONFIG.regime_breadth_high
REGIME_BREADTH_MED = DEFAULT_QUANT_CONFIG.regime_breadth_med
REGIME_BREADTH_LOW = DEFAULT_QUANT_CONFIG.regime_breadth_low

REGIME_BREADTH_HIGH_SCORE = DEFAULT_QUANT_CONFIG.regime_breadth_high_score
REGIME_BREADTH_MED_SCORE = DEFAULT_QUANT_CONFIG.regime_breadth_med_score
REGIME_BREADTH_LOW_SCORE = DEFAULT_QUANT_CONFIG.regime_breadth_low_score

REGIME_PANIC_VOLATILITY = DEFAULT_QUANT_CONFIG.regime_panic_volatility
REGIME_PANIC_DAILY_DROP_PCT = DEFAULT_QUANT_CONFIG.regime_panic_daily_drop_pct
REGIME_PANIC_PENALTY = DEFAULT_QUANT_CONFIG.regime_panic_penalty

REGIME_THRESHOLD_STRONG_BULL = DEFAULT_QUANT_CONFIG.regime_threshold_strong_bull
REGIME_THRESHOLD_BULL = DEFAULT_QUANT_CONFIG.regime_threshold_bull
REGIME_THRESHOLD_DEFENSIVE = DEFAULT_QUANT_CONFIG.regime_threshold_defensive
REGIME_THRESHOLD_BEAR = DEFAULT_QUANT_CONFIG.regime_threshold_bear

REGIME_CONFIDENCE_SUFFICIENT = DEFAULT_QUANT_CONFIG.regime_confidence_sufficient
REGIME_CONFIDENCE_PARTIAL = DEFAULT_QUANT_CONFIG.regime_confidence_partial
REGIME_CONFIDENCE_HISTORY_THRESHOLD = DEFAULT_QUANT_CONFIG.regime_confidence_history_threshold

# Temporal Data Consistency & Staleness Threshold Parameters
MAX_STOCK_STALENESS_DAYS = 7
MAX_BENCHMARK_FUTURE_DAYS = 0

# Production Update Provider Throttle Configuration
DEFAULT_UPDATE_THROTTLE_DELAY = 3.5

# Data / Model Drift Monitoring Configuration & Threshold Parameters
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

PROVIDER_BUDGET = {
    "max_total_calls": 120,
    "max_duplicate_operations": 5,
    "max_total_elapsed_seconds": 60.0,
}

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
    """Return True if failure category is considered transient/recoverable, False otherwise."""
    return category in RECOVERABLE_FAILURE_CATEGORIES


__all__ = [
    "DEFAULT_QUANT_CONFIG",
    "PIPELINE_VERSION",
    "QUANT_VERSION",
    "QUANT_VERSION_CONTRACT",
    "SCHEMA_VERSION",
    "SIGNAL_MODEL_VERSION",
    "QuantConfig",
]
