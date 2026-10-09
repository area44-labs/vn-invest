"""Feature Engine Module for VN Invest.

Computes technical indicators, moving averages, RSI, MACD, ATR,
relative strength vs benchmark, market structure bounds, and
multi-timeframe divergence (1D, 1W, 1M). Explicitly sets 1H as unavailable
when intraday data is absent.
"""

from collections.abc import Mapping

import pandas as pd

from scripts.quant.config import DEFAULT_QUANT_CONFIG, QuantConfig
from scripts.quant.contracts import FeatureInput, FeatureResult


def calculate_atr(
    df: pd.DataFrame,
    period: int = DEFAULT_QUANT_CONFIG.atr_period,
    config: QuantConfig = DEFAULT_QUANT_CONFIG,
) -> pd.Series:
    """Calculate Average True Range (ATR)."""
    p = period if period != DEFAULT_QUANT_CONFIG.atr_period else config.atr_period
    high, low, close = df["high"], df["low"], df["close"]
    close_prev = close.shift(1)
    tr = pd.concat([high - low, (high - close_prev).abs(), (low - close_prev).abs()], axis=1).max(
        axis=1
    )
    return tr.rolling(window=p, min_periods=1).mean()


def calculate_single_tf_indicators(
    df: pd.DataFrame, config: QuantConfig = DEFAULT_QUANT_CONFIG
) -> pd.DataFrame:
    """Calculate single timeframe indicators (MA20, MA50, RSI, MACD, ATR, Returns)."""
    df_calc = df.copy()
    df_calc["ma20"] = df_calc["close"].rolling(window=config.ma_short_period, min_periods=1).mean()
    df_calc["ma50"] = df_calc["close"].rolling(window=config.ma_long_period, min_periods=1).mean()
    df_calc["vol_ma20"] = (
        df_calc["volume"].rolling(window=config.ma_short_period, min_periods=1).mean()
    )

    delta = df_calc["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=config.rsi_period, min_periods=1).mean()
    avg_loss = loss.rolling(window=config.rsi_period, min_periods=1).mean().replace(0, 0.00001)
    df_calc["rsi"] = (100 - (100 / (1 + (avg_gain / avg_loss)))).fillna(50)

    df_calc["ema12"] = (
        df_calc["close"].ewm(span=config.macd_fast_period, adjust=False, min_periods=1).mean()
    )
    df_calc["ema26"] = (
        df_calc["close"].ewm(span=config.macd_slow_period, adjust=False, min_periods=1).mean()
    )
    df_calc["macd"] = df_calc["ema12"] - df_calc["ema26"]
    df_calc["signal"] = (
        df_calc["macd"].ewm(span=config.macd_signal_period, adjust=False, min_periods=1).mean()
    )
    df_calc["hist"] = df_calc["macd"] - df_calc["signal"]
    df_calc["atr"] = calculate_atr(df_calc, period=config.atr_period, config=config)
    df_calc["daily_return"] = df_calc["close"].pct_change()
    return df_calc


def detect_divergence(
    df: pd.DataFrame,
    lookback: int | None = None,
    config: QuantConfig = DEFAULT_QUANT_CONFIG,
) -> dict:
    """Detect RSI and MACD bullish and bearish divergences."""
    lb = lookback if lookback is not None else config.divergence_lookback_1d
    if len(df) < config.divergence_min_history:
        return {
            "rsi_bullish": False,
            "rsi_bearish": False,
            "macd_bullish": False,
            "macd_bearish": False,
        }

    df_sub = df.tail(lb).reset_index(drop=True)
    n = len(df_sub)

    troughs = []
    peaks = []

    for i in range(2, n - 2):
        if (
            df_sub["low"].iloc[i] <= df_sub["low"].iloc[i - 1]
            and df_sub["low"].iloc[i] <= df_sub["low"].iloc[i - 2]
            and df_sub["low"].iloc[i] <= df_sub["low"].iloc[i + 1]
            and df_sub["low"].iloc[i] <= df_sub["low"].iloc[i + 2]
        ):
            troughs.append(i)
        if (
            df_sub["high"].iloc[i] >= df_sub["high"].iloc[i - 1]
            and df_sub["high"].iloc[i] >= df_sub["high"].iloc[i - 2]
            and df_sub["high"].iloc[i] >= df_sub["high"].iloc[i + 1]
            and df_sub["high"].iloc[i] >= df_sub["high"].iloc[i + 2]
        ):
            peaks.append(i)

    rsi_bullish = False
    macd_bullish = False
    rsi_bearish = False
    macd_bearish = False

    if len(troughs) >= 2:
        t1, t2 = troughs[-2], troughs[-1]
        p1, p2 = df_sub["low"].iloc[t1], df_sub["low"].iloc[t2]
        rsi1, rsi2 = df_sub["rsi"].iloc[t1], df_sub["rsi"].iloc[t2]
        macd1, macd2 = df_sub["hist"].iloc[t1], df_sub["hist"].iloc[t2]

        if (
            p2 <= p1 * config.divergence_trough_price_tolerance
            and rsi2 > rsi1 + config.divergence_rsi_delta
        ):
            rsi_bullish = True
        if (
            p2 <= p1 * config.divergence_trough_price_tolerance
            and macd2 > macd1 + config.divergence_macd_delta
        ):
            macd_bullish = True

    if len(peaks) >= 2:
        pk1, pk2 = peaks[-2], peaks[-1]
        p1, p2 = df_sub["high"].iloc[pk1], df_sub["high"].iloc[pk2]
        rsi1, rsi2 = df_sub["rsi"].iloc[pk1], df_sub["rsi"].iloc[pk2]
        macd1, macd2 = df_sub["hist"].iloc[pk1], df_sub["hist"].iloc[pk2]

        if (
            p2 >= p1 * config.divergence_peak_price_tolerance
            and rsi2 < rsi1 - config.divergence_rsi_delta
        ):
            rsi_bearish = True
        if (
            p2 >= p1 * config.divergence_peak_price_tolerance
            and macd2 < macd1 - config.divergence_macd_delta
        ):
            macd_bearish = True

    last_5 = df_sub.tail(5)
    if (
        not rsi_bullish
        and (last_5["low"].iloc[-1] <= last_5["low"].min())
        and (last_5["rsi"].iloc[-1] > last_5["rsi"].iloc[0] + config.divergence_fallback_rsi_delta)
        and (last_5["rsi"].min() < config.divergence_fallback_rsi_max)
    ):
        rsi_bullish = True

    return {
        "rsi_bullish": rsi_bullish,
        "rsi_bearish": rsi_bearish,
        "macd_bullish": macd_bullish,
        "macd_bearish": macd_bearish,
    }


def calculate_multi_timeframe_features(
    df_daily: pd.DataFrame, config: QuantConfig = DEFAULT_QUANT_CONFIG
) -> tuple[pd.DataFrame, dict]:
    """Perform multi-timeframe feature analysis across 1D, 1W, and 1M.

    Explicitly marks 1H as unavailable when daily EOD data is supplied.
    """
    df_d = calculate_single_tf_indicators(df_daily, config=config)
    div_d = detect_divergence(df_d, lookback=config.divergence_lookback_1d, config=config)

    df_resample = df_d.copy()
    if not isinstance(df_resample.index, pd.DatetimeIndex):
        if "time" in df_resample.columns:
            df_resample["date_dt"] = pd.to_datetime(df_resample["time"])
            df_resample = df_resample.set_index("date_dt")
        elif "date" in df_resample.columns:
            df_resample["date_dt"] = pd.to_datetime(df_resample["date"])
            df_resample = df_resample.set_index("date_dt")

    if not isinstance(df_resample.index, pd.DatetimeIndex):
        df_weekly = df_d
        df_monthly = df_d
    else:
        df_weekly = (
            df_resample.resample("W")
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna()
        )
        df_monthly = (
            df_resample.resample("ME")
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna()
        )

    df_w = calculate_single_tf_indicators(df_weekly, config=config)
    div_w = detect_divergence(df_w, lookback=config.divergence_lookback_1w, config=config)

    df_m = calculate_single_tf_indicators(df_monthly, config=config)
    div_m = detect_divergence(df_m, lookback=config.divergence_lookback_1m, config=config)

    tf_summary = {
        "1h": {
            "available": False,
            "status": "NO_INTRADAY_DATA",
            "divergence": {
                "rsi_bullish": False,
                "rsi_bearish": False,
                "macd_bullish": False,
                "macd_bearish": False,
            },
        },
        "1d": {
            "available": True,
            "rsi": round(float(df_d["rsi"].iloc[-1]), 1) if not df_d.empty else 50.0,
            "macd_hist": round(float(df_d["hist"].iloc[-1]), 3) if not df_d.empty else 0.0,
            "divergence": div_d,
        },
        "1w": {
            "available": True,
            "rsi": round(float(df_w["rsi"].iloc[-1]), 1) if not df_w.empty else 50.0,
            "macd_hist": round(float(df_w["hist"].iloc[-1]), 3) if not df_w.empty else 0.0,
            "divergence": div_w,
        },
        "1m": {
            "available": True,
            "rsi": round(float(df_m["rsi"].iloc[-1]), 1) if not df_m.empty else 50.0,
            "macd_hist": round(float(df_m["hist"].iloc[-1]), 3) if not df_m.empty else 0.0,
            "divergence": div_m,
        },
    }

    return df_d, tf_summary


def compute_market_breadth(
    input_data: FeatureInput
    | Mapping[str, pd.DataFrame]
    | list[pd.DataFrame]
    | tuple[pd.DataFrame, ...],
    candidate_symbols: tuple[str, ...] | list[str] | set[str] | None = None,
    processed_symbols: set[str] | tuple[str, ...] | list[str] | None = None,
    config: QuantConfig = DEFAULT_QUANT_CONFIG,
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
        cfg = input_data.config
    else:
        stock_data_map = input_data
        cfg = config

    bullish_count = 0
    valid_breadth_denom = 0

    if candidate_symbols is not None:
        symbols_to_check = [s for s in candidate_symbols]
    elif isinstance(stock_data_map, Mapping):
        symbols_to_check = list(stock_data_map.keys())
    else:
        symbols_to_check = None

    min_hist = cfg.ma_short_period

    if symbols_to_check is not None:
        processed_set = set(processed_symbols) if processed_symbols is not None else None
        for sym in symbols_to_check:
            if processed_set is not None and sym not in processed_set:
                continue
            df_st = stock_data_map.get(sym) if isinstance(stock_data_map, Mapping) else None
            if df_st is not None and not df_st.empty and len(df_st) >= min_hist:
                valid_breadth_denom += 1
                c = df_st["close"].iloc[-1]
                ma20 = df_st["close"].tail(min_hist).mean()
                if c > ma20:
                    bullish_count += 1
    else:
        dfs = stock_data_map if isinstance(stock_data_map, (list, tuple)) else []
        for df_st in dfs:
            if df_st is not None and not df_st.empty and len(df_st) >= min_hist:
                valid_breadth_denom += 1
                c = df_st["close"].iloc[-1]
                ma20 = df_st["close"].tail(min_hist).mean()
                if c > ma20:
                    bullish_count += 1

    ratio = round(bullish_count / valid_breadth_denom, 2) if valid_breadth_denom > 0 else 0.50
    return FeatureResult(breadth_ratio=ratio)


__all__ = [
    "calculate_atr",
    "calculate_multi_timeframe_features",
    "calculate_single_tf_indicators",
    "compute_market_breadth",
    "detect_divergence",
]
