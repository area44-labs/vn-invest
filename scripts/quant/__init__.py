"""Quantitative layer package for VN Invest."""

from scripts.quant.contracts import (
    CandidateSpec,
    FeatureInput,
    FeatureResult,
    RecommendationInput,
    RecommendationResult,
    RegimeInput,
    RegimeResult,
    RiskInput,
    RiskResult,
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
    calculate_risk_adjusted_score,
    calculate_t25_risk_metrics,
    compute_stock_risk_and_trade_plan,
    normalize_universe_liquidity_scores,
)
from scripts.quant.signal import (
    calculate_confidence,
    calculate_divergence_score,
    calculate_momentum_score,
    calculate_relative_strength_score,
    calculate_signal_score,
    calculate_trend_score,
    calculate_volume_score,
    classify_action,
    compute_signal,
)

# MarketAnalysisEngine alias/wrapper around features & regime
class MarketAnalysisEngine:
    """Quantitative engine for market analysis (breadth and regime)."""

    @staticmethod
    def analyze(input_data, regime_detector=None):
        breadth = compute_market_breadth(
            stock_data_map=input_data.stock_data_map,
            candidate_symbols=input_data.candidate_symbols,
            processed_symbols=input_data.processed_symbols,
        )
        df_vn30_input = input_data.df_vn30 if input_data.vn30_sufficient else None
        detector = regime_detector or detect_market_regime
        regime_dict = detector(
            df_vnindex=input_data.df_vnindex,
            df_vn30=df_vn30_input,
            breadth_ratio=breadth,
        )
        return RegimeResult(market_regime=regime_dict)


__all__ = [
    "CandidateSpec",
    "FeatureInput",
    "FeatureResult",
    "MarketAnalysisEngine",
    "RecommendationInput",
    "RecommendationResult",
    "RegimeInput",
    "RegimeResult",
    "RiskInput",
    "RiskResult",
    "RiskTradePlanEngine",
    "SignalInput",
    "SignalResult",
    "SignalRecommendationEngine",
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
