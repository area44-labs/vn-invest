"""Market Regime Module for VN Invest v2.

Determines multi-factor Vietnam market regime:
STRONG_BULL, BULL, DEFENSIVE, BEAR, PANIC
Evaluating VNINDEX, VN30, breadth, volatility, volume, and momentum.

Invariant:
All quantitative consumers must receive clean OHLCV data.
Raw provider data may be retained for diagnostics only.
"""

import logging

import pandas as pd

from scripts.lib import config

logger = logging.getLogger(__name__)


def detect_market_regime(
    df_vnindex: pd.DataFrame | None = None,
    df_vn30: pd.DataFrame | None = None,
    breadth_ratio: float | None = None,
) -> dict:
    """Evaluate multi-factor Vietnam market regime.

    Expects clean benchmark DataFrames (df_vnindex, df_vn30).
    Returns dict containing regime, regime_score, confidence, and metrics.
    """
    if df_vnindex is None or df_vnindex.empty or len(df_vnindex) < config.REGIME_MIN_HISTORY:
        return {
            "regime": "DEFENSIVE",
            "regime_score": config.REGIME_BASE_SCORE,
            "confidence": 0.40,
            "metrics": {
                "vnindex_value": None,
                "vnindex_change_pct": None,
                "vn30_change_pct": None,
                "market_breadth_ratio": breadth_ratio,
                "volatility": None,
                "volume_20d_ratio": None,
            },
        }

    close_vn = df_vnindex["close"]
    latest_vn = float(close_vn.iloc[-1])
    prev_vn = float(close_vn.iloc[-2]) if len(close_vn) >= 2 else latest_vn
    vn_change_pct = float((latest_vn - prev_vn) / prev_vn * 100) if prev_vn > 0 else 0.0

    ma20_vn = float(close_vn.tail(config.MA_SHORT_PERIOD).mean())
    ma50_vn = (
        float(close_vn.tail(config.MA_LONG_PERIOD).mean())
        if len(close_vn) >= config.MA_LONG_PERIOD
        else ma20_vn
    )

    ret_20d = (
        float(
            (latest_vn - close_vn.iloc[-config.MA_SHORT_PERIOD])
            / close_vn.iloc[-config.MA_SHORT_PERIOD]
            * 100
        )
        if len(close_vn) >= config.MA_SHORT_PERIOD
        else 0.0
    )

    vol_col = "volume" if "volume" in df_vnindex.columns else None
    if (
        vol_col
        and len(df_vnindex) >= config.MA_SHORT_PERIOD
        and df_vnindex[vol_col].tail(config.MA_SHORT_PERIOD).mean() > 0
    ):
        vol_ratio = float(
            df_vnindex[vol_col].iloc[-1] / df_vnindex[vol_col].tail(config.MA_SHORT_PERIOD).mean()
        )
    else:
        vol_ratio = 1.0

    # Volatility 20d std of daily return
    returns_20d = close_vn.pct_change().tail(config.MA_SHORT_PERIOD)
    vn_volatility = float(returns_20d.std() * (252**0.5)) if len(returns_20d) >= 5 else 0.15

    # VN30 metrics
    vn30_change_pct = None
    if df_vn30 is not None and not df_vn30.empty and len(df_vn30) >= 2:
        c30 = df_vn30["close"]
        vn30_change_pct = float((c30.iloc[-1] - c30.iloc[-2]) / c30.iloc[-2] * 100)

    # Multi-factor score calculation (0 - 100)
    score = config.REGIME_BASE_SCORE

    # Trend component (+/- 25)
    if latest_vn > ma20_vn:
        score += config.REGIME_TREND_MA20_WEIGHT
    else:
        score -= config.REGIME_TREND_MA20_WEIGHT

    if latest_vn > ma50_vn:
        score += config.REGIME_TREND_MA50_WEIGHT
    else:
        score -= config.REGIME_TREND_MA50_WEIGHT

    # Momentum component (+/- 15)
    if ret_20d > config.REGIME_RET_20D_STRONG_BULL:
        score += config.REGIME_RET_20D_STRONG_BULL_SCORE
    elif ret_20d > config.REGIME_RET_20D_BULL:
        score += config.REGIME_RET_20D_BULL_SCORE
    elif ret_20d < config.REGIME_RET_20D_STRONG_BEAR:
        score += config.REGIME_RET_20D_STRONG_BEAR_SCORE
    elif ret_20d < config.REGIME_RET_20D_BEAR:
        score += config.REGIME_RET_20D_BEAR_SCORE

    # Market breadth (+/- 10)
    if breadth_ratio is not None:
        if breadth_ratio >= config.REGIME_BREADTH_HIGH:
            score += config.REGIME_BREADTH_HIGH_SCORE
        elif breadth_ratio >= config.REGIME_BREADTH_MED:
            score += config.REGIME_BREADTH_MED_SCORE
        elif breadth_ratio <= config.REGIME_BREADTH_LOW:
            score += config.REGIME_BREADTH_LOW_SCORE

    # Volatility / Panic penalty (-15)
    if (
        vn_volatility > config.REGIME_PANIC_VOLATILITY
        or vn_change_pct < config.REGIME_PANIC_DAILY_DROP_PCT
    ):
        score += config.REGIME_PANIC_PENALTY

    score = max(0.0, min(100.0, round(score, 1)))

    # Classification
    if score >= config.REGIME_THRESHOLD_STRONG_BULL:
        regime = "STRONG_BULL"
    elif score >= config.REGIME_THRESHOLD_BULL:
        regime = "BULL"
    elif score >= config.REGIME_THRESHOLD_DEFENSIVE:
        regime = "DEFENSIVE"
    elif score >= config.REGIME_THRESHOLD_BEAR:
        regime = "BEAR"
    else:
        regime = "PANIC"

    confidence = (
        config.REGIME_CONFIDENCE_SUFFICIENT
        if len(df_vnindex) >= config.REGIME_CONFIDENCE_HISTORY_THRESHOLD
        else config.REGIME_CONFIDENCE_PARTIAL
    )

    return {
        "regime": regime,
        "regime_score": score,
        "confidence": confidence,
        "metrics": {
            "vnindex_value": round(latest_vn, 2),
            "vnindex_change_pct": round(vn_change_pct, 2),
            "vn30_change_pct": (round(vn30_change_pct, 2) if vn30_change_pct is not None else None),
            "market_breadth_ratio": (
                round(breadth_ratio, 2) if breadth_ratio is not None else None
            ),
            "volatility": round(vn_volatility, 4),
            "volume_20d_ratio": round(vol_ratio, 2),
        },
    }
