"""Signal recommendation engine for VN Invest.

Pure quantitative calculation engine for generating universe stock signals and recommendations.
Does not perform I/O, network requests, or database state updates.
"""

from collections.abc import Callable
from typing import Any

import pandas as pd

from scripts.engine.contracts import (
    CandidateSpec,
    SignalRecommendationInput,
    SignalRecommendationResult,
)
from scripts.lib.recommendation import generate_recommendation


class SignalRecommendationEngine:
    """Quantitative engine for universe signal and recommendation generation."""

    @staticmethod
    def generate_recommendations(
        input_data: SignalRecommendationInput,
        recommendation_generator: Callable[..., Any] | None = None,
    ) -> SignalRecommendationResult:
        """Generate recommendations for candidates based on stock data and market regime."""
        scanned_recs = []
        processed_set = (
            set(input_data.processed_symbols) if input_data.processed_symbols is not None else None
        )
        generator = recommendation_generator or generate_recommendation

        for cand in input_data.candidates:
            sym = cand.symbol
            comp = cand.company_name
            sec = cand.sector
            ex = cand.exchange

            df_stock_raw = input_data.stock_data_map.get(sym)

            if processed_set is not None and sym not in processed_set or df_stock_raw is None:
                df_stock_input = pd.DataFrame()
            else:
                df_stock_input = df_stock_raw

            source_tag = None
            if input_data.data_sources and sym in input_data.data_sources:
                source_tag = input_data.data_sources[sym]
            elif not df_stock_input.empty:
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

        return SignalRecommendationResult(recommendations=scanned_recs)


__all__ = [
    "CandidateSpec",
    "SignalRecommendationEngine",
]
