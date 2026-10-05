"""Signal scoring and classification module for VN Invest quant layer."""

import math

from scripts.lib.vietnam_market import (
    get_clean_ohlcv_data,
    validate_ohlcv_data,
)
from scripts.quant.contracts import SignalInput, SignalResult
from scripts.quant.features import calculate_multi_timeframe_features

SIGNAL_MODEL_VERSION = "2.0"

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


def compute_signal(input_data: SignalInput) -> SignalResult:
    """Compute stock signals, scores, and components from clean OHLCV data."""
    val_res = validate_ohlcv_data(input_data.df_stock, input_data.symbol)
    df_clean = val_res["clean_df"]

    if val_res["status"] == "INSUFFICIENT" or df_clean.empty or len(df_clean) < 20:
        return SignalResult(
            symbol=input_data.symbol,
            score=None,
            score_components={
                "trend": None,
                "momentum": None,
                "volume": None,
                "relative_strength": None,
                "divergence": None,
            },
            data_quality="INSUFFICIENT",
            rsi=None,
            macd_hist=None,
            prev_macd_hist=None,
            atr=None,
            vol_ratio=None,
            rs_diff=None,
            raw_close=None,
            raw_ma20=None,
            raw_ma50=None,
            lowest_5d=None,
            df_d=df_clean,
            val_res=val_res,
            tf_summary={},
            reasons=("Dữ liệu lịch sử không đủ hoặc vi phạm điều kiện an toàn dữ liệu.",),
            warnings=("Dữ liệu OHLCV không hợp lệ để tính toán chỉ báo.",),
        )

    df_d, tf_summary = calculate_multi_timeframe_features(df_clean)

    raw_close = _safe_float(df_d["close"].iloc[-1])
    raw_ma20 = _safe_float(df_d["ma20"].iloc[-1])
    raw_ma50 = _safe_float(df_d["ma50"].iloc[-1])
    rsi = _safe_float(df_d["rsi"].iloc[-1])
    macd_hist = _safe_float(df_d["hist"].iloc[-1])
    prev_macd_hist = _safe_float(df_d["hist"].iloc[-2]) if len(df_d) >= 2 else None
    atr = _safe_float(df_d["atr"].iloc[-1])

    vol_20d_avg = _safe_float(df_d["vol_ma20"].iloc[-1])
    current_vol = _safe_float(df_d["volume"].iloc[-1])
    vol_ratio = (
        (current_vol / vol_20d_avg)
        if (current_vol is not None and vol_20d_avg is not None and vol_20d_avg > 0)
        else None
    )

    rs_diff = None
    df_vnindex_clean = None
    if input_data.df_vnindex is not None and not input_data.df_vnindex.empty:
        df_vnindex_clean, _ = get_clean_ohlcv_data(input_data.df_vnindex, "VNINDEX")

    if df_vnindex_clean is not None and len(df_vnindex_clean) >= 20 and len(df_d) >= 20:
        c0 = _safe_float(df_d["close"].iloc[-20])
        vn_c1 = _safe_float(df_vnindex_clean["close"].iloc[-1])
        vn_c0 = _safe_float(df_vnindex_clean["close"].iloc[-20])
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
        if prev_macd_hist is not None and macd_hist > 0 and macd_hist > prev_macd_hist:
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

    lowest_5d = float(df_d["low"].tail(5).min()) if not df_d.empty else raw_close

    return SignalResult(
        symbol=input_data.symbol,
        score=score,
        score_components=score_components,
        data_quality=data_quality,
        rsi=rsi,
        macd_hist=macd_hist,
        prev_macd_hist=prev_macd_hist,
        atr=atr,
        vol_ratio=vol_ratio,
        rs_diff=rs_diff,
        raw_close=raw_close,
        raw_ma20=raw_ma20,
        raw_ma50=raw_ma50,
        lowest_5d=lowest_5d,
        df_d=df_d,
        val_res=val_res,
        tf_summary=tf_summary,
        reasons=tuple(reasons),
        warnings=tuple(warnings),
    )


__all__ = [
    "DIVERGENCE_TIMEFRAME_WEIGHTS",
    "SIGNAL_MODEL_VERSION",
    "SIGNAL_WEIGHTS",
    "VALID_MARKET_REGIMES",
    "_safe_float",
    "calculate_divergence_score",
    "calculate_momentum_score",
    "calculate_relative_strength_score",
    "calculate_signal_score",
    "calculate_trend_score",
    "calculate_volume_score",
    "classify_action",
    "compute_signal",
    "format_vnd",
]
