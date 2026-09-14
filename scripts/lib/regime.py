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
    if df_vnindex is None or df_vnindex.empty or len(df_vnindex) < 20:
        return {
            "regime": "DEFENSIVE",
            "regime_score": 50.0,
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

    ma20_vn = float(close_vn.tail(20).mean())
    ma50_vn = float(close_vn.tail(50).mean()) if len(close_vn) >= 50 else ma20_vn

    ret_20d = (
        float((latest_vn - close_vn.iloc[-20]) / close_vn.iloc[-20] * 100)
        if len(close_vn) >= 20
        else 0.0
    )

    vol_col = "volume" if "volume" in df_vnindex.columns else None
    if vol_col and len(df_vnindex) >= 20 and df_vnindex[vol_col].tail(20).mean() > 0:
        vol_ratio = float(df_vnindex[vol_col].iloc[-1] / df_vnindex[vol_col].tail(20).mean())
    else:
        vol_ratio = 1.0

    # Volatility 20d std of daily return
    returns_20d = close_vn.pct_change().tail(20)
    vn_volatility = float(returns_20d.std() * (252**0.5)) if len(returns_20d) >= 5 else 0.15

    # VN30 metrics
    vn30_change_pct = None
    if df_vn30 is not None and not df_vn30.empty and len(df_vn30) >= 2:
        c30 = df_vn30["close"]
        vn30_change_pct = float((c30.iloc[-1] - c30.iloc[-2]) / c30.iloc[-2] * 100)

    # Multi-factor score calculation (0 - 100)
    score = 50.0

    # Trend component (+/- 25)
    if latest_vn > ma20_vn:
        score += 15.0
    else:
        score -= 15.0

    if latest_vn > ma50_vn:
        score += 10.0
    else:
        score -= 10.0

    # Momentum component (+/- 15)
    if ret_20d > 5.0:
        score += 15.0
    elif ret_20d > 1.0:
        score += 8.0
    elif ret_20d < -5.0:
        score -= 15.0
    elif ret_20d < -1.0:
        score -= 8.0

    # Market breadth (+/- 10)
    if breadth_ratio is not None:
        if breadth_ratio >= 0.65:
            score += 10.0
        elif breadth_ratio >= 0.50:
            score += 5.0
        elif breadth_ratio <= 0.35:
            score -= 10.0

    # Volatility / Panic penalty (-15)
    if vn_volatility > 0.35 or vn_change_pct < -3.0:
        score -= 15.0

    score = max(0.0, min(100.0, round(score, 1)))

    # Classification
    if score >= 80.0:
        regime = "STRONG_BULL"
    elif score >= 60.0:
        regime = "BULL"
    elif score >= 40.0:
        regime = "DEFENSIVE"
    elif score >= 20.0:
        regime = "BEAR"
    else:
        regime = "PANIC"

    confidence = 0.85 if len(df_vnindex) >= 50 else 0.60

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
