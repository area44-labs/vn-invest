"""Canonical Domain Contracts package for VN Invest.

Defines immutable domain models independent of external I/O, CLI, and data provider logic.
"""

from scripts.domain.data_quality import VALID_DATA_QUALITY_STATUSES, DataQuality
from scripts.domain.ohlcv import OHLCVData
from scripts.domain.pipeline_result import PipelineResult
from scripts.domain.recommendation import VALID_ACTIONS, Recommendation
from scripts.domain.risk_assessment import VALID_RISK_LEVELS, RiskAssessment
from scripts.domain.trade_plan import TradePlan
from scripts.domain.universe import VALID_EXCHANGES, Universe, UniverseCandidate

__all__ = [
    "VALID_ACTIONS",
    "VALID_DATA_QUALITY_STATUSES",
    "VALID_EXCHANGES",
    "VALID_RISK_LEVELS",
    "DataQuality",
    "OHLCVData",
    "PipelineResult",
    "Recommendation",
    "RiskAssessment",
    "TradePlan",
    "Universe",
    "UniverseCandidate",
]
