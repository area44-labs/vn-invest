"""Quantitative engine input and output contracts for VN Invest."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class CandidateSpec:
    """Canonical specification for a universe candidate stock."""

    symbol: str
    company_name: str
    sector: str
    exchange: str = "HOSE"

    def __post_init__(self) -> None:
        if not self.symbol or not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("CandidateSpec.symbol must be a non-empty string")
        if not self.company_name or not isinstance(self.company_name, str):
            raise ValueError("CandidateSpec.company_name must be a string")
        if not self.sector or not isinstance(self.sector, str):
            raise ValueError("CandidateSpec.sector must be a string")
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(
            self, "exchange", self.exchange.strip().upper() if self.exchange else "HOSE"
        )


@dataclass(frozen=True)
class MarketAnalysisInput:
    """Input payload for MarketAnalysisEngine."""

    stock_data_map: Mapping[str, pd.DataFrame]
    df_vnindex: pd.DataFrame | None = None
    df_vn30: pd.DataFrame | None = None
    candidate_symbols: tuple[str, ...] | list[str] | set[str] | None = None
    processed_symbols: set[str] | tuple[str, ...] | list[str] | None = None
    vn30_sufficient: bool = True


@dataclass(frozen=True)
class MarketAnalysisResult:
    """Output result from MarketAnalysisEngine."""

    breadth_ratio: float
    market_regime: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "breadth_ratio": self.breadth_ratio,
            "market_regime": self.market_regime,
        }


@dataclass(frozen=True)
class SignalRecommendationInput:
    """Input payload for SignalRecommendationEngine."""

    candidates: tuple[CandidateSpec, ...] | list[CandidateSpec]
    stock_data_map: Mapping[str, pd.DataFrame]
    market_regime: dict[str, Any]
    df_vnindex: pd.DataFrame | None = None
    data_as_of: str | None = None
    data_source: str | None = None
    data_sources: Mapping[str, str] | None = None
    processed_symbols: set[str] | tuple[str, ...] | list[str] | None = None


@dataclass(frozen=True)
class SignalRecommendationResult:
    """Output result from SignalRecommendationEngine."""

    recommendations: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class RiskTradePlanInput:
    """Input payload for RiskTradePlanEngine."""

    scanned_recs: list[dict[str, Any]]
    market_regime: dict[str, Any]


@dataclass(frozen=True)
class RiskTradePlanResult:
    """Output result from RiskTradePlanEngine."""

    recommendations: list[dict[str, Any]] = field(default_factory=list)


__all__ = [
    "CandidateSpec",
    "MarketAnalysisInput",
    "MarketAnalysisResult",
    "RiskTradePlanInput",
    "RiskTradePlanResult",
    "SignalRecommendationInput",
    "SignalRecommendationResult",
]
