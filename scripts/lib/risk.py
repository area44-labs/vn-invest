"""T+2.5 Risk Model Module for VN Invest v2.

Implements Vietnam-specific T+2.5 settlement horizon risk calculations:
- T+2.5 Historical VaR 95%
- T+2.5 Expected Shortfall (ES 95%)
- 60-day Annualized Volatility
- Max Drawdown
- Average 20-day Trading Value
Returns null values if data is insufficient.

INVARIANT: This module contains pure risk calculations and must NEVER import scripts.lib.recommendation.
"""

import numpy as np
import pandas as pd


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
    # Formula: trading_value_vnd = price (VND/share) * volume (shares)
    # avg_value_20d_bn = mean(last 20 trading_value_vnd) / 1_000_000_000
    if "volume" in df_calc.columns:
        df_calc["trading_value"] = df_calc[price_col] * df_calc["volume"]
        avg_val_vnd = float(df_calc["trading_value"].tail(20).mean())
        avg_val_20d_bn = avg_val_vnd / 1e9
    else:
        avg_val_20d_bn = None

    return {
        "var_t25": round(var_95_t25, 4) if var_95_t25 is not None else None,
        "es_t25": round(es_95_t25, 4) if es_95_t25 is not None else None,
        "volatility_60d": round(volatility_60d, 4) if volatility_60d is not None else None,
        "max_drawdown": round(max_dd, 4) if max_dd is not None else None,
        "liquidity_score": None,  # Computed via universe percentile in scoring.py
        "avg_value_20d": round(avg_val_20d_bn, 2) if avg_val_20d_bn is not None else None,
    }


def normalize_universe_liquidity_scores(
    scanned_recommendations: list[dict],
    market_regime: str | dict | None = None,
) -> list[dict]:
    """Forwarding wrapper for backward compatibility. Delegates strictly to scripts.lib.scoring."""
    from scripts.lib.scoring import normalize_universe_liquidity_scores as _normalize

    return _normalize(scanned_recommendations, market_regime=market_regime)
