"""Scoring Module for VN Invest v2.

Implements risk-adjusted scoring and universe percentile liquidity score calculations.
Independent of recommendation composition/orchestration layer.
"""

import math
import numpy as np
import pandas as pd

from scripts.lib.config import VALID_MARKET_REGIMES


def _safe_float(val: float | None) -> float | None:
    if val is None or math.isnan(val) or math.isinf(val):
        return None
    return float(val)


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
    scanned_recommendations: list[dict],
    market_regime: str | dict | None = None,
) -> list[dict]:
    """Compute 0-100 percentile rank for liquidity_score across all stocks in universe at same point in time.

    Updates risk_adjusted_score using finalized liquidity_score and explicitly provided market_regime.
    Non-mutating: returns new updated recommendation payload dictionaries.
    """
    regime_str = None
    if isinstance(market_regime, dict):
        regime_str = market_regime.get("regime")
    elif isinstance(market_regime, str):
        regime_str = market_regime

    if not regime_str or regime_str not in VALID_MARKET_REGIMES:
        raise ValueError(
            f"Invalid or missing market regime: '{market_regime}'. Must be one of {VALID_MARKET_REGIMES}"
        )

    values = []
    for r in scanned_recommendations:
        val = r.get("risk_metrics", {}).get("avg_value_20d")
        if val is not None:
            values.append(val)

    if not values:
        return scanned_recommendations

    s_values = pd.Series(values)
    # Compute percentile rank (0 to 100)
    ranks = (s_values.rank(pct=True) * 100.0).round(1)

    updated_recs = []
    idx_map = 0

    for r in scanned_recommendations:
        r_copy = dict(r)
        risk_metrics = dict(r_copy.get("risk_metrics", {})) if r_copy.get("risk_metrics") else {}

        if risk_metrics.get("avg_value_20d") is not None:
            liq_score = float(ranks.iloc[idx_map])
            risk_metrics["liquidity_score"] = liq_score
            idx_map += 1

            r_copy["risk_metrics"] = risk_metrics

            # Re-calculate risk_adjusted_score with populated liquidity_score using explicit market_regime
            if r_copy.get("signal_score") is not None:
                final_adj = calculate_risk_adjusted_score(
                    signal_score=r_copy["signal_score"],
                    regime=regime_str,
                    volatility_60d=risk_metrics.get("volatility_60d"),
                    max_drawdown=risk_metrics.get("max_drawdown"),
                    liquidity_score=liq_score,
                )
                r_copy["risk_adjusted_score"] = final_adj
            else:
                r_copy["risk_adjusted_score"] = None
        else:
            risk_metrics["liquidity_score"] = None
            r_copy["risk_metrics"] = risk_metrics
            updated_recs.append(r_copy)
            continue

        updated_recs.append(r_copy)

    return updated_recs
