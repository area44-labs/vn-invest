"""Quantitative layer package for VN Invest."""

from collections.abc import Callable
from typing import Any

from scripts.quant.config import DEFAULT_QUANT_CONFIG, QuantConfig
from scripts.quant.contracts import (
    CandidateSpec,
    FeatureInput,
    FeatureResult,
    MarketAnalysisInput,
    RecommendationInput,
    RecommendationResult,
    RegimeInput,
    RegimeResult,
    RiskInput,
    RiskResult,
    RiskTradePlanInput,
    SignalInput,
    SignalResult,
)
from scripts.quant.features import calculate_multi_timeframe_features, compute_market_breadth
from scripts.quant.recommendation import (
    SignalRecommendationEngine,
    generate_single_recommendation,
)
from scripts.quant.regime import detect_market_regime
from scripts.quant.risk import (
    RiskTradePlanEngine,
    calculate_confidence,
    calculate_risk_adjusted_score,
    calculate_t25_risk_metrics,
    compute_stock_risk_and_trade_plan,
    normalize_universe_liquidity_scores,
)
from scripts.quant.signal import (
    calculate_divergence_score,
    calculate_momentum_score,
    calculate_relative_strength_score,
    calculate_signal_score,
    calculate_trend_score,
    calculate_volume_score,
    classify_action,
    compute_signal,
)


class MarketAnalysisEngine:
    """Quantitative engine for market analysis (breadth and regime)."""

    @staticmethod
    def analyze(
        input_data: MarketAnalysisInput,
        regime_detector: Callable[..., dict[str, Any]] | None = None,
    ) -> RegimeResult:
        cfg = input_data.config
        feature_in = FeatureInput(
            stock_data_map=input_data.stock_data_map,
            candidate_symbols=input_data.candidate_symbols,
            processed_symbols=input_data.processed_symbols,
            config=cfg,
        )
        feature_res = compute_market_breadth(feature_in)

        df_vn30_input = input_data.df_vn30 if input_data.vn30_sufficient else None
        regime_in = RegimeInput(
            df_vnindex=input_data.df_vnindex,
            df_vn30=df_vn30_input,
            breadth_ratio=feature_res.breadth_ratio,
            config=cfg,
        )
        return detect_market_regime(regime_in, detector=regime_detector)


__all__ = [
    "DEFAULT_QUANT_CONFIG",
    "CandidateSpec",
    "FeatureInput",
    "FeatureResult",
    "MarketAnalysisEngine",
    "MarketAnalysisInput",
    "QuantConfig",
    "RecommendationInput",
    "RecommendationResult",
    "RegimeInput",
    "RegimeResult",
    "RiskInput",
    "RiskResult",
    "RiskTradePlanEngine",
    "RiskTradePlanInput",
    "SignalInput",
    "SignalRecommendationEngine",
    "SignalResult",
    "calculate_confidence",
    "calculate_divergence_score",
    "calculate_momentum_score",
    "calculate_multi_timeframe_features",
    "calculate_relative_strength_score",
    "calculate_risk_adjusted_score",
    "calculate_signal_score",
    "calculate_t25_risk_metrics",
    "calculate_trend_score",
    "calculate_volume_score",
    "classify_action",
    "compute_market_breadth",
    "compute_signal",
    "compute_stock_risk_and_trade_plan",
    "detect_market_regime",
    "generate_single_recommendation",
    "normalize_universe_liquidity_scores",
]
