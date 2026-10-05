"""Risk Assessment and Trade Plan calculation module for VN Invest quant layer."""

from typing import Any, Callable

from scripts.lib.recommendation import (
    _safe_float,
    calculate_confidence,
    calculate_risk_adjusted_score,
    format_vnd,
)
from scripts.lib.risk import (
    calculate_t25_risk_metrics,
    normalize_universe_liquidity_scores,
)
from scripts.lib.vietnam_market import (
    clamp_price_limits,
    round_tick_size,
)
from scripts.quant.contracts import RiskInput, RiskResult, RiskTradePlanInput


def compute_stock_risk_and_trade_plan(input_data: RiskInput) -> RiskResult:
    """Compute risk assessment, confidence, risk-adjusted score, trade plan, and invalidation rules."""
    sig = input_data.signal_result
    ex_clean = input_data.exchange
    df_d = input_data.df_d
    raw_close = sig.raw_close
    raw_ma20 = sig.raw_ma20
    raw_ma50 = sig.raw_ma50
    atr = sig.atr

    risk_metrics = calculate_t25_risk_metrics(df_d, exchange=ex_clean)

    confidence = calculate_confidence(
        data_quality=sig.data_quality,
        components=sig.score_components,
        risk_metrics=risk_metrics,
        rsi=sig.rsi,
    )

    vol60 = risk_metrics.get("volatility_60d")
    mdd = risk_metrics.get("max_drawdown")
    if vol60 is not None and mdd is not None:
        if vol60 > 0.35 or abs(mdd) > 0.25:
            risk_level = "HIGH"
        elif vol60 < 0.22 and abs(mdd) < 0.12:
            risk_level = "LOW"
        else:
            risk_level = "MEDIUM"
    else:
        risk_level = None

    current_price_vnd = round(raw_close, 0) if raw_close is not None else 0.0
    lowest_5d = sig.lowest_5d

    invalidation = []

    if input_data.action in ["BUY", "WATCH"] and raw_close is not None:
        stop_atr_component = (raw_close - 1.8 * atr) if atr is not None else (raw_close * 0.95)
        sl_raw = max(
            stop_atr_component,
            lowest_5d if lowest_5d is not None else raw_close,
            (raw_ma20 * 0.98 if raw_ma20 else raw_close * 0.95),
            raw_close * 0.93,
        )
        sl_p = min(sl_raw, raw_close * 0.99)
        sl_p = clamp_price_limits(sl_p, raw_close, ex_clean)
        risk_amt = max(raw_close - sl_p, raw_close * 0.03)

        entry_low_p = round_tick_size(raw_close, ex_clean)
        entry_high_p = clamp_price_limits(max(entry_low_p, raw_close * 1.02), raw_close, ex_clean)
        tp1_p = clamp_price_limits(
            max(entry_high_p, raw_close + 2.0 * risk_amt), raw_close, ex_clean
        )
        tp2_p = clamp_price_limits(max(tp1_p, raw_close + 3.0 * risk_amt), raw_close, ex_clean)

        rr_num = round((tp1_p - raw_close) / risk_amt, 2) if risk_amt > 0 else 1.0

        stop_distance_pct = (
            abs(raw_close - sl_p) / raw_close
            if raw_close > 0 and abs(raw_close - sl_p) > 1e-4
            else 0.05
        )
        portfolio_risk_budget_pct = 1.0
        calc_position_pct = round(portfolio_risk_budget_pct / stop_distance_pct, 1)

        max_position_cap = 20.0 if input_data.action == "BUY" else 10.0
        final_position_pct = min(calc_position_pct, max_position_cap)

        trade_plan = {
            "current_price": current_price_vnd,
            "entry_low": round(entry_low_p, 0),
            "entry_high": round(entry_high_p, 0),
            "stop_loss": round(sl_p, 0),
            "tp1": round(tp1_p, 0),
            "tp2": round(tp2_p, 0),
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
            "current_price": current_price_vnd if raw_close is not None else None,
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

    regime = input_data.market_regime.get("regime", "DEFENSIVE")
    risk_adjusted_score = calculate_risk_adjusted_score(
        signal_score=sig.score,
        regime=regime,
        volatility_60d=vol60,
        max_drawdown=mdd,
        liquidity_score=risk_metrics.get("liquidity_score"),
    )

    return RiskResult(
        risk_level=risk_level,
        confidence=confidence,
        risk_adjusted_score=risk_adjusted_score,
        risk_metrics=risk_metrics,
        trade_plan=trade_plan,
        invalidation=tuple(invalidation),
    )


class RiskTradePlanEngine:
    """Quantitative engine for universe risk normalization and trade plan adjustment."""

    @staticmethod
    def process_risk(
        scanned_recommendations: list[Any] | RiskTradePlanInput,
        market_regime: str | dict | None = None,
        risk_normalizer: Callable[..., list[Any]] | None = None,
    ) -> list[Any]:
        """Normalize liquidity scores and adjust trade plans across scanned recommendations."""
        if isinstance(scanned_recommendations, RiskTradePlanInput):
            input_obj = scanned_recommendations
            recs = input_obj.scanned_recs
            regime = input_obj.market_regime
        else:
            recs = scanned_recommendations
            regime = market_regime

        normalizer = risk_normalizer or normalize_universe_liquidity_scores
        return normalizer(
            scanned_recommendations=recs,
            market_regime=regime,
        )


__all__ = [
    "RiskTradePlanEngine",
    "calculate_risk_adjusted_score",
    "calculate_t25_risk_metrics",
    "compute_stock_risk_and_trade_plan",
    "normalize_universe_liquidity_scores",
]
