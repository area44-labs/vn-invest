"""Market Regime Module for VN Invest v2.

Determines multi-factor Vietnam market regime:
STRONG_BULL, BULL, DEFENSIVE, BEAR, PANIC
Evaluating VNINDEX, VN30, breadth, volatility, volume, and momentum.

Invariant:
All quantitative consumers must receive clean OHLCV data.
Raw provider data may be retained for diagnostics only.
"""

import logging
import math
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from scripts.quant.config import DEFAULT_QUANT_CONFIG, QuantConfig
from scripts.quant.contracts import RegimeInput, RegimeResult

logger = logging.getLogger(__name__)


def _safe_breadth_ratio(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return None
        if 0.0 <= f <= 1.0:
            return f
        return None
    except ValueError, TypeError:
        return None


def _detect_market_regime(
    df_vnindex: pd.DataFrame | None = None,
    df_vn30: pd.DataFrame | None = None,
    breadth_ratio: float | None = None,
    config: QuantConfig = DEFAULT_QUANT_CONFIG,
) -> dict:
    """Internal calculation helper for multi-factor Vietnam market regime evaluation.

    Validates benchmark DataFrames and breadth_ratio safely.
    Returns dict containing regime, regime_score, confidence, and metrics.
    """
    safe_breadth = _safe_breadth_ratio(breadth_ratio)

    default_defensive = {
        "regime": "DEFENSIVE",
        "regime_score": config.regime_base_score,
        "confidence": config.regime_confidence_insufficient,
        "metrics": {
            "vnindex_value": None,
            "vnindex_change_pct": None,
            "vn30_change_pct": None,
            "market_breadth_ratio": safe_breadth,
            "volatility": None,
            "volume_20d_ratio": None,
        },
    }

    if (
        df_vnindex is None
        or df_vnindex.empty
        or len(df_vnindex) < config.regime_min_history
        or "close" not in df_vnindex.columns
    ):
        return default_defensive

    # Clean check: ensure no NaN/Inf/non-positive values in close
    close_series = pd.to_numeric(df_vnindex["close"], errors="coerce")
    if (
        close_series.isna().any()
        or np.isinf(close_series.to_numpy()).any()
        or (close_series <= 0).any()
    ):
        return default_defensive

    close_vn = close_series
    latest_vn = float(close_vn.iloc[-1])
    prev_vn = float(close_vn.iloc[-2]) if len(close_vn) >= 2 else latest_vn
    vn_change_pct = float((latest_vn - prev_vn) / prev_vn * 100) if prev_vn > 0 else 0.0

    ma20_vn = float(close_vn.tail(config.ma_short_period).mean())
    ma50_vn = (
        float(close_vn.tail(config.ma_long_period).mean())
        if len(close_vn) >= config.ma_long_period
        else ma20_vn
    )

    ret_20d = (
        float(
            (latest_vn - close_vn.iloc[-config.ma_short_period])
            / close_vn.iloc[-config.ma_short_period]
            * 100
        )
        if len(close_vn) >= config.ma_short_period
        else 0.0
    )

    vol_ratio = None
    if "volume" in df_vnindex.columns and len(df_vnindex) >= config.ma_short_period:
        vol_series = pd.to_numeric(df_vnindex["volume"], errors="coerce")
        if (
            not vol_series.isna().any()
            and not np.isinf(vol_series.to_numpy()).any()
            and (vol_series >= 0).all()
        ):
            mean_20_vol = float(vol_series.tail(config.ma_short_period).mean())
            if mean_20_vol > 0:
                latest_vol = float(vol_series.iloc[-1])
                vol_ratio = round(latest_vol / mean_20_vol, 2)

    # Volatility 20d std of daily return
    returns_20d = close_vn.pct_change().tail(config.ma_short_period)
    vn_volatility = float(returns_20d.std() * (252**0.5)) if len(returns_20d) >= 5 else 0.15

    # VN30 metrics
    vn30_change_pct = None
    if (
        df_vn30 is not None
        and not df_vn30.empty
        and len(df_vn30) >= 2
        and "close" in df_vn30.columns
    ):
        c30_series = pd.to_numeric(df_vn30["close"], errors="coerce")
        if (
            not c30_series.isna().any()
            and not np.isinf(c30_series.to_numpy()).any()
            and (c30_series > 0).all()
        ):
            vn30_change_pct = float(
                (c30_series.iloc[-1] - c30_series.iloc[-2]) / c30_series.iloc[-2] * 100
            )

    # Multi-factor score calculation (0 - 100)
    score = config.regime_base_score

    # Trend component (+/- 25)
    if latest_vn > ma20_vn:
        score += config.regime_trend_ma20_weight
    else:
        score -= config.regime_trend_ma20_weight

    if latest_vn > ma50_vn:
        score += config.regime_trend_ma50_weight
    else:
        score -= config.regime_trend_ma50_weight

    # Momentum component (+/- 15)
    if ret_20d > config.regime_ret_20d_strong_bull:
        score += config.regime_ret_20d_strong_bull_score
    elif ret_20d > config.regime_ret_20d_bull:
        score += config.regime_ret_20d_bull_score
    elif ret_20d < config.regime_ret_20d_strong_bear:
        score += config.regime_ret_20d_strong_bear_score
    elif ret_20d < config.regime_ret_20d_bear:
        score += config.regime_ret_20d_bear_score

    # Market breadth (+/- 10)
    if safe_breadth is not None:
        if safe_breadth >= config.regime_breadth_high:
            score += config.regime_breadth_high_score
        elif safe_breadth >= config.regime_breadth_med:
            score += config.regime_breadth_med_score
        elif safe_breadth <= config.regime_breadth_low:
            score += config.regime_breadth_low_score

    # Volatility / Panic penalty (-15)
    if (
        vn_volatility > config.regime_panic_volatility
        or vn_change_pct < config.regime_panic_daily_drop_pct
    ):
        score += config.regime_panic_penalty

    score = max(0.0, min(100.0, round(score, 1)))

    # Classification
    if score >= config.regime_threshold_strong_bull:
        regime = "STRONG_BULL"
    elif score >= config.regime_threshold_bull:
        regime = "BULL"
    elif score >= config.regime_threshold_defensive:
        regime = "DEFENSIVE"
    elif score >= config.regime_threshold_bear:
        regime = "BEAR"
    else:
        regime = "PANIC"

    confidence = (
        config.regime_confidence_sufficient
        if len(df_vnindex) >= config.regime_confidence_history_threshold
        else config.regime_confidence_partial
    )

    return {
        "regime": regime,
        "regime_score": score,
        "confidence": confidence,
        "metrics": {
            "vnindex_value": round(latest_vn, 2),
            "vnindex_change_pct": round(vn_change_pct, 2),
            "vn30_change_pct": (round(vn30_change_pct, 2) if vn30_change_pct is not None else None),
            "market_breadth_ratio": (round(safe_breadth, 2) if safe_breadth is not None else None),
            "volatility": round(vn_volatility, 4),
            "volume_20d_ratio": vol_ratio,
        },
    }


def detect_market_regime(
    input_data: RegimeInput | pd.DataFrame | None = None,
    df_vn30: pd.DataFrame | None = None,
    breadth_ratio: float | None = None,
    detector: Callable[..., dict[str, Any]] | None = None,
    config: QuantConfig = DEFAULT_QUANT_CONFIG,
    df_vnindex: pd.DataFrame | None = None,
) -> RegimeResult | dict:
    """Detect market regime given index datasets and market breadth ratio.

    Accepts RegimeInput or raw position/keyword arguments.
    Returns RegimeResult when passed RegimeInput, or dict when passed raw arguments.
    """
    if isinstance(input_data, RegimeInput):
        df_vnindex_val = input_data.df_vnindex
        df_vn30_val = input_data.df_vn30
        breadth_val = input_data.breadth_ratio
        cfg = input_data.config
        is_typed = True
    else:
        df_vnindex_val = input_data if input_data is not None else df_vnindex
        df_vn30_val = df_vn30
        breadth_val = breadth_ratio
        cfg = config
        is_typed = False

    if detector is not None:
        regime_dict = detector(
            df_vnindex=df_vnindex_val,
            df_vn30=df_vn30_val,
            breadth_ratio=breadth_val,
        )
    else:
        regime_dict = _detect_market_regime(
            df_vnindex=df_vnindex_val,
            df_vn30=df_vn30_val,
            breadth_ratio=breadth_val,
            config=cfg,
        )

    if is_typed:
        return RegimeResult(market_regime=regime_dict)
    return regime_dict


__all__ = [
    "detect_market_regime",
]
