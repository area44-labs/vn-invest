"""Market analysis engine for VN Invest.

Pure quantitative calculation engine for market breadth ratio and multi-factor market regime detection.
Does not perform I/O, network requests, or database state updates.
"""

from collections.abc import Callable, Mapping
from typing import Any

import pandas as pd

from scripts.engine.contracts import MarketAnalysisInput, MarketAnalysisResult
from scripts.lib.regime import detect_market_regime


def compute_market_breadth(
    stock_data_map: Mapping[str, pd.DataFrame] | list[pd.DataFrame] | tuple[pd.DataFrame, ...],
    candidate_symbols: tuple[str, ...] | list[str] | set[str] | None = None,
    processed_symbols: set[str] | tuple[str, ...] | list[str] | None = None,
) -> float:
    """Compute market breadth ratio across given stock datasets.

    Breadth ratio = (stocks with close > MA20) / (stocks with >= 20 sessions).
    Returns 0.50 default if zero valid stocks are available.
    """
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

    return round(bullish_count / valid_breadth_denom, 2) if valid_breadth_denom > 0 else 0.50


class MarketAnalysisEngine:
    """Quantitative engine for market breadth and regime detection."""

    @staticmethod
    def analyze(
        input_data: MarketAnalysisInput,
        regime_detector: Callable[..., dict[str, Any]] | None = None,
    ) -> MarketAnalysisResult:
        """Analyze market condition to return market breadth ratio and market regime dict."""
        breadth = compute_market_breadth(
            stock_data_map=input_data.stock_data_map,
            candidate_symbols=input_data.candidate_symbols,
            processed_symbols=input_data.processed_symbols,
        )

        df_vn30_input = input_data.df_vn30 if input_data.vn30_sufficient else None

        detector = regime_detector or detect_market_regime

        regime_dict = detector(
            df_vnindex=input_data.df_vnindex,
            df_vn30=df_vn30_input,
            breadth_ratio=breadth,
        )

        return MarketAnalysisResult(
            breadth_ratio=breadth,
            market_regime=regime_dict,
        )


__all__ = [
    "MarketAnalysisEngine",
    "compute_market_breadth",
]
