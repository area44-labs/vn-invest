"""Signal scoring and classification module for VN Invest quant layer."""

from scripts.lib.recommendation import (
    SIGNAL_MODEL_VERSION,
    SIGNAL_WEIGHTS,
    _safe_float,
    calculate_confidence,
    calculate_divergence_score,
    calculate_momentum_score,
    calculate_relative_strength_score,
    calculate_signal_score,
    calculate_trend_score,
    calculate_volume_score,
    classify_action,
    format_vnd,
)
from scripts.quant.contracts import SignalInput, SignalResult
from scripts.quant.features import calculate_multi_timeframe_features
from scripts.lib.vietnam_market import (
    get_clean_ohlcv_data,
    validate_ohlcv_data,
)


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
    "SIGNAL_MODEL_VERSION",
    "SIGNAL_WEIGHTS",
    "calculate_confidence",
    "calculate_divergence_score",
    "calculate_momentum_score",
    "calculate_relative_strength_score",
    "calculate_signal_score",
    "calculate_trend_score",
    "calculate_volume_score",
    "classify_action",
    "compute_signal",
]
