"""Recommendation Engine Module for VN Invest v2.

Generates stock recommendations based on composite technical alpha score,
market regime, T+2.5 risk horizon, market structure entry/stop/target bounds,
and risk-based position sizing.
Allowed actions: BUY, WATCH, HOLD, SELL, AVOID.
Strictly avoids unverified heuristics for expected returns.
All stock price values are converted and displayed in full VND units (e.g. 33,630 VND).
"""

from scripts.lib.features import calculate_multi_timeframe_features
from scripts.lib.risk import calculate_t25_risk_metrics
from scripts.lib.vietnam_market import clamp_price_limits, round_tick_size


def format_vnd(price: float) -> str:
    """Format numeric price into full VND string (e.g. 33.63 -> '33,630')."""
    vnd_val = price * 1000.0 if price < 1000.0 else price
    return f"{vnd_val:,.0f}".replace(",", ".")


VALID_MARKET_REGIMES = {
    "STRONG_BULL",
    "BULL",
    "NEUTRAL",
    "DEFENSIVE",
    "BEAR",
    "PANIC",
}


def calculate_risk_adjusted_alpha(
    alpha_score: float,
    regime: str,
    volatility_60d: float | None = None,
    max_drawdown: float | None = None,
    liquidity_score: float | None = None,
) -> float:
    """Calculate deterministic and explainable risk-adjusted alpha score.

    Formula:
      risk_adjusted_alpha = alpha_score * regime_factor * (1 - vol_penalty) * (1 - mdd_penalty) * liq_factor

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
    if volatility_60d is not None:
        vol_penalty = min(0.25, max(0.0, (volatility_60d - 0.20) * 0.5))

    mdd_penalty = 0.0
    if max_drawdown is not None:
        mdd_penalty = min(0.25, max(0.0, (abs(max_drawdown) - 0.15) * 0.5))

    liq_factor = 1.0
    if liquidity_score is not None:
        liq_factor = 0.85 + 0.15 * (max(0.0, min(100.0, liquidity_score)) / 100.0)

    score = alpha_score * regime_factor * (1.0 - vol_penalty) * (1.0 - mdd_penalty) * liq_factor
    return max(0.0, min(100.0, round(score, 1)))


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
    """Generate a single stock recommendation object for VN Invest v2."""
    ex = exchange.upper() if exchange else "HOSE"

    if df_stock is None or df_stock.empty or len(df_stock) < 20:
        return {
            "symbol": symbol,
            "company_name": company_name,
            "exchange": ex,
            "sector": sector,
            "action": "AVOID",
            "alpha_score": None,
            "risk_adjusted_alpha": None,
            "confidence": 0.0,
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
                "position_percent": None,
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

    raw_close = float(df_d["close"].iloc[-1])
    raw_ma20 = float(df_d["ma20"].iloc[-1])
    raw_ma50 = float(df_d["ma50"].iloc[-1])
    rsi = float(df_d["rsi"].iloc[-1])
    macd_hist = float(df_d["hist"].iloc[-1])
    prev_macd_hist = float(df_d["hist"].iloc[-2]) if len(df_d) >= 2 else 0.0
    atr = float(df_d["atr"].iloc[-1])

    # Convert to full VND units
    close_vnd = raw_close * 1000.0 if raw_close < 1000.0 else raw_close

    vol_20d_avg = float(df_d["vol_ma20"].iloc[-1])
    vol_ratio = float(df_d["volume"].iloc[-1]) / vol_20d_avg if vol_20d_avg > 0 else 1.0

    score = 50.0
    confidence = 0.65
    reasons = []
    warnings = []
    invalidation = []

    if raw_close > raw_ma20:
        score += 10.0
        confidence += 0.05
        reasons.append(
            f"Giá đóng cửa ({format_vnd(raw_close)} VNĐ) nằm trên đường xu hướng MA20 ({format_vnd(raw_ma20)} VNĐ)."
        )
    else:
        score -= 10.0
        confidence -= 0.05
        warnings.append(
            f"Giá đóng cửa ({format_vnd(raw_close)} VNĐ) nằm dưới đường xu hướng MA20 ({format_vnd(raw_ma20)} VNĐ)."
        )

    if raw_close > raw_ma50:
        score += 10.0
        reasons.append(f"Giá đóng cửa nằm trên hỗ trợ trung hạn MA50 ({format_vnd(raw_ma50)} VNĐ).")

    if macd_hist > 0 and macd_hist > prev_macd_hist:
        score += 10.0
        confidence += 0.05
        reasons.append("MACD Histogram dương và đang tăng trưởng, củng cố đà tăng.")
    elif macd_hist < 0:
        score -= 10.0
        warnings.append("MACD Histogram âm, báo hiệu áp lực điều chỉnh.")

    if vol_ratio > 1.2:
        score += 10.0
        confidence += 0.05
        reasons.append(f"Khối lượng bùng nổ {vol_ratio:.1f}x so với bình quân 20 phiên.")

    if 45.0 <= rsi <= 68.0:
        score += 10.0
        reasons.append(f"Chỉ báo RSI ({rsi:.1f}) nằm trong vùng an toàn (45 - 68).")
    elif rsi > 78.0:
        score -= 15.0
        confidence -= 0.10
        warnings.append(f"RSI ({rsi:.1f}) rơi vào vùng quá mua nặng (> 78), rủi ro đảo chiều cao.")
    elif rsi > 70.0:
        score -= 10.0
        warnings.append(f"RSI ({rsi:.1f}) thuộc vùng quá mua (> 70).")
    elif rsi < 35.0:
        score -= 10.0
        warnings.append(f"RSI ({rsi:.1f}) quá bán nặng (< 35).")

    # Relative strength vs VN-Index
    if df_vnindex is not None and len(df_vnindex) >= 20 and len(df_d) >= 20:
        stock_ret_20 = (df_d["close"].iloc[-1] - df_d["close"].iloc[-20]) / df_d["close"].iloc[-20]
        vn_ret_20 = (df_vnindex["close"].iloc[-1] - df_vnindex["close"].iloc[-20]) / df_vnindex[
            "close"
        ].iloc[-20]
        rs_diff = stock_ret_20 - vn_ret_20
        if rs_diff > 0.05:
            score += 5.0
            confidence += 0.05
            reasons.append(
                f"Sức mạnh tương quan (RS) vượt trội so với VN-Index (+{rs_diff * 100:.1f}%)."
            )
        elif rs_diff < -0.05:
            score -= 5.0
            warnings.append(f"Sức mạnh tương quan (RS) yếu hơn VN-Index ({rs_diff * 100:.1f}%).")

    has_major_bearish_div = False
    for tf_key, tf_label in [("1d", "1D"), ("1w", "1W"), ("1m", "1M")]:
        div = tf_summary[tf_key]["divergence"]
        if div["rsi_bullish"] or div["macd_bullish"]:
            score += 5.0
            confidence += 0.05
            reasons.append(f"Xuất hiện tín hiệu Phân Kỳ Dương trên khung {tf_label}.")
        if div["rsi_bearish"] or div["macd_bearish"]:
            score -= 10.0
            confidence -= 0.05
            warnings.append(f"Cảnh báo Phân Kỳ Âm trên khung {tf_label}.")
            if tf_key in ["1d", "1w"]:
                has_major_bearish_div = True

    if has_major_bearish_div:
        score = min(score, 60.0)

    score = max(0.0, min(100.0, round(score, 1)))

    regime = market_regime_info.get("regime", "DEFENSIVE")

    if regime == "PANIC" or score < 35.0:
        action = "AVOID" if regime == "PANIC" else "SELL"
    elif (score >= 75.0 and raw_close > raw_ma20 and regime in ["STRONG_BULL", "BULL"]) or (
        score >= 65.0 and raw_close > raw_ma20 and regime == "DEFENSIVE"
    ):
        action = "BUY"
    elif score >= 55.0:
        action = "WATCH"
    elif score >= 45.0:
        action = "HOLD"
    else:
        action = "SELL"

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

    confidence = round(max(0.10, min(0.95, confidence)), 2)

    # Trade Plan in full VND
    current_price_vnd = round(close_vnd, 0)
    lowest_5d = float(df_d["low"].tail(5).min())

    if action in ["BUY", "WATCH"]:
        sl_raw = max(raw_close - 1.8 * atr, lowest_5d, raw_ma20 * 0.98, raw_close * 0.93)
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
                f"Giá gãy hỗ trợ trung hạn MA50 ({format_vnd(raw_ma50)} VNĐ).",
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

    # Initial risk_adjusted_alpha without universe liquidity score (will be updated when universe normalized)
    risk_adjusted_alpha = calculate_risk_adjusted_alpha(
        alpha_score=score,
        regime=regime,
        volatility_60d=vol60,
        max_drawdown=mdd,
        liquidity_score=risk_metrics.get("liquidity_score"),
    )

    div_mapping = {
        "1H": "NONE",
        "1D": "NONE",
        "1W": "NONE",
        "1M": "NONE",
    }
    tf_k_map = [("1d", "1D"), ("1w", "1W"), ("1m", "1M")]
    for tf_key, tf_lbl in tf_k_map:
        d_info = tf_summary[tf_key]["divergence"]
        if d_info["rsi_bullish"] or d_info["macd_bullish"]:
            div_mapping[tf_lbl] = "BULLISH"
        elif d_info["rsi_bearish"] or d_info["macd_bearish"]:
            div_mapping[tf_lbl] = "BEARISH"
        else:
            div_mapping[tf_lbl] = "NONE"

    return {
        "symbol": symbol,
        "company_name": company_name,
        "exchange": ex,
        "sector": sector,
        "action": action,
        "alpha_score": score,
        "risk_adjusted_alpha": risk_adjusted_alpha,
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
