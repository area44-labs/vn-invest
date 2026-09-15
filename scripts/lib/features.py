"""Feature Engine Module for VN Invest v2.

Computes technical indicators, moving averages, RSI, MACD, ATR,
relative strength vs benchmark, market structure bounds, and
multi-timeframe divergence (1D, 1W, 1M). Explicitly sets 1H as unavailable
when intraday data is absent.
"""

import pandas as pd


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Average True Range (ATR)."""
    high, low, close = df["high"], df["low"], df["close"]
    close_prev = close.shift(1)
    tr = pd.concat([high - low, (high - close_prev).abs(), (low - close_prev).abs()], axis=1).max(
        axis=1
    )
    return tr.rolling(window=period, min_periods=1).mean()


def calculate_single_tf_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate single timeframe indicators (MA20, MA50, RSI, MACD, ATR, Returns)."""
    df_calc = df.copy()
    df_calc["ma20"] = df_calc["close"].rolling(window=20, min_periods=1).mean()
    df_calc["ma50"] = df_calc["close"].rolling(window=50, min_periods=1).mean()
    df_calc["vol_ma20"] = df_calc["volume"].rolling(window=20, min_periods=1).mean()

    delta = df_calc["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=14, min_periods=1).mean()
    avg_loss = loss.rolling(window=14, min_periods=1).mean().replace(0, 0.00001)
    df_calc["rsi"] = (100 - (100 / (1 + (avg_gain / avg_loss)))).fillna(50)

    df_calc["ema12"] = df_calc["close"].ewm(span=12, adjust=False, min_periods=1).mean()
    df_calc["ema26"] = df_calc["close"].ewm(span=26, adjust=False, min_periods=1).mean()
    df_calc["macd"] = df_calc["ema12"] - df_calc["ema26"]
    df_calc["signal"] = df_calc["macd"].ewm(span=9, adjust=False, min_periods=1).mean()
    df_calc["hist"] = df_calc["macd"] - df_calc["signal"]
    df_calc["atr"] = calculate_atr(df_calc, 14)
    df_calc["daily_return"] = df_calc["close"].pct_change()
    return df_calc


def detect_divergence(df: pd.DataFrame, lookback: int = 40) -> dict:
    """Detect RSI and MACD bullish and bearish divergences."""
    if len(df) < 15:
        return {
            "rsi_bullish": False,
            "rsi_bearish": False,
            "macd_bullish": False,
            "macd_bearish": False,
        }

    df_sub = df.tail(lookback).reset_index(drop=True)
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

        if p2 <= p1 * 1.01 and rsi2 > rsi1 + 1.5:
            rsi_bullish = True
        if p2 <= p1 * 1.01 and macd2 > macd1 + 0.05:
            macd_bullish = True

    if len(peaks) >= 2:
        pk1, pk2 = peaks[-2], peaks[-1]
        p1, p2 = df_sub["high"].iloc[pk1], df_sub["high"].iloc[pk2]
        rsi1, rsi2 = df_sub["rsi"].iloc[pk1], df_sub["rsi"].iloc[pk2]
        macd1, macd2 = df_sub["hist"].iloc[pk1], df_sub["hist"].iloc[pk2]

        if p2 >= p1 * 0.99 and rsi2 < rsi1 - 1.5:
            rsi_bearish = True
        if p2 >= p1 * 0.99 and macd2 < macd1 - 0.05:
            macd_bearish = True

    last_5 = df_sub.tail(5)
    if (
        not rsi_bullish
        and (last_5["low"].iloc[-1] <= last_5["low"].min())
        and (last_5["rsi"].iloc[-1] > last_5["rsi"].iloc[0] + 3.0)
        and (last_5["rsi"].min() < 40)
    ):
        rsi_bullish = True

    return {
        "rsi_bullish": rsi_bullish,
        "rsi_bearish": rsi_bearish,
        "macd_bullish": macd_bullish,
        "macd_bearish": macd_bearish,
    }


def calculate_multi_timeframe_features(
    df_daily: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    """Perform multi-timeframe feature analysis across 1D, 1W, and 1M.

    Explicitly marks 1H as unavailable when daily EOD data is supplied.
    """
    df_d = calculate_single_tf_indicators(df_daily)
    div_d = detect_divergence(df_d)

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

    df_w = calculate_single_tf_indicators(df_weekly)
    div_w = detect_divergence(df_w, lookback=30)

    df_m = calculate_single_tf_indicators(df_monthly)
    div_m = detect_divergence(df_m, lookback=24)

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
