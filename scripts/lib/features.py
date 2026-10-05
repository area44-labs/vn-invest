"""Feature Engine Module for VN Invest v2.

Backward-compatibility delegation wrapper. Implementation has moved to scripts.quant.features.
"""

from scripts.quant.features import (
    calculate_atr,
    calculate_multi_timeframe_features,
    calculate_single_tf_indicators,
    detect_divergence,
)

__all__ = [
    "calculate_atr",
    "calculate_multi_timeframe_features",
    "calculate_single_tf_indicators",
    "detect_divergence",
]
