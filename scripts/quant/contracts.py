"""Quantitative input and output contracts for VN Invest quant layer."""

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
class FeatureInput:
    """Input payload for feature computation."""

    stock_data_map: Mapping[str, pd.DataFrame] | list[pd.DataFrame] | tuple[pd.DataFrame, ...]
    candidate_symbols: tuple[str, ...] | list[str] | set[str] | None = None
    processed_symbols: set[str] | tuple[str, ...] | list[str] | None = None


@dataclass(frozen=True)
class FeatureResult:
    """Output result from feature computation."""

    breadth_ratio: float


@dataclass(frozen=True)
class RegimeInput:
    """Input payload for market regime detection."""

    df_vnindex: pd.DataFrame | None = None
    df_vn30: pd.DataFrame | None = None
    breadth_ratio: float | None = None


@dataclass(frozen=True)
class RegimeResult:
    """Output result from market regime detection."""

    market_regime: dict[str, Any]


@dataclass(frozen=True)
class MarketAnalysisInput:
    """Input payload for MarketAnalysisEngine."""

    stock_data_map: Mapping[str, pd.DataFrame] | list[pd.DataFrame] | tuple[pd.DataFrame, ...]
    df_vnindex: pd.DataFrame | None = None
    df_vn30: pd.DataFrame | None = None
    candidate_symbols: tuple[str, ...] | list[str] | set[str] | None = None
    processed_symbols: set[str] | tuple[str, ...] | list[str] | None = None
    vn30_sufficient: bool = True


@dataclass(frozen=True)
class SignalInput:
    """Input payload for signal scoring."""

    symbol: str
    company_name: str
    sector: str
    exchange: str
    df_stock: pd.DataFrame
    market_regime: dict[str, Any]
    df_vnindex: pd.DataFrame | None = None
    data_as_of: str | None = None
    data_source: str | None = None


@dataclass(frozen=True)
class SignalResult:
    """Output result from signal scoring."""

    symbol: str
    score: float | None
    score_components: dict[str, float | None]
    data_quality: str
    rsi: float | None
    macd_hist: float | None
    prev_macd_hist: float | None
    atr: float | None
    vol_ratio: float | None
    rs_diff: float | None
    raw_close: float | None
    raw_ma20: float | None
    raw_ma50: float | None
    lowest_5d: float | None
    df_d: pd.DataFrame
    val_res: dict[str, Any]
    tf_summary: dict[str, Any]
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class RiskInput:
    """Input payload for stock risk assessment and trade plan calculation."""

    symbol: str
    company_name: str
    exchange: str
    sector: str
    df_d: pd.DataFrame
    val_res: dict[str, Any]
    market_regime: dict[str, Any]
    signal_result: SignalResult
    action: str


@dataclass(frozen=True)
class RiskResult:
    """Output result from risk assessment and trade plan calculation."""

    risk_level: str | None
    confidence: float
    risk_adjusted_score: float | None
    risk_metrics: dict[str, Any]
    trade_plan: dict[str, Any]
    invalidation: tuple[str, ...]


@dataclass(frozen=True)
class RiskTradePlanInput:
    """Input payload for universe risk trade plan processing."""

    scanned_recs: list[Any]
    market_regime: str | dict[str, Any] | None = None


@dataclass(frozen=True)
class RecommendationInput:
    """Input payload for recommendation generation."""

    candidates: tuple[CandidateSpec, ...] | list[CandidateSpec]
    stock_data_map: Mapping[str, pd.DataFrame]
    market_regime: dict[str, Any]
    df_vnindex: pd.DataFrame | None = None
    data_as_of: str | None = None
    data_source: str | None = None
    data_sources: Mapping[str, str] | None = None
    processed_symbols: set[str] | tuple[str, ...] | list[str] | None = None


@dataclass(frozen=True)
class RecommendationResult:
    """Output result from recommendation generation."""

    recommendations: list[Any] = field(default_factory=list)


__all__ = [
    "CandidateSpec",
    "FeatureInput",
    "FeatureResult",
    "MarketAnalysisInput",
    "RecommendationInput",
    "RecommendationResult",
    "RegimeInput",
    "RegimeResult",
    "RiskInput",
    "RiskResult",
    "RiskTradePlanInput",
    "SignalInput",
    "SignalResult",
]
