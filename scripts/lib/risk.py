"""T+2.5 Risk Model Module for VN Invest v2.

Implements Vietnam-specific T+2.5 settlement horizon risk calculations:
- T+2.5 Historical VaR 95%
- T+2.5 Expected Shortfall (ES 95%)
- 60-day Annualized Volatility
- Max Drawdown
- Liquidity Score (0-100 Universe Percentile Rank)
Returns null values if data is insufficient.
"""

import math

import numpy as np
import pandas as pd


def _safe_float(val) -> float | None:
    """Safely convert value to float, returning None if None, NaN, or Inf."""
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except ValueError, TypeError:
        return None


def calculate_t25_returns(price_series: pd.Series) -> pd.Series:
    """Calculate 3-session EOD proxy returns for the Vietnam T+2.5 settlement horizon.

    Vietnam Market T+2.5 Settlement & Holding Horizon Context:
    Under Vietnamese equity market settlement rules (T+2.5), securities purchased in trading
    session T complete settlement on the afternoon of T+2. Consequently, the investor can first
    trade or dispose of the position during trading session T+3.

    EOD Data Proxy & Limitations:
    Daily EOD OHLCV data consists of discrete trading-session closing/VWAP prices without intra-day
    half-session observations. Exact intra-day settlement mechanics (e.g. trading at T+2 afternoon)
    cannot be reconstructed from daily EOD data alone.

    Therefore, a 3-trading-session return (R_{T+3} = (P_{T+3} - P_T) / P_T) serves as the project's
    explicit, deterministic EOD risk-horizon proxy for T+2.5.

    Input-Order & Clean-Data Contract:
    `price_series` MUST be a chronologically ordered sequence of validated clean trading-session
    prices produced upstream by the clean-data boundary (`get_clean_ohlcv_data`). This helper does
    NOT perform calendar interpolation, date reindexing, price forward-filling, or synthetic row creation.

    Requires at least 4 valid price observations (periods=3 + 1) to yield the first valid return.
    """
    if price_series is None or len(price_series) < 4:
        return pd.Series(dtype=float)

    return price_series.pct_change(periods=3).dropna()


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

    # Calculate T+2.5 settlement horizon returns using explicit EOD session mapping
    returns_3d = calculate_t25_returns(df_calc[price_col])

    if len(returns_3d) < 10:
        return default_nulls

    # Historical VaR 95% T+2.5
    raw_var = _safe_float(np.percentile(returns_3d, 5))
    var_95_t25 = round(raw_var, 4) if raw_var is not None else None

    # Expected Shortfall (ES T+2.5): average return below 5th percentile
    if raw_var is not None:
        tail_losses = returns_3d[returns_3d <= raw_var]
        raw_es = _safe_float(tail_losses.mean()) if not tail_losses.empty else raw_var
        es_95_t25 = round(raw_es, 4) if raw_es is not None else var_95_t25
    else:
        es_95_t25 = None

    # 60d Annualized Volatility
    returns_1d = df_calc[price_col].pct_change().dropna().tail(60)
    volatility_60d = None
    if len(returns_1d) >= 10:
        std_1d = _safe_float(returns_1d.std())
        if std_1d is not None:
            volatility_60d = round(std_1d * np.sqrt(252), 4)

    # Max Drawdown
    cummax = df_calc[price_col].cummax()
    dd = (df_calc[price_col] - cummax) / cummax
    raw_mdd = _safe_float(dd.min()) if not dd.empty else None
    max_dd = round(raw_mdd, 4) if raw_mdd is not None else None

    # Average 20d trading value in billion VND
    # Formula: trading_value_vnd = price (VND/share) * volume (shares)
    # avg_value_20d_bn = mean(last 20 trading_value_vnd) / 1_000_000_000
    avg_val_20d_bn = None
    if "volume" in df_calc.columns:
        df_calc["trading_value"] = df_calc[price_col] * df_calc["volume"]
        raw_avg_val = _safe_float(df_calc["trading_value"].tail(20).mean())
        if raw_avg_val is not None and raw_avg_val > 0:
            avg_val_20d_bn = round(raw_avg_val / 1e9, 2)

    return {
        "var_t25": var_95_t25,
        "es_t25": es_95_t25,
        "volatility_60d": volatility_60d,
        "max_drawdown": max_dd,
        "liquidity_score": None,  # Computed via universe percentile
        "avg_value_20d": avg_val_20d_bn,
    }


def normalize_universe_liquidity_scores(
    scanned_recommendations: list[dict],
    market_regime: str | dict | None = None,
) -> list[dict]:
    """Compute 0-100 percentile rank for liquidity_score across all stocks in universe at same point in time.

    Also updates risk_adjusted_score using the finalized liquidity_score and explicitly provided market_regime.
    """
    from scripts.lib.recommendation import VALID_MARKET_REGIMES, calculate_risk_adjusted_score

    regime_str = None
    if isinstance(market_regime, dict):
        regime_str = market_regime.get("regime")
    elif isinstance(market_regime, str):
        regime_str = market_regime

    if not regime_str or regime_str not in VALID_MARKET_REGIMES:
        raise ValueError(
            f"Invalid or missing market regime: '{market_regime}'. Must be one of {VALID_MARKET_REGIMES}"
        )

    # Only include non-None, positive avg_value_20d from valid symbols in denominator
    valid_recs_indices = []
    values = []
    for idx, r in enumerate(scanned_recommendations):
        # Exclude failed/insufficient symbols from liquidity denominator
        if r.get("data_quality") == "INSUFFICIENT":
            if r.get("risk_metrics"):
                r["risk_metrics"]["liquidity_score"] = None
            r["risk_adjusted_score"] = None
            continue

        val = _safe_float(r.get("risk_metrics", {}).get("avg_value_20d"))
        if val is not None and val > 0:
            values.append(val)
            valid_recs_indices.append(idx)
        else:
            r.get("risk_metrics", {})["liquidity_score"] = None
            r["risk_adjusted_score"] = None

    if not values:
        for r in scanned_recommendations:
            if r.get("risk_metrics"):
                r["risk_metrics"]["liquidity_score"] = None
            r["risk_adjusted_score"] = None
        return scanned_recommendations

    s_values = pd.Series(values)
    # Compute percentile rank (0 to 100)
    ranks = (s_values.rank(pct=True) * 100.0).round(1)

    for list_pos, rec_idx in enumerate(valid_recs_indices):
        r = scanned_recommendations[rec_idx]
        liq_score = float(ranks.iloc[list_pos])
        r["risk_metrics"]["liquidity_score"] = liq_score

        # Re-calculate risk_adjusted_score with populated liquidity_score using explicit market_regime
        if r.get("signal_score") is not None:
            final_adj = calculate_risk_adjusted_score(
                signal_score=r["signal_score"],
                regime=regime_str,
                volatility_60d=r["risk_metrics"].get("volatility_60d"),
                max_drawdown=r["risk_metrics"].get("max_drawdown"),
                liquidity_score=liq_score,
            )
            r["risk_adjusted_score"] = final_adj
        else:
            r["risk_adjusted_score"] = None

    return scanned_recommendations
