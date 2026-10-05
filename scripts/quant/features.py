"""Feature and indicator calculation module for VN Invest quant layer."""

from collections.abc import Mapping

import pandas as pd

from scripts.lib.features import calculate_multi_timeframe_features
from scripts.quant.contracts import FeatureInput, FeatureResult


def compute_market_breadth(
    input_data: FeatureInput
    | Mapping[str, pd.DataFrame]
    | list[pd.DataFrame]
    | tuple[pd.DataFrame, ...],
    candidate_symbols: tuple[str, ...] | list[str] | set[str] | None = None,
    processed_symbols: set[str] | tuple[str, ...] | list[str] | None = None,
) -> FeatureResult:
    """Compute market breadth ratio across given stock datasets.

    Breadth ratio = (stocks with close > MA20) / (stocks with >= 20 sessions).
    Returns 0.50 default if zero valid stocks are available.
    Returns FeatureResult containing breadth_ratio.
    """
    if isinstance(input_data, FeatureInput):
        stock_data_map = input_data.stock_data_map
        candidate_symbols = input_data.candidate_symbols
        processed_symbols = input_data.processed_symbols
    else:
        stock_data_map = input_data

    bullish_count = 0
    valid_breadth_denom = 0

    if candidate_symbols is not None:
        symbols_to_check = [s for s in candidate_symbols]
    elif isinstance(stock_data_map, Mapping):
        symbols_to_check = list(stock_data_map.keys())
    else:
        symbols_to_check = None

    if symbols_to_check is not None:
        processed_set = set(processed_symbols) if processed_symbols is not None else None
        for sym in symbols_to_check:
            if processed_set is not None and sym not in processed_set:
                continue
            df_st = stock_data_map.get(sym) if isinstance(stock_data_map, Mapping) else None
            if df_st is not None and not df_st.empty and len(df_st) >= 20:
                valid_breadth_denom += 1
                c = df_st["close"].iloc[-1]
                ma20 = df_st["close"].tail(20).mean()
                if c > ma20:
                    bullish_count += 1
    else:
        dfs = stock_data_map if isinstance(stock_data_map, (list, tuple)) else []
        for df_st in dfs:
            if df_st is not None and not df_st.empty and len(df_st) >= 20:
                valid_breadth_denom += 1
                c = df_st["close"].iloc[-1]
                ma20 = df_st["close"].tail(20).mean()
                if c > ma20:
                    bullish_count += 1

    ratio = round(bullish_count / valid_breadth_denom, 2) if valid_breadth_denom > 0 else 0.50
    return FeatureResult(breadth_ratio=ratio)


__all__ = [
    "calculate_multi_timeframe_features",
    "compute_market_breadth",
]
