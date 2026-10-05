"""Market Regime Module for VN Invest v2.

Backward-compatibility delegation wrapper. Implementation has moved to scripts.quant.regime.
"""

from scripts.quant.regime import lib_detect_market_regime as detect_market_regime

__all__ = [
    "detect_market_regime",
]
