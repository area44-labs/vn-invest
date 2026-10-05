"""Risk and trade plan engine for VN Invest.

Pure quantitative calculation engine for normalizing risk, liquidity rankings, and trade plan parameters.
Does not perform I/O, network requests, or database state updates.
"""

from collections.abc import Callable
from typing import Any

from scripts.engine.contracts import RiskTradePlanInput, RiskTradePlanResult
from scripts.lib.risk import normalize_universe_liquidity_scores


class RiskTradePlanEngine:
    """Quantitative engine for universe risk normalization and trade plan adjustment."""

    @staticmethod
    def process_risk(
        input_data: RiskTradePlanInput,
        risk_normalizer: Callable[..., list[Any]] | None = None,
    ) -> RiskTradePlanResult:
        """Normalize liquidity scores and adjust trade plans across scanned recommendations."""
        normalizer = risk_normalizer or normalize_universe_liquidity_scores
        normalized_recs = normalizer(
            scanned_recommendations=input_data.scanned_recs,
            market_regime=input_data.market_regime,
        )
        return RiskTradePlanResult(recommendations=normalized_recs)


__all__ = [
    "RiskTradePlanEngine",
]
