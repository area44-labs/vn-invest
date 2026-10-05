"""VN Invest Signal Engine v2.0.

Backward-compatibility delegation wrapper. Implementation has moved to scripts.quant.*.
"""

from scripts.quant.recommendation import (
    generate_single_recommendation as generate_recommendation,
)
from scripts.quant.risk import (
    calculate_confidence,
    calculate_risk_adjusted_score,
)
from scripts.quant.signal import (
    DIVERGENCE_TIMEFRAME_WEIGHTS,
    SIGNAL_MODEL_VERSION,
    SIGNAL_WEIGHTS,
    VALID_MARKET_REGIMES,
    _safe_float,
    calculate_divergence_score,
    calculate_momentum_score,
    calculate_relative_strength_score,
    calculate_signal_score,
    calculate_trend_score,
    calculate_volume_score,
    classify_action,
    format_vnd,
)

__all__ = [
    "DIVERGENCE_TIMEFRAME_WEIGHTS",
    "SIGNAL_MODEL_VERSION",
    "SIGNAL_WEIGHTS",
    "VALID_MARKET_REGIMES",
    "_safe_float",
    "calculate_confidence",
    "calculate_divergence_score",
    "calculate_momentum_score",
    "calculate_relative_strength_score",
    "calculate_risk_adjusted_score",
    "calculate_signal_score",
    "calculate_trend_score",
    "calculate_volume_score",
    "classify_action",
    "format_vnd",
    "generate_recommendation",
]
