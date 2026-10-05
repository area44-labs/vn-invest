"""VN Invest Signal Engine v2.0.

Generates stock recommendations based on composite deterministic technical signal score,
market regime, T+2.5 risk horizon, market structure entry/stop/target bounds,
and risk-based position sizing.
Allowed actions: BUY, WATCH, HOLD, SELL, AVOID.
Strictly avoids unverified heuristics for expected returns.
All stock price values are converted and displayed in full VND units (e.g. 33,630 VND).

Invariant:
All quantitative consumers must receive clean OHLCV data.
Raw provider data may be retained for diagnostics only.
"""

import math

from scripts.domain import Recommendation, RiskAssessment, TradePlan
from scripts.lib.features import calculate_multi_timeframe_features
from scripts.lib.risk import calculate_t25_risk_metrics
from scripts.lib.vietnam_market import (
    clamp_price_limits,
    extract_latest_trading_date,
    get_clean_ohlcv_data,
    round_tick_size,
    validate_ohlcv_data,
)

SIGNAL_MODEL_VERSION = "2.0"

# Centralized component weights for VN Invest Signal Engine.
SIGNAL_WEIGHTS = {
    "trend": 0.30,
    "momentum": 0.25,
    "volume": 0.15,
    "relative_strength": 0.15,
    "divergence": 0.15,
}

DIVERGENCE_TIMEFRAME_WEIGHTS = {
    "1D": 0.50,
    "1W": 0.30,
    "1M": 0.20,
}

VALID_MARKET_REGIMES = {
    "STRONG_BULL",
    "BULL",
    "NEUTRAL",
    "DEFENSIVE",
    "BEAR",
    "PANIC",
}


def format_vnd(price: float) -> str:
    """Format numeric price (in VND/share) into full VND string (e.g. 33630 -> '33.630')."""
    return f"{price:,.0f}".replace(",", ".")


def _safe_float(val) -> float | None:
    """Safely convert value to float, returning None if None, NaN, or Inf."""
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except ValueError, TypeError:
        return None


def calculate_trend_score(
    raw_close: float | None,
    raw_ma20: float | None,
    raw_ma50: float | None,
) -> float | None:
    """Calculate Trend Score (0 to 100). Returns None if essential inputs are missing."""
    c = _safe_float(raw_close)
    ma20 = _safe_float(raw_ma20)
    ma50 = _safe_float(raw_ma50)

    if c is None or c <= 0 or (ma20 is None and ma50 is None):
        return None

    score = 50.0

    if ma20 is not None and ma20 > 0:
        if c > ma20:
            score += 25.0
        else:
            score -= 25.0

    if ma50 is not None and ma50 > 0:
        if c > ma50:
            score += 15.0
        else:
            score -= 15.0

    if ma20 is not None and ma50 is not None and ma20 > 0 and ma50 > 0:
        if ma20 > ma50:
            score += 10.0
        else:
            score -= 10.0

    return max(0.0, min(100.0, round(score, 1)))


def calculate_momentum_score(
    rsi: float | None,
    macd_hist: float | None,
    prev_macd_hist: float | None,
) -> float | None:
    """Calculate Momentum Score (0 to 100). Returns None if essential inputs are missing."""
    r = _safe_float(rsi)
    hist = _safe_float(macd_hist)
    prev_hist = _safe_float(prev_macd_hist)

    if r is None and hist is None:
        return None

    score = 50.0

    if r is not None:
        if r > 78.0:
            score -= 25.0
        elif r > 70.0:
            score -= 15.0
        elif 65.0 < r <= 70.0:
            score += 10.0
        elif 45.0 <= r <= 65.0:
            score += 20.0
        elif 35.0 <= r < 45.0:
            score -= 10.0
        elif r < 35.0:
            score -= 20.0

    if hist is not None:
        if prev_hist is not None:
            if hist > 0 and hist > prev_hist:
                score += 25.0
            elif hist > 0 and hist <= prev_hist:
                score += 10.0
            elif hist < 0 and hist < prev_hist:
                score -= 25.0
            elif hist < 0 and hist >= prev_hist:
                score -= 10.0
        else:
            if hist > 0:
                score += 15.0
            elif hist < 0:
                score -= 15.0

    return max(0.0, min(100.0, round(score, 1)))


def calculate_volume_score(volume_ratio: float | None) -> float | None:
    """Calculate Volume Score (0 to 100). Returns None if essential inputs are missing."""
    vr = _safe_float(volume_ratio)
    if vr is None or vr <= 0:
        return None

    if vr >= 2.0:
        score = 100.0
    elif vr >= 1.5:
        score = 85.0
    elif vr >= 1.2:
        score = 70.0
    elif vr >= 0.8:
        score = 50.0
    elif vr >= 0.5:
        score = 35.0
    else:
        score = 20.0

    return max(0.0, min(100.0, round(score, 1)))


def calculate_relative_strength_score(rs_diff: float | None) -> float | None:
    """Calculate Relative Strength Score (0 to 100) vs VN-Index benchmark."""
    diff = _safe_float(rs_diff)
    if diff is None:
        return None

    if diff >= 0.10:
        score = 100.0
    elif diff >= 0.05:
        score = 80.0
    elif diff >= 0.02:
        score = 65.0
    elif diff >= -0.02:
        score = 50.0
    elif diff >= -0.05:
        score = 35.0
    else:
        score = 15.0

    return max(0.0, min(100.0, round(score, 1)))


def calculate_divergence_score(tf_summary: dict | None) -> float | None:
    """Calculate Timeframe-Weighted Divergence Score (0 to 100)."""
    if not tf_summary or not isinstance(tf_summary, dict):
        return None

    tf_map = [("1d", "1D"), ("1w", "1W"), ("1m", "1M")]
    available_tfs = []

    for tf_key, tf_label in tf_map:
        tf_info = tf_summary.get(tf_key)
        if tf_info and isinstance(tf_info, dict) and tf_info.get("available", False):
            available_tfs.append((tf_label, tf_info.get("divergence", {})))

    if not available_tfs:
        return None

    total_tf_weight = sum(DIVERGENCE_TIMEFRAME_WEIGHTS[lbl] for lbl, _ in available_tfs)
    if total_tf_weight <= 0:
        return None

    tf_scores = []
    for tf_label, div in available_tfs:
        bullish = bool(div.get("rsi_bullish") or div.get("macd_bullish"))
        bearish = bool(div.get("rsi_bearish") or div.get("macd_bearish"))

        if bullish and not bearish:
            tf_score = 90.0
        elif bearish and not bullish:
            tf_score = 10.0
        elif bullish and bearish:
            tf_score = 40.0
        else:
            tf_score = 50.0

        weight = DIVERGENCE_TIMEFRAME_WEIGHTS[tf_label] / total_tf_weight
        tf_scores.append(tf_score * weight)

    final_div_score = sum(tf_scores)
    return max(0.0, min(100.0, round(final_div_score, 1)))


def calculate_signal_score(
    trend_score: float | None,
    momentum_score: float | None,
    volume_score: float | None,
    relative_strength_score: float | None,
    divergence_score: float | None,
) -> tuple[float | None, dict[str, float | None], str]:
    """Combine component scores into final deterministic signal_score (0 to 100)."""
    components = {
        "trend": trend_score,
        "momentum": momentum_score,
        "volume": volume_score,
        "relative_strength": relative_strength_score,
        "divergence": divergence_score,
    }

    available_keys = [k for k, v in components.items() if v is not None]
    num_available = len(available_keys)

    if num_available < 3:
        return None, components, "INSUFFICIENT"

    total_weight = sum(SIGNAL_WEIGHTS[k] for k in available_keys)
    if total_weight <= 0:
        return None, components, "INSUFFICIENT"

    weighted_sum = sum(components[k] * (SIGNAL_WEIGHTS[k] / total_weight) for k in available_keys)
    signal_score = max(0.0, min(100.0, round(weighted_sum, 1)))

    data_quality = "SUFFICIENT" if num_available >= 5 else "PARTIAL"

    return signal_score, components, data_quality


def calculate_confidence(
    data_quality: str,
    components: dict[str, float | None],
    risk_metrics: dict,
    rsi: float | None = None,
) -> float:
    """Calculate deterministic confidence score (0.10 to 0.95)."""
    if data_quality == "INSUFFICIENT":
        return 0.10

    base_conf = 0.70 if data_quality == "SUFFICIENT" else 0.55

    available_scores = [v for v in components.values() if v is not None]
    if len(available_scores) >= 2:
        mean_score = sum(available_scores) / len(available_scores)
        variance = sum((s - mean_score) ** 2 for s in available_scores) / len(available_scores)
        std_dev = math.sqrt(variance)

        if std_dev < 12.0:
            base_conf += 0.10
        elif std_dev < 18.0:
            base_conf += 0.05
        elif std_dev > 30.0:
            base_conf -= 0.15
        elif std_dev > 22.0:
            base_conf -= 0.08

    vol60 = _safe_float(risk_metrics.get("volatility_60d"))
    mdd = _safe_float(risk_metrics.get("max_drawdown"))

    if vol60 is not None and mdd is not None:
        if vol60 > 0.35 or abs(mdd) > 0.25:
            base_conf -= 0.05
        elif vol60 < 0.22 and abs(mdd) < 0.12:
            base_conf += 0.05

    if rsi is not None and (rsi > 78.0 or rsi < 35.0):
        base_conf -= 0.05

    return round(max(0.10, min(0.95, base_conf)), 2)


def calculate_risk_adjusted_score(
    signal_score: float | None,
    regime: str,
    volatility_60d: float | None = None,
    max_drawdown: float | None = None,
    liquidity_score: float | None = None,
) -> float | None:
    """Calculate deterministic and explainable risk-adjusted signal score."""
    if signal_score is None:
        return None

    regime_map = {
        "STRONG_BULL": 1.05,
        "BULL": 1.00,
        "NEUTRAL": 0.90,
        "DEFENSIVE": 0.90,
        "BEAR": 0.75,
        "PANIC": 0.50,
    }
    if regime not in regime_map:
        raise ValueError(
            f"Invalid market regime: '{regime}'. Must be one of {VALID_MARKET_REGIMES}"
        )
    regime_factor = regime_map[regime]

    vol_penalty = 0.0
    vol60 = _safe_float(volatility_60d)
    if vol60 is not None:
        vol_penalty = min(0.25, max(0.0, (vol60 - 0.20) * 0.5))

    mdd_penalty = 0.0
    mdd = _safe_float(max_drawdown)
    if mdd is not None:
        mdd_penalty = min(0.25, max(0.0, (abs(mdd) - 0.15) * 0.5))

    liq_factor = 1.0
    liq = _safe_float(liquidity_score)
    if liq is not None:
        liq_factor = 0.85 + 0.15 * (max(0.0, min(100.0, liq)) / 100.0)

    score = signal_score * regime_factor * (1.0 - vol_penalty) * (1.0 - mdd_penalty) * liq_factor
    return max(0.0, min(100.0, round(score, 1)))


def classify_action(
    signal_score: float | None,
    regime: str,
    raw_close: float | None = None,
    raw_ma20: float | None = None,
) -> str:
    """Classify action deterministically based on signal_score, market regime, and price filters."""
    if regime == "PANIC" or signal_score is None:
        return "AVOID"

    score = signal_score
    close_above_ma20 = (
        (raw_close > raw_ma20)
        if (raw_close is not None and raw_ma20 is not None and raw_ma20 > 0)
        else False
    )

    if score < 35.0:
        return "AVOID" if regime in ["BEAR", "PANIC"] else "SELL"

    if score >= 75.0:
        if regime in ["STRONG_BULL", "BULL"] and close_above_ma20:
            return "BUY"
        return "WATCH"

    if score >= 65.0:
        if regime in ["STRONG_BULL", "BULL", "DEFENSIVE"] and close_above_ma20:
            return "BUY"
        return "WATCH"

    if score >= 55.0:
        return "WATCH"

    if score >= 45.0:
        return "HOLD"

    return "SELL"


def generate_recommendation(
    symbol: str,
    company_name: str,
    sector: str,
    exchange: str,
    df_stock,
    market_regime_info: dict,
    df_vnindex=None,
    foreign_net_buy_bn: float = 0.0,
    prop_net_buy_bn: float = 0.0,
    data_as_of: str | None = None,
    data_source: str | None = None,
) -> Recommendation:
    """Generate a single stock recommendation object for VN Invest Signal Engine v2.0."""
    from scripts.quant.recommendation import generate_single_recommendation

    return generate_single_recommendation(
        symbol=symbol,
        company_name=company_name,
        sector=sector,
        exchange=exchange,
        df_stock=df_stock,
        market_regime_info=market_regime_info,
        df_vnindex=df_vnindex,
        foreign_net_buy_bn=foreign_net_buy_bn,
        prop_net_buy_bn=prop_net_buy_bn,
        data_as_of=data_as_of,
        data_source=data_source,
    )
