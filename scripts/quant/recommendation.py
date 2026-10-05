"""Recommendation and trade plan composition module for VN Invest quant layer."""

from collections.abc import Callable
from typing import Any

import pandas as pd

from scripts.domain import Recommendation, RiskAssessment, TradePlan
from scripts.lib.recommendation import (
    SIGNAL_MODEL_VERSION,
    classify_action,
)
from scripts.quant.contracts import (
    CandidateSpec,
    RecommendationInput,
    RecommendationResult,
    RiskInput,
    SignalInput,
)
from scripts.quant.risk import compute_stock_risk_and_trade_plan
from scripts.quant.signal import compute_signal
from scripts.lib.vietnam_market import (
    extract_latest_trading_date,
    validate_ohlcv_data,
)


def generate_single_recommendation(
    symbol: str,
    company_name: str,
    sector: str,
    exchange: str,
    df_stock: pd.DataFrame,
    market_regime_info: dict[str, Any],
    df_vnindex: pd.DataFrame | None = None,
    foreign_net_buy_bn: float = 0.0,
    prop_net_buy_bn: float = 0.0,
    data_as_of: str | None = None,
    data_source: str | None = None,
) -> Recommendation:
    """Generate a single stock recommendation object by composing quant signal and risk modules."""
    comp_clean = (
        company_name.strip()
        if (isinstance(company_name, str) and company_name.strip())
        else f"Company {symbol}"
    )
    sec_clean = sector.strip() if (isinstance(sector, str) and sector.strip()) else "General"
    ex_clean = (
        exchange.strip().upper() if (isinstance(exchange, str) and exchange.strip()) else "HOSE"
    )

    val_res = validate_ohlcv_data(df_stock, symbol)
    df_clean = val_res["clean_df"]
    stock_data_as_of = (
        data_as_of or val_res.get("latest_date") or extract_latest_trading_date(df_clean)
    )

    if val_res["status"] == "INSUFFICIENT" or df_clean.empty or len(df_clean) < 20:
        return Recommendation(
            symbol=symbol,
            company_name=comp_clean,
            exchange=ex_clean,
            sector=sec_clean,
            action="AVOID",
            model_version=SIGNAL_MODEL_VERSION,
            data_quality="INSUFFICIENT",
            data_quality_issues=tuple(val_res["issues"]),
            data_as_of=stock_data_as_of,
            data_source=data_source,
            signal_score=None,
            risk_adjusted_score=None,
            score_components={
                "trend": None,
                "momentum": None,
                "volume": None,
                "relative_strength": None,
                "divergence": None,
            },
            confidence=0.10,
            risk_level=None,
            expected_return={
                "expected_return_5d": None,
                "expected_return_10d": None,
                "expected_return_20d": None,
            },
            risk_metrics=RiskAssessment(
                var_t25=None,
                es_t25=None,
                volatility_60d=None,
                max_drawdown=None,
                liquidity_score=None,
            ),
            trade_plan=TradePlan(
                current_price=None,
                entry_low=None,
                entry_high=None,
                stop_loss=None,
                tp1=None,
                tp2=None,
                risk_reward=None,
                position_percent=0.0,
            ),
            reasons=("Dữ liệu lịch sử không đủ hoặc vi phạm điều kiện an toàn dữ liệu.",),
            warnings=("Dữ liệu OHLCV không hợp lệ để tính toán chỉ báo.",),
            invalidation=("Cần kiểm tra và bổ sung dữ liệu giao dịch trước khi phân tích.",),
            divergence={
                "1H": "NONE",
                "1D": "NONE",
                "1W": "NONE",
                "1M": "NONE",
            },
        )

    # 1. Compute Signal
    signal_input = SignalInput(
        symbol=symbol,
        company_name=comp_clean,
        sector=sec_clean,
        exchange=ex_clean,
        df_stock=df_stock,
        market_regime=market_regime_info,
        df_vnindex=df_vnindex,
        data_as_of=stock_data_as_of,
        data_source=data_source,
    )
    sig_res = compute_signal(signal_input)

    regime = market_regime_info.get("regime", "DEFENSIVE")
    action = classify_action(sig_res.score, regime, sig_res.raw_close, sig_res.raw_ma20)

    # 2. Compute Risk & Trade Plan
    risk_input = RiskInput(
        symbol=symbol,
        company_name=comp_clean,
        exchange=ex_clean,
        sector=sec_clean,
        df_d=sig_res.df_d,
        val_res=val_res,
        market_regime=market_regime_info,
        signal_result=sig_res,
        action=action,
    )
    risk_res = compute_stock_risk_and_trade_plan(risk_input)

    div_mapping = {
        "1H": "NONE",
        "1D": "NONE",
        "1W": "NONE",
        "1M": "NONE",
    }
    tf_k_map = [("1d", "1D"), ("1w", "1W"), ("1m", "1M")]
    for tf_key, tf_lbl in tf_k_map:
        d_info = sig_res.tf_summary.get(tf_key, {}).get("divergence", {})
        if d_info.get("rsi_bullish") or d_info.get("macd_bullish"):
            div_mapping[tf_lbl] = "BULLISH"
        elif d_info.get("rsi_bearish") or d_info.get("macd_bearish"):
            div_mapping[tf_lbl] = "BEARISH"
        else:
            div_mapping[tf_lbl] = "NONE"

    final_data_quality = sig_res.data_quality
    if val_res["status"] == "PARTIAL" and final_data_quality == "SUFFICIENT":
        final_data_quality = "PARTIAL"

    risk_assessment = RiskAssessment(
        var_t25=risk_res.risk_metrics.get("var_t25"),
        es_t25=risk_res.risk_metrics.get("es_t25"),
        volatility_60d=risk_res.risk_metrics.get("volatility_60d"),
        max_drawdown=risk_res.risk_metrics.get("max_drawdown"),
        liquidity_score=risk_res.risk_metrics.get("liquidity_score"),
        avg_value_20d=risk_res.risk_metrics.get("avg_value_20d"),
        risk_level=risk_res.risk_level,
    )

    trade_plan_obj = TradePlan(
        current_price=risk_res.trade_plan.get("current_price"),
        entry_low=risk_res.trade_plan.get("entry_low"),
        entry_high=risk_res.trade_plan.get("entry_high"),
        stop_loss=risk_res.trade_plan.get("stop_loss"),
        tp1=risk_res.trade_plan.get("tp1"),
        tp2=risk_res.trade_plan.get("tp2"),
        risk_reward=risk_res.trade_plan.get("risk_reward"),
        position_percent=risk_res.trade_plan.get("position_percent", 0.0),
    )

    expected_return = {
        "expected_return_5d": None,
        "expected_return_10d": None,
        "expected_return_20d": None,
    }

    return Recommendation(
        symbol=symbol,
        company_name=comp_clean,
        exchange=ex_clean,
        sector=sec_clean,
        action=action,
        model_version=SIGNAL_MODEL_VERSION,
        data_quality=final_data_quality,
        data_quality_issues=tuple(val_res["issues"]),
        data_as_of=stock_data_as_of,
        data_source=data_source,
        signal_score=sig_res.score,
        risk_adjusted_score=risk_res.risk_adjusted_score,
        score_components=sig_res.score_components,
        confidence=risk_res.confidence,
        risk_level=risk_res.risk_level,
        expected_return=expected_return,
        risk_metrics=risk_assessment,
        trade_plan=trade_plan_obj,
        reasons=tuple(sig_res.reasons),
        warnings=tuple(sig_res.warnings),
        invalidation=tuple(risk_res.invalidation),
        divergence=div_mapping,
    )


class SignalRecommendationEngine:
    """Quantitative engine for universe signal and recommendation generation."""

    @staticmethod
    def generate_recommendations(
        input_data: RecommendationInput,
        recommendation_generator: Callable[..., Any] | None = None,
    ) -> RecommendationResult:
        """Generate recommendations for candidates based on stock data and market regime."""
        scanned_recs = []
        processed_set = (
            set(input_data.processed_symbols) if input_data.processed_symbols is not None else None
        )
        generator = recommendation_generator or generate_single_recommendation

        for cand in input_data.candidates:
            sym = cand.symbol
            comp = cand.company_name
            sec = cand.sector
            ex = cand.exchange

            df_stock_raw = input_data.stock_data_map.get(sym)

            if (processed_set is not None and sym not in processed_set) or df_stock_raw is None:
                df_stock_input = pd.DataFrame()
            else:
                df_stock_input = df_stock_raw

            source_tag = None
            if not df_stock_input.empty:
                if input_data.data_sources and sym in input_data.data_sources:
                    source_tag = input_data.data_sources[sym]
                else:
                    source_tag = input_data.data_source

            rec = generator(
                symbol=sym,
                company_name=comp,
                sector=sec,
                exchange=ex,
                df_stock=df_stock_input,
                market_regime_info=input_data.market_regime,
                df_vnindex=input_data.df_vnindex,
                data_as_of=input_data.data_as_of,
                data_source=source_tag,
            )
            scanned_recs.append(rec)

        return RecommendationResult(recommendations=scanned_recs)


__all__ = [
    "CandidateSpec",
    "SignalRecommendationEngine",
    "generate_single_recommendation",
]
