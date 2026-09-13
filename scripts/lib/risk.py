"""T+2.5 Risk Model Module for VN Invest v2.

Implements Vietnam-specific T+2.5 settlement horizon risk calculations:
- T+2.5 Historical VaR 95%
- T+2.5 Expected Shortfall (ES 95%)
- 60-day Annualized Volatility
- Max Drawdown
- Liquidity Score (0-100 Universe Percentile Rank)
Returns null values if data is insufficient.
"""

import numpy as np
import pandas as pd


def calculate_t25_risk_metrics(
    df: pd.DataFrame,
    exchange: str = "HOSE",
    is_margin_eligible: bool = True,
) -> dict:
    """Calculate T+2.5 risk metrics for a given stock.

    Returns dict with keys: var_t25, es_t25, volatility_60d, max_drawdown, liquidity_score, avg_value_20d.
    If data < 20 sessions, returns nulls.
    """
    default_nulls = {
        "var_t25": None,
        "es_t25": None,
        "volatility_60d": None,
        "max_drawdown": None,
        "liquidity_score": None,
        "avg_value_20d": None,
    }

    if df is None or df.empty or len(df) < 20:
        return default_nulls

    price_col = "close"
    if exchange.upper() == "UPCOM" and "vwap" in df.columns:
        price_col = "vwap"

    df_calc = df.copy()

    # T+2.5 horizon corresponds to 3-session rolling return in daily EOD data
    returns_3d = df_calc[price_col].pct_change(periods=3).dropna()

    if len(returns_3d) < 10:
        return default_nulls

    # Historical VaR 95% T+2.5
    var_95_t25 = float(np.percentile(returns_3d, 5))

    # Expected Shortfall (ES T+2.5): average return below 5th percentile
    tail_losses = returns_3d[returns_3d <= var_95_t25]
    if not tail_losses.empty:
        es_95_t25 = float(tail_losses.mean())
    else:
        es_95_t25 = var_95_t25

    # 60d Annualized Volatility
    returns_1d = df_calc[price_col].pct_change().dropna().tail(60)
    if len(returns_1d) >= 10:
        std_1d = float(returns_1d.std())
        volatility_60d = float(std_1d * np.sqrt(252))
    else:
        volatility_60d = None

    # Max Drawdown
    cummax = df_calc[price_col].cummax()
    dd = (df_calc[price_col] - cummax) / cummax
    max_dd = float(dd.min()) if not dd.empty else None

    # Average 20d trading value in billion VND
    if "volume" in df_calc.columns:
        df_calc["trading_value"] = df_calc[price_col] * df_calc["volume"]
        avg_val = float(df_calc["trading_value"].tail(20).mean())
        avg_val_20d_bn = avg_val / 1e9 if avg_val > 1e6 else avg_val * 1000 / 1e9
    else:
        avg_val_20d_bn = None

    return {
        "var_t25": round(var_95_t25, 4) if var_95_t25 is not None else None,
        "es_t25": round(es_95_t25, 4) if es_95_t25 is not None else None,
        "volatility_60d": round(volatility_60d, 4) if volatility_60d is not None else None,
        "max_drawdown": round(max_dd, 4) if max_dd is not None else None,
        "liquidity_score": None,  # Computed via universe percentile
        "avg_value_20d": round(avg_val_20d_bn, 2) if avg_val_20d_bn is not None else None,
    }


def normalize_universe_liquidity_scores(
    scanned_recommendations: list[dict],
    market_regime: str | dict | None = None,
) -> list[dict]:
    """Compute 0-100 percentile rank for liquidity_score across all stocks in universe at same point in time.

    Also updates risk_adjusted_alpha using the finalized liquidity_score and explicitly provided market_regime.
    """
    from scripts.lib.recommendation import VALID_MARKET_REGIMES, calculate_risk_adjusted_alpha

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

    idx_map = 0
    for r in scanned_recommendations:
        if r.get("risk_metrics", {}).get("avg_value_20d") is not None:
            liq_score = float(ranks.iloc[idx_map])
            r["risk_metrics"]["liquidity_score"] = liq_score
            idx_map += 1

            # Re-calculate risk_adjusted_alpha with populated liquidity_score using explicit market_regime
            if r.get("alpha_score") is not None:
                r["risk_adjusted_alpha"] = calculate_risk_adjusted_alpha(
                    alpha_score=r["alpha_score"],
                    regime=regime_str,
                    volatility_60d=r["risk_metrics"].get("volatility_60d"),
                    max_drawdown=r["risk_metrics"].get("max_drawdown"),
                    liquidity_score=liq_score,
                )
        else:
            r["risk_metrics"]["liquidity_score"] = None

    return scanned_recommendations
