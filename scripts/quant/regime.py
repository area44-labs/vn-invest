"""Market regime detection module for VN Invest quant layer."""

from collections.abc import Callable
from typing import Any

import pandas as pd

from scripts.lib.regime import detect_market_regime as lib_detect_market_regime
from scripts.quant.contracts import RegimeInput, RegimeResult


def detect_market_regime(
    input_data: RegimeInput | pd.DataFrame | None = None,
    df_vn30: pd.DataFrame | None = None,
    breadth_ratio: float | None = None,
    detector: Callable[..., dict[str, Any]] | None = None,
) -> RegimeResult:
    """Detect market regime given index datasets and market breadth ratio.

    Accepts RegimeInput or raw position arguments for backward compatibility.
    Returns RegimeResult containing market_regime dictionary.
    """
    if isinstance(input_data, RegimeInput):
        df_vnindex = input_data.df_vnindex
        df_vn30_val = input_data.df_vn30
        breadth_val = input_data.breadth_ratio
    else:
        df_vnindex = input_data
        df_vn30_val = df_vn30
        breadth_val = breadth_ratio

    detect_fn = detector or lib_detect_market_regime
    regime_dict = detect_fn(
        df_vnindex=df_vnindex,
        df_vn30=df_vn30_val,
        breadth_ratio=breadth_val,
    )
    return RegimeResult(market_regime=regime_dict)


__all__ = [
    "detect_market_regime",
]
