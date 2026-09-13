"""VN Invest Signal Engine v2.0.

Generates stock recommendations based on composite deterministic technical signal score,
market regime, T+2.5 risk horizon, market structure entry/stop/target bounds,
and risk-based position sizing.
Allowed actions: BUY, WATCH, HOLD, SELL, AVOID.
Strictly avoids unverified heuristics for expected returns.
All stock price values are converted and displayed in full VND units (e.g. 33,630 VND).
"""

import math

from scripts.lib.features import calculate_multi_timeframe_features
from scripts.lib.risk import calculate_t25_risk_metrics
from scripts.lib.vietnam_market import clamp_price_limits, round_tick_size

SIGNAL_MODEL_VERSION = "2.0"

# Centralized component weights for VN Invest Signal Engine.
# Rationale:
# - Trend (30%): Primary direction vector based on price relative to moving averages (MA20, MA50).
# - Momentum (25%): RSI and MACD indicator confirmation evaluating move strength and momentum decay.
# - Volume (15%): Volume ratio confirming institutional participation vs lack of market liquidity.
# - Relative Strength (15%): Performance relative to benchmark (VN-Index) over 20 sessions.
# - Divergence (15%): Multi-timeframe bullish/bearish divergence signals indicating potential trend reversals.
SIGNAL_WEIGHTS = {
    "trend": 0.30,
    "momentum": 0.25,
    "volume": 0.15,
    "relative_strength": 0.15,
    "divergence": 0.15,
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
    """Format numeric price into full VND string (e.g. 33.63 -> '33,630')."""
    vnd_val = price * 1000.0 if price < 1000.0 else price
    return f"{vnd_val:,.0f}".replace(",", ".")


def _safe_float(val) -> float | None:
    """Safely convert value to float, returning None if None, NaN, or Inf."""
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
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
    prev_hist = _safe_float(prev_macd_hist) if prev_macd_hist is not None else 0.0

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
        if hist > 0 and hist > prev_hist:
            score += 25.0
        elif hist > 0 and hist <= prev_hist:
            score += 10.0
        elif hist < 0 and hist < prev_hist:
            score -= 25.0
        elif hist < 0 and hist >= prev_hist:
            score -= 10.0

    return max(0.0, min(100.0, round(score, 1)))


def calculate_volume_score(volume_ratio: float | None) -> float | None:
    """Calculate Volume Score (0 to 100). Returns None if essential inputs are missing."""
    vr = _safe_float(volume_ratio)
    if vr is None or vr < 0:
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
    """Calculate Divergence Score (0 to 100) across multi-timeframe divergence."""
    if not tf_summary or not isinstance(tf_summary, dict):
        return None

    score = 50.0
    has_valid_tf = False

    for tf_key, tf_label in [("1d", "1D"), ("1w", "1W"), ("1m", "1M")]:
        tf_info = tf_summary.get(tf_key)
        if not tf_info or not tf_info.get("available", False):
            continue

        div = tf_info.get("divergence", {})
        has_valid_tf = True

        if div.get("rsi_bullish") or div.get("macd_bullish"):
            score += 15.0
        if div.get("rsi_bearish") or div.get("macd_bearish"):
            score -= 20.0

    if not has_valid_tf:
        return None

    return max(0.0, min(100.0, round(score, 1)))


def calculate_signal_score(
    trend_score: float | None,
    momentum_score: float | None,
    volume_score: float | None,
    relative_strength_score: float | None,
    divergence_score: float | None,
) -> tuple[float | None, dict[str, float | None], str]:
    """Combine component scores into final deterministic signal_score (0 to 100).

    Uses renormalized available component weights when data is partially missing.
    Returns (signal_score, score_components, data_quality).
    """
    components = {
        "trend": trend_score,
        "momentum": momentum_score,
        "volume": volume_score,
        "relative_strength": relative_strength_score,
        "divergence": divergence_score,
    }

    available_keys = [k for k, v in components.items() if v is not None]
    num_available = len(available_keys)

    if num_available == 0:
        return None, components, "INSUFFICIENT"

    total_weight = sum(SIGNAL_WEIGHTS[k] for k in available_keys)
    if total_weight <= 0:
        return None, components, "INSUFFICIENT"

    weighted_sum = sum(components[k] * (SIGNAL_WEIGHTS[k] / total_weight) for k in available_keys)
    signal_score = max(0.0, min(100.0, round(weighted_sum, 1)))

    if num_available >= 5:
        data_quality = "SUFFICIENT"
    elif num_available >= 3:
        data_quality = "PARTIAL"
    else:
        data_quality = "INSUFFICIENT"

    return signal_score, components, data_quality


def calculate_risk_adjusted_alpha(
    alpha_score: float,
    regime: str,
    volatility_60d: float | None = None,
    max_drawdown: float | None = None,
    liquidity_score: float | None = None,
) -> float:
    """Calculate deterministic and explainable risk-adjusted signal score.

    Formula:
      risk_adjusted_score = signal_score * regime_factor * (1 - vol_penalty) * (1 - mdd_penalty) * liq_factor

    Where:
      - regime_factor: STRONG_BULL=1.05, BULL=1.0, NEUTRAL/DEFENSIVE=0.90, BEAR=0.75, PANIC=0.50
      - vol_penalty: min(0.25, max(0.0, (vol60 - 0.20) * 0.5))
      - mdd_penalty: min(0.25, max(0.0, (abs(mdd) - 0.15) * 0.5))
      - liq_factor: 0.85 + 0.15 * (liquidity_score / 100.0) if liquidity_score is not None else 1.0
    """
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

    score = alpha_score * regime_factor * (1.0 - vol_penalty) * (1.0 - mdd_penalty) * liq_factor
    return max(0.0, min(100.0, round(score, 1)))


# Alias for canonical terminology
calculate_risk_adjusted_score = calculate_risk_adjusted_alpha


def classify_action(
    signal_score: float | None,
    regime: str,
    raw_close: float | None = None,
    raw_ma20: float | None = None,
) -> str:
    """Classify action deterministically based on signal_score, market regime, and price filters.

    Rules are complete, mutually exclusive, and bounded:
    - PANIC regime => AVOID
    - signal_score is None => AVOID
    - signal_score < 35.0 => AVOID (if BEAR/PANIC) else SELL
    - signal_score >= 75.0 => BUY (if STRONG_BULL/BULL & close > ma20) else WATCH
    - signal_score >= 65.0 => BUY (if DEFENSIVE/BULL/STRONG_BULL & close > ma20) else WATCH
    - signal_score >= 55.0 => WATCH
    - signal_score >= 45.0 => HOLD
    - 35.0 <= signal_score < 45.0 => SELL
    """
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
) -> dict:
    """Generate a single stock recommendation object for VN Invest Signal Engine v2.0."""
    ex = exchange.upper() if exchange else "HOSE"

    if df_stock is None or df_stock.empty or len(df_stock) < 20:
        return {
            "symbol": symbol,
            "company_name": company_name,
            "exchange": ex,
            "sector": sector,
            "action": "AVOID",
            "model_version": SIGNAL_MODEL_VERSION,
            "data_quality": "INSUFFICIENT",
            "signal_score": None,
            "alpha_score": None,  # Compatibility field
            "risk_adjusted_score": None,
            "risk_adjusted_alpha": None,  # Compatibility field
            "score_components": {
                "trend": None,
                "momentum": None,
                "volume": None,
                "relative_strength": None,
                "divergence": None,
            },
            "confidence": 0.10,
            "risk_level": None,
            "expected_return": {
                "expected_return_5d": None,
                "expected_return_10d": None,
                "expected_return_20d": None,
            },
            "risk_metrics": {
                "var_t25": None,
                "es_t25": None,
                "volatility_60d": None,
                "max_drawdown": None,
                "liquidity_score": None,
            },
            "trade_plan": {
                "current_price": None,
                "entry_low": None,
                "entry_high": None,
                "stop_loss": None,
                "tp1": None,
                "tp2": None,
                "risk_reward": None,
                "position_percent": 0.0,
            },
            "reasons": ["Dữ liệu lịch sử không đủ 20 phiên giao dịch."],
            "warnings": ["Không có dữ liệu giao dịch để phân tích."],
            "invalidation": ["Cần bổ sung thêm dữ liệu giao dịch trước khi phân tích."],
            "divergence": {
                "1H": "NONE",
                "1D": "NONE",
                "1W": "NONE",
                "1M": "NONE",
            },
        }

    df_d, tf_summary = calculate_multi_timeframe_features(df_stock)
    risk_metrics = calculate_t25_risk_metrics(df_d, exchange=ex)

    raw_close = _safe_float(df_d["close"].iloc[-1])
    raw_ma20 = _safe_float(df_d["ma20"].iloc[-1])
    raw_ma50 = _safe_float(df_d["ma50"].iloc[-1])
    rsi = _safe_float(df_d["rsi"].iloc[-1])
    macd_hist = _safe_float(df_d["hist"].iloc[-1])
    prev_macd_hist = _safe_float(df_d["hist"].iloc[-2]) if len(df_d) >= 2 else 0.0
    atr = _safe_float(df_d["atr"].iloc[-1]) or 0.0

    vol_20d_avg = _safe_float(df_d["vol_ma20"].iloc[-1])
    current_vol = _safe_float(df_d["volume"].iloc[-1])
    vol_ratio = (
        (current_vol / vol_20d_avg)
        if (current_vol is not None and vol_20d_avg is not None and vol_20d_avg > 0)
        else 1.0
    )

    # Relative strength vs VN-Index benchmark
    rs_diff = None
    if df_vnindex is not None and len(df_vnindex) >= 20 and len(df_d) >= 20:
        c0 = _safe_float(df_d["close"].iloc[-20])
        vn_c1 = _safe_float(df_vnindex["close"].iloc[-1])
        vn_c0 = _safe_float(df_vnindex["close"].iloc[-20])
        if (
            raw_close is not None
            and c0 is not None
            and c0 > 0
            and vn_c1 is not None
            and vn_c0 is not None
            and vn_c0 > 0
        ):
            stock_ret_20 = (raw_close - c0) / c0
            vn_ret_20 = (vn_c1 - vn_c0) / vn_c0
            rs_diff = stock_ret_20 - vn_ret_20

    # Component scores calculation
    trend_score = calculate_trend_score(raw_close, raw_ma20, raw_ma50)
    momentum_score = calculate_momentum_score(rsi, macd_hist, prev_macd_hist)
    volume_score = calculate_volume_score(vol_ratio)
    rs_score = calculate_relative_strength_score(rs_diff)
    div_score = calculate_divergence_score(tf_summary)

    score, score_components, data_quality = calculate_signal_score(
        trend_score=trend_score,
        momentum_score=momentum_score,
        volume_score=volume_score,
        relative_strength_score=rs_score,
        divergence_score=div_score,
    )

    # Textual explainability reasons and warnings
    reasons = []
    warnings = []

    if raw_close is not None and raw_ma20 is not None:
        if raw_close > raw_ma20:
            reasons.append(
                f"Giá đóng cửa ({format_vnd(raw_close)} VNĐ) nằm trên đường xu hướng MA20 ({format_vnd(raw_ma20)} VNĐ)."
            )
        else:
            warnings.append(
                f"Giá đóng cửa ({format_vnd(raw_close)} VNĐ) nằm dưới đường xu hướng MA20 ({format_vnd(raw_ma20)} VNĐ)."
            )

    if raw_close is not None and raw_ma50 is not None and raw_close > raw_ma50:
        reasons.append(f"Giá đóng cửa nằm trên hỗ trợ trung hạn MA50 ({format_vnd(raw_ma50)} VNĐ).")

    if macd_hist is not None:
        if macd_hist > 0 and macd_hist > prev_macd_hist:
            reasons.append("MACD Histogram dương và đang tăng trưởng, củng cố đà tăng.")
        elif macd_hist < 0:
            warnings.append("MACD Histogram âm, báo hiệu áp lực điều chỉnh.")

    if vol_ratio is not None and vol_ratio > 1.2:
        reasons.append(f"Khối lượng bùng nổ {vol_ratio:.1f}x so với bình quân 20 phiên.")

    if rsi is not None:
        if 45.0 <= rsi <= 65.0:
            reasons.append(f"Chỉ báo RSI ({rsi:.1f}) nằm trong vùng an toàn (45 - 65).")
        elif rsi > 78.0:
            warnings.append(
                f"RSI ({rsi:.1f}) rơi vào vùng quá mua nặng (> 78), rủi ro đảo chiều cao."
            )
        elif rsi > 70.0:
            warnings.append(f"RSI ({rsi:.1f}) thuộc vùng quá mua (> 70).")
        elif rsi < 35.0:
            warnings.append(f"RSI ({rsi:.1f}) quá bán nặng (< 35).")

    if rs_diff is not None:
        if rs_diff > 0.05:
            reasons.append(
                f"Sức mạnh tương quan (RS) vượt trội so với VN-Index (+{rs_diff * 100:.1f}%)."
            )
        elif rs_diff < -0.05:
            warnings.append(f"Sức mạnh tương quan (RS) yếu hơn VN-Index ({rs_diff * 100:.1f}%).")

    for tf_key, tf_label in [("1d", "1D"), ("1w", "1W"), ("1m", "1M")]:
        tf_info = tf_summary.get(tf_key, {})
        div = tf_info.get("divergence", {})
        if div.get("rsi_bullish") or div.get("macd_bullish"):
            reasons.append(f"Xuất hiện tín hiệu Phân Kỳ Dương trên khung {tf_label}.")
        if div.get("rsi_bearish") or div.get("macd_bearish"):
            warnings.append(f"Cảnh báo Phân Kỳ Âm trên khung {tf_label}.")

    regime = market_regime_info.get("regime", "DEFENSIVE")
    action = classify_action(score, regime, raw_close, raw_ma20)

    # Separate Confidence calculation (0.10 to 0.95)
    confidence = 0.65
    if data_quality == "SUFFICIENT":
        confidence += 0.05
    elif data_quality == "INSUFFICIENT":
        confidence -= 0.15

    vol60 = risk_metrics.get("volatility_60d")
    mdd = risk_metrics.get("max_drawdown")
    if vol60 is not None and mdd is not None:
        if vol60 > 0.35 or abs(mdd) > 0.25:
            risk_level = "HIGH"
            confidence -= 0.05
        elif vol60 < 0.22 and abs(mdd) < 0.12:
            risk_level = "LOW"
            confidence += 0.05
        else:
            risk_level = "MEDIUM"
    else:
        risk_level = None

    if rsi is not None and (rsi > 78.0 or rsi < 35.0):
        confidence -= 0.05

    confidence = round(max(0.10, min(0.95, confidence)), 2)

    # Convert prices to full VND units
    close_vnd = (
        (raw_close * 1000.0 if raw_close < 1000.0 else raw_close) if raw_close is not None else 0.0
    )
    current_price_vnd = round(close_vnd, 0)
    lowest_5d = float(df_d["low"].tail(5).min()) if not df_d.empty else raw_close

    invalidation = []

    if action in ["BUY", "WATCH"]:
        sl_raw = max(
            raw_close - 1.8 * atr,
            lowest_5d,
            (raw_ma20 * 0.98 if raw_ma20 else raw_close * 0.95),
            raw_close * 0.93,
        )
        sl_p = min(sl_raw, raw_close * 0.99)
        sl_p = clamp_price_limits(sl_p, raw_close, ex)
        risk_amt = max(raw_close - sl_p, raw_close * 0.03)

        entry_low_p = round_tick_size(raw_close, ex)
        entry_high_p = clamp_price_limits(max(entry_low_p, raw_close * 1.02), raw_close, ex)
        tp1_p = clamp_price_limits(max(entry_high_p, raw_close + 2.0 * risk_amt), raw_close, ex)
        tp2_p = clamp_price_limits(max(tp1_p, raw_close + 3.0 * risk_amt), raw_close, ex)

        rr_num = round((tp1_p - raw_close) / risk_amt, 2) if risk_amt > 0 else 1.0

        stop_distance_pct = (
            abs(raw_close - sl_p) / raw_close
            if raw_close > 0 and abs(raw_close - sl_p) > 1e-4
            else 0.05
        )
        portfolio_risk_budget_pct = 1.0
        calc_position_pct = round(portfolio_risk_budget_pct / stop_distance_pct, 1)

        max_position_cap = 20.0 if action == "BUY" else 10.0
        final_position_pct = min(calc_position_pct, max_position_cap)

        trade_plan = {
            "current_price": current_price_vnd,
            "entry_low": round(entry_low_p * 1000.0, 0),
            "entry_high": round(entry_high_p * 1000.0, 0),
            "stop_loss": round(sl_p * 1000.0, 0),
            "tp1": round(tp1_p * 1000.0, 0),
            "tp2": round(tp2_p * 1000.0, 0),
            "risk_reward": rr_num,
            "position_percent": final_position_pct,
        }

        invalidation.extend(
            [
                f"Giá đóng cửa vi phạm ngưỡng cắt lỗ {format_vnd(sl_p)} VNĐ.",
                f"Giá gãy hỗ trợ trung hạn MA50 ({format_vnd(raw_ma50 if raw_ma50 else raw_close)}) VNĐ.",
                "Trạng thái thị trường chung suy giảm sang PANIC.",
            ]
        )
    else:
        trade_plan = {
            "current_price": current_price_vnd,
            "entry_low": None,
            "entry_high": None,
            "stop_loss": None,
            "tp1": None,
            "tp2": None,
            "risk_reward": None,
            "position_percent": 0.0,
        }
        invalidation.extend(
            [
                "Giá vượt lên trên MA20 kèm thanh khoản bùng nổ vượt 1.5x bình quân 20 phiên.",
                "Tín hiệu phân kỳ dương hình thành trên khung 1D.",
            ]
        )

    expected_return = {
        "expected_return_5d": None,
        "expected_return_10d": None,
        "expected_return_20d": None,
    }

    # Calculate risk-adjusted score
    risk_adjusted_score = (
        calculate_risk_adjusted_alpha(
            alpha_score=score,
            regime=regime,
            volatility_60d=vol60,
            max_drawdown=mdd,
            liquidity_score=risk_metrics.get("liquidity_score"),
        )
        if score is not None
        else None
    )

    div_mapping = {
        "1H": "NONE",
        "1D": "NONE",
        "1W": "NONE",
        "1M": "NONE",
    }
    tf_k_map = [("1d", "1D"), ("1w", "1W"), ("1m", "1M")]
    for tf_key, tf_lbl in tf_k_map:
        d_info = tf_summary.get(tf_key, {}).get("divergence", {})
        if d_info.get("rsi_bullish") or d_info.get("macd_bullish"):
            div_mapping[tf_lbl] = "BULLISH"
        elif d_info.get("rsi_bearish") or d_info.get("macd_bearish"):
            div_mapping[tf_lbl] = "BEARISH"
        else:
            div_mapping[tf_lbl] = "NONE"

    return {
        "symbol": symbol,
        "company_name": company_name,
        "exchange": ex,
        "sector": sector,
        "action": action,
        "model_version": SIGNAL_MODEL_VERSION,
        "data_quality": data_quality,
        "signal_score": score,
        "alpha_score": score,  # Backward compatibility alias
        "risk_adjusted_score": risk_adjusted_score,
        "risk_adjusted_alpha": risk_adjusted_score,  # Backward compatibility alias
        "score_components": score_components,
        "confidence": confidence,
        "risk_level": risk_level,
        "expected_return": expected_return,
        "risk_metrics": risk_metrics,
        "trade_plan": trade_plan,
        "reasons": reasons,
        "warnings": warnings,
        "invalidation": invalidation,
        "divergence": div_mapping,
    }
