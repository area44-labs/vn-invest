"""Risk Assessment and Trade Plan calculation module for VN Invest quant layer."""

import math
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from scripts.lib.vietnam_market import (
    clamp_price_limits,
    round_tick_size,
)
from scripts.quant.contracts import RiskInput, RiskResult, RiskTradePlanInput
from scripts.quant.signal import (
    VALID_MARKET_REGIMES,
    _safe_float,
    format_vnd,
)


def calculate_t25_returns(price_series: pd.Series) -> pd.Series:
    """Calculate 3-session EOD proxy returns for the Vietnam T+2.5 settlement horizon."""
    if price_series is None or len(price_series) < 4:
        return pd.Series(dtype=float)

    return price_series.pct_change(periods=3).dropna()


def calculate_t25_risk_metrics(
    df: pd.DataFrame,
    exchange: str = "HOSE",
    is_margin_eligible: bool = True,
) -> dict:
    """Calculate T+2.5 risk metrics for a given stock."""
    default_nulls = {
        "var_t25": None,
        "es_t25": None,
        "volatility_60d": None,
        "max_drawdown": None,
        "liquidity_score": None,
        "avg_value_20d": None,
    }

    if df is None or df.empty or len(df) < 20:
        return default_nulls

    price_col = "close"
    if exchange.upper() == "UPCOM" and "vwap" in df.columns:
        price_col = "vwap"

    df_calc = df.copy()

    returns_3d = calculate_t25_returns(df_calc[price_col])

    if len(returns_3d) < 10:
        return default_nulls

    raw_var = _safe_float(np.percentile(returns_3d, 5))
    var_95_t25 = round(raw_var, 4) if raw_var is not None else None

    if raw_var is not None:
        tail_losses = returns_3d[returns_3d <= raw_var]
        raw_es = _safe_float(tail_losses.mean()) if not tail_losses.empty else raw_var
        es_95_t25 = round(raw_es, 4) if raw_es is not None else var_95_t25
    else:
        es_95_t25 = None

    returns_1d = df_calc[price_col].pct_change().dropna().tail(60)
    volatility_60d = None
    if len(returns_1d) >= 10:
        std_1d = _safe_float(returns_1d.std())
        if std_1d is not None:
            volatility_60d = _safe_float(round(std_1d * float(np.sqrt(252)), 4))

    cummax = df_calc[price_col].cummax()
    dd = (df_calc[price_col] - cummax) / cummax
    raw_mdd = _safe_float(dd.min()) if not dd.empty else None
    max_dd = round(raw_mdd, 4) if raw_mdd is not None else None

    avg_val_20d_bn = None
    if "volume" in df_calc.columns:
        df_calc["trading_value"] = df_calc[price_col] * df_calc["volume"]
        raw_avg_val = _safe_float(df_calc["trading_value"].tail(20).mean())
        if raw_avg_val is not None and raw_avg_val > 0:
            avg_val_20d_bn = round(raw_avg_val / 1e9, 2)

    return {
        "var_t25": var_95_t25,
        "es_t25": es_95_t25,
        "volatility_60d": volatility_60d,
        "max_drawdown": max_dd,
        "liquidity_score": None,
        "avg_value_20d": avg_val_20d_bn,
    }


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

    vol60 = _safe_float(risk_metrics.get("volatility_60d")) if risk_metrics else None
    mdd = _safe_float(risk_metrics.get("max_drawdown")) if risk_metrics else None

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


def normalize_universe_liquidity_scores(
    scanned_recommendations: list[Any],
    market_regime: str | dict | None = None,
) -> list[Any]:
    """Compute 0-100 percentile rank for liquidity_score across all stocks in universe."""
    from scripts.domain.recommendation import Recommendation

    regime_str = None
    if isinstance(market_regime, dict):
        regime_str = market_regime.get("regime")
    elif isinstance(market_regime, str):
        regime_str = market_regime

    if not regime_str or regime_str not in VALID_MARKET_REGIMES:
        raise ValueError(
            f"Invalid or missing market regime: '{market_regime}'. Must be one of {VALID_MARKET_REGIMES}"
        )

    recs_out = list(scanned_recommendations)

    valid_recs_indices = []
    values = []
    for idx, r in enumerate(recs_out):
        dq = r.data_quality if isinstance(r, Recommendation) else r.get("data_quality")
        if dq == "INSUFFICIENT":
            if isinstance(r, Recommendation):
                recs_out[idx] = r.with_liquidity_score(
                    liquidity_score=None, risk_adjusted_score=None
                )
            else:
                if r.get("risk_metrics"):
                    r["risk_metrics"]["liquidity_score"] = None
                r["risk_adjusted_score"] = None
            continue

        if isinstance(r, Recommendation):
            avg_val = r.risk_metrics.avg_value_20d if r.risk_metrics else None
        else:
            avg_val = (
                r.get("risk_metrics", {}).get("avg_value_20d")
                if isinstance(r.get("risk_metrics"), dict)
                else None
            )

        val = _safe_float(avg_val)
        if val is not None and val > 0:
            values.append(val)
            valid_recs_indices.append(idx)
        else:
            if isinstance(r, Recommendation):
                recs_out[idx] = r.with_liquidity_score(
                    liquidity_score=None, risk_adjusted_score=None
                )
            else:
                if isinstance(r.get("risk_metrics"), dict):
                    r["risk_metrics"]["liquidity_score"] = None
                r["risk_adjusted_score"] = None

    if not values:
        for idx, r in enumerate(recs_out):
            if isinstance(r, Recommendation):
                recs_out[idx] = r.with_liquidity_score(
                    liquidity_score=None, risk_adjusted_score=None
                )
            else:
                if isinstance(r.get("risk_metrics"), dict):
                    r["risk_metrics"]["liquidity_score"] = None
                r["risk_adjusted_score"] = None
        return recs_out

    s_values = pd.Series(values)
    ranks = (s_values.rank(pct=True) * 100.0).round(1)

    for list_pos, rec_idx in enumerate(valid_recs_indices):
        r = recs_out[rec_idx]
        liq_score = float(ranks.iloc[list_pos])

        if isinstance(r, Recommendation):
            sig_score = r.signal_score
            vol_60d = r.risk_metrics.volatility_60d if r.risk_metrics else None
            mdd = r.risk_metrics.max_drawdown if r.risk_metrics else None
        else:
            sig_score = r.get("signal_score")
            vol_60d = (
                r.get("risk_metrics", {}).get("volatility_60d")
                if isinstance(r.get("risk_metrics"), dict)
                else None
            )
            mdd = (
                r.get("risk_metrics", {}).get("max_drawdown")
                if isinstance(r.get("risk_metrics"), dict)
                else None
            )

        if sig_score is not None:
            final_adj = calculate_risk_adjusted_score(
                signal_score=sig_score,
                regime=regime_str,
                volatility_60d=vol_60d,
                max_drawdown=mdd,
                liquidity_score=liq_score,
            )
        else:
            final_adj = None

        if isinstance(r, Recommendation):
            recs_out[rec_idx] = r.with_liquidity_score(
                liquidity_score=liq_score, risk_adjusted_score=final_adj
            )
        else:
            if isinstance(r.get("risk_metrics"), dict):
                r["risk_metrics"]["liquidity_score"] = liq_score
            r["risk_adjusted_score"] = final_adj

    return recs_out


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
    "calculate_confidence",
    "calculate_risk_adjusted_score",
    "calculate_t25_returns",
    "calculate_t25_risk_metrics",
    "compute_stock_risk_and_trade_plan",
    "normalize_universe_liquidity_scores",
]
