"""Quantitative engine package for VN Invest.

Provides dedicated quantitative engines with explicit typed contracts for:
- Market analysis and regime detection (MarketAnalysisEngine)
- Universe signal and recommendation generation (SignalRecommendationEngine)
- Risk normalization and trade plan adjustment (RiskTradePlanEngine)
"""

from scripts.engine.contracts import (
    CandidateSpec,
    MarketAnalysisInput,
    MarketAnalysisResult,
    RiskTradePlanInput,
    RiskTradePlanResult,
    SignalRecommendationInput,
    SignalRecommendationResult,
)
from scripts.engine.market import MarketAnalysisEngine, compute_market_breadth
from scripts.engine.recommendation import SignalRecommendationEngine
from scripts.engine.risk import RiskTradePlanEngine

__all__ = [
    "CandidateSpec",
    "MarketAnalysisEngine",
    "MarketAnalysisInput",
    "MarketAnalysisResult",
    "RiskTradePlanEngine",
    "RiskTradePlanInput",
    "RiskTradePlanResult",
    "SignalRecommendationEngine",
    "SignalRecommendationInput",
    "SignalRecommendationResult",
    "compute_market_breadth",
]
