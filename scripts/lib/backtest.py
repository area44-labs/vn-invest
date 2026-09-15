"""Deterministic No-Lookahead Backtesting Framework for Quantitative Signals.

This module provides a minimal, deterministic, and non-lookahead evaluation framework
to evaluate the forward historical outcomes of quantitative signal recommendations produced
by VN Invest Signal Engine.

Key Architectural Principles:
1. Temporal Separation & As-Of Semantics:
   At evaluation date T, the quantitative engine strictly receives data timestamped <= T.
   Future data (> T) is strictly isolated and used solely for forward outcome evaluation.
   All market-level inputs (VNINDEX, VN30, and universe market breadth as-of T) are
   strictly bounded <= T before evaluating market regime and signal recommendations.
2. Forward Return Calculation:
   Forward return at horizon N (e.g., 5, 10, 20 trading sessions) is defined as:
       forward_return_N = (Price[T + N] / Price[T]) - 1.0
   If fewer than N future trading sessions exist after T, the outcome is marked as unavailable.
   No extrapolation, interpolation, or fake fill values are used.
3. Direction-Aware Evaluation:
   Directional strategy return is calculated as:
       - BUY: +forward_return
       - SELL: -forward_return
       - HOLD / WATCH / AVOID: 0.0
4. Strategy Return Diagnostic Semantics:
   The metric `sum_strategy_return` represents the arithmetic sum of individual signal strategy returns.
   It serves as a simple diagnostic indicator of signal directionality, NOT a portfolio/compounded return.
5. Scope Notice:
   Backtest này đánh giá historical signal outcomes, chưa phải portfolio/execution backtest.
   It does not simulate portfolio allocation, position sizing, slippage, transaction costs,
   leverage, or trade execution dynamics.
"""

from dataclasses import dataclass, field
import math
from typing import Any

import numpy as np
import pandas as pd

from scripts.lib.recommendation import generate_recommendation
from scripts.lib.regime import detect_market_regime
from scripts.lib.vietnam_market import get_clean_ohlcv_data

DEFAULT_HORIZONS = [5, 10, 20]


def _safe_float(val: Any) -> float | None:
    """Safely convert value to float, returning None if None, NaN, or Inf."""
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def _find_date_column(df: pd.DataFrame) -> str | None:
    """Identify the date or time column name in a DataFrame."""
    if df is None or df.empty:
        return None
    for col in ["date", "time", "Date", "Time"]:
        if col in df.columns:
            return col
    return None


@dataclass
class BacktestSignal:
    """Signal state at evaluation time T (no future information included)."""

    symbol: str
    evaluation_date: str
    action: str
    signal_score: float | None
    confidence: float
    market_regime: str
    risk_adjusted_score: float | None
    data_quality: str
    model_version: str
    entry_price: float | None
    score_components: dict[str, float | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "evaluation_date": self.evaluation_date,
            "action": self.action,
            "signal_score": self.signal_score,
            "confidence": self.confidence,
            "market_regime": self.market_regime,
            "risk_adjusted_score": self.risk_adjusted_score,
            "data_quality": self.data_quality,
            "model_version": self.model_version,
            "entry_price": self.entry_price,
            "score_components": self.score_components,
        }


@dataclass
class ForwardOutcome:
    """Future evaluation outcomes after session T (> T)."""

    evaluation_date: str
    returns: dict[int, float | None]
    availability: dict[int, bool]
    strategy_returns: dict[int, float | None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_date": self.evaluation_date,
            "returns": self.returns,
            "availability": self.availability,
            "strategy_returns": self.strategy_returns,
        }


@dataclass
class BacktestResult:
    """Single signal evaluation pair (Signal at T + Forward Outcome after T)."""

    signal: BacktestSignal
    outcome: ForwardOutcome

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal.to_dict(),
            "outcome": self.outcome.to_dict(),
        }


def get_as_of_dataset(df: pd.DataFrame, evaluation_date: str | pd.Timestamp) -> pd.DataFrame:
    """Extract a strict non-mutating point-in-time dataset containing rows with timestamp <= evaluation_date.

    Raises ValueError if required columns are missing, dataset is empty, or evaluation_date is invalid/out-of-bounds.
    """
    if df is None or df.empty:
        raise ValueError("Cannot slice empty or None DataFrame.")

    date_col = _find_date_column(df)
    if not date_col:
        raise ValueError("DataFrame missing required 'date' or 'time' column.")

    try:
        target_date_str = pd.to_datetime(evaluation_date).strftime("%Y-%m-%d")
    except Exception as err:
        raise ValueError(f"Invalid evaluation date format '{evaluation_date}': {err}") from err

    # Ensure clean OHLCV sorting and format
    df_sorted = df.copy()
    parsed_dates = pd.to_datetime(df_sorted[date_col], errors="coerce")
    if parsed_dates.isna().all():
        raise ValueError(f"DataFrame column '{date_col}' contains no valid dates.")

    df_sorted["_date_str"] = parsed_dates.dt.strftime("%Y-%m-%d")
    df_sorted = df_sorted.sort_values("_date_str").reset_index(drop=True)

    as_of_df = df_sorted[df_sorted["_date_str"] <= target_date_str].drop(columns=["_date_str"])

    if as_of_df.empty:
        raise ValueError(
            f"No historical data available on or before evaluation date '{target_date_str}'."
        )

    return as_of_df.reset_index(drop=True)


def calculate_as_of_market_breadth(
    universe_stock_map: dict[str, pd.DataFrame],
    evaluation_date: str,
) -> float:
    """Calculate point-in-time market breadth as-of evaluation date T (ratio of stocks with close > MA20)."""
    if not universe_stock_map:
        return 0.50

    bullish_count = 0
    valid_stocks_count = 0

    for sym, df_stock in universe_stock_map.items():
        if df_stock is None or df_stock.empty:
            continue

        try:
            df_stock_as_of = get_as_of_dataset(df_stock, evaluation_date)
            df_clean, val_res = get_clean_ohlcv_data(df_stock_as_of, sym)
            if val_res["status"] != "INSUFFICIENT" and len(df_clean) >= 20:
                c = _safe_float(df_clean["close"].iloc[-1])
                ma20 = _safe_float(df_clean["close"].tail(20).mean())
                if c is not None and ma20 is not None and ma20 > 0:
                    valid_stocks_count += 1
                    if c > ma20:
                        bullish_count += 1
        except ValueError:
            # Expected when stock has no history prior to evaluation date
            continue

    if valid_stocks_count == 0:
        return 0.50

    return round(bullish_count / valid_stocks_count, 2)


def evaluate_forward_outcomes(
    df_stock: pd.DataFrame,
    evaluation_date: str,
    horizons: list[int] | None = None,
    action: str = "BUY",
) -> ForwardOutcome:
    """Evaluate forward returns and strategy returns for specified trading session horizons after T.

    Forward return formula at T + N trading sessions:
        forward_return_N = (Price[T + N] / Price[T]) - 1.0

    Strategy return semantics:
        - BUY: +forward_return
        - SELL: -forward_return
        - HOLD / WATCH / AVOID: 0.0
    """
    if horizons is None:
        horizons = DEFAULT_HORIZONS

    if df_stock is None or df_stock.empty:
        raise ValueError("Cannot evaluate outcomes on empty or None DataFrame.")

    date_col_raw = _find_date_column(df_stock)
    if not date_col_raw or "close" not in df_stock.columns:
        raise ValueError("DataFrame missing required date or 'close' column.")

    df_clean, _ = get_clean_ohlcv_data(df_stock, "SYMBOL")
    if df_clean.empty:
        raise ValueError("Stock DataFrame contains no valid OHLCV data.")

    clean_date_col = _find_date_column(df_clean)
    if not clean_date_col:
        raise ValueError("Clean DataFrame missing date/time column.")

    df_clean["_date_str"] = pd.to_datetime(df_clean[clean_date_col]).dt.strftime("%Y-%m-%d")
    df_sorted = df_clean.sort_values("_date_str").reset_index(drop=True)

    try:
        target_date_str = pd.to_datetime(evaluation_date).strftime("%Y-%m-%d")
    except Exception as err:
        raise ValueError(f"Invalid evaluation date format '{evaluation_date}': {err}") from err

    matches = df_sorted[df_sorted["_date_str"] == target_date_str]

    if matches.empty:
        raise ValueError(f"Evaluation date '{target_date_str}' not present in stock price history.")

    idx_T = matches.index[0]
    price_T = _safe_float(df_sorted.iloc[idx_T]["close"])

    if price_T is None or price_T <= 0:
        raise ValueError(f"Invalid price at evaluation date '{target_date_str}': {price_T}")

    returns: dict[int, float | None] = {}
    availability: dict[int, bool] = {}
    strategy_returns: dict[int, float | None] = {}

    total_sessions = len(df_sorted)

    for h in horizons:
        if h <= 0:
            raise ValueError(f"Horizon must be a positive integer, got {h}")

        future_idx = idx_T + h
        if future_idx < total_sessions:
            price_future = _safe_float(df_sorted.iloc[future_idx]["close"])
            if price_future is not None and price_future > 0:
                ret_val = round((price_future / price_T) - 1.0, 6)
                returns[h] = ret_val
                availability[h] = True

                if action == "BUY":
                    strategy_returns[h] = ret_val
                elif action == "SELL":
                    strategy_returns[h] = round(-ret_val, 6)
                else:
                    strategy_returns[h] = 0.0
            else:
                returns[h] = None
                availability[h] = False
                strategy_returns[h] = None
        else:
            returns[h] = None
            availability[h] = False
            strategy_returns[h] = None

    return ForwardOutcome(
        evaluation_date=target_date_str,
        returns=returns,
        availability=availability,
        strategy_returns=strategy_returns,
    )


def run_backtest_for_symbol(
    symbol: str,
    df_stock: pd.DataFrame,
    evaluation_dates: list[str],
    company_name: str = "",
    sector: str = "",
    exchange: str = "HOSE",
    df_vnindex: pd.DataFrame | None = None,
    df_vn30: pd.DataFrame | None = None,
    breadth_ratio: float | None = None,
    universe_stock_map: dict[str, pd.DataFrame] | None = None,
    horizons: list[int] | None = None,
) -> list[BacktestResult]:
    """Run point-in-time deterministic backtest for a single symbol over multiple evaluation dates.

    Guarantees strict no-lookahead bias by slicing stock data and all market-level inputs
    (VNINDEX, VN30, and universe market breadth as-of T) strictly <= T before calling production engine.
    """
    if horizons is None:
        horizons = DEFAULT_HORIZONS

    results: list[BacktestResult] = []

    for eval_date in evaluation_dates:
        target_date_str = pd.to_datetime(eval_date).strftime("%Y-%m-%d")

        # 1. Point-in-time stock data slicing (<= T)
        df_stock_as_of = get_as_of_dataset(df_stock, target_date_str)

        # 2. Point-in-time market data slicing (<= T) for production regime inputs
        df_vnindex_clean_as_of = None
        if df_vnindex is not None and not df_vnindex.empty:
            try:
                df_vnindex_as_of = get_as_of_dataset(df_vnindex, target_date_str)
                df_vnindex_clean_as_of, val_vn = get_clean_ohlcv_data(df_vnindex_as_of, "VNINDEX")
                if val_vn["status"] == "INSUFFICIENT":
                    df_vnindex_clean_as_of = None
            except ValueError:
                df_vnindex_clean_as_of = None

        df_vn30_clean_as_of = None
        if df_vn30 is not None and not df_vn30.empty:
            try:
                df_vn30_as_of = get_as_of_dataset(df_vn30, target_date_str)
                df_vn30_clean_as_of, val_30 = get_clean_ohlcv_data(df_vn30_as_of, "VN30")
                if val_30["status"] == "INSUFFICIENT":
                    df_vn30_clean_as_of = None
            except ValueError:
                df_vn30_clean_as_of = None

        # Point-in-time market breadth as-of T
        effective_breadth = breadth_ratio
        if effective_breadth is None and universe_stock_map:
            effective_breadth = calculate_as_of_market_breadth(universe_stock_map, target_date_str)

        # 3. Market regime evaluation at T using production regime engine
        market_regime_info = detect_market_regime(
            df_vnindex=df_vnindex_clean_as_of,
            df_vn30=df_vn30_clean_as_of,
            breadth_ratio=effective_breadth,
        )

        # 4. Recommendation generation at T using production engine
        rec = generate_recommendation(
            symbol=symbol,
            company_name=company_name,
            sector=sector,
            exchange=exchange,
            df_stock=df_stock_as_of,
            market_regime_info=market_regime_info,
            df_vnindex=df_vnindex_clean_as_of,
            data_as_of=target_date_str,
        )

        raw_entry_price = rec["trade_plan"].get("current_price")
        entry_price = _safe_float(raw_entry_price)

        signal = BacktestSignal(
            symbol=symbol,
            evaluation_date=target_date_str,
            action=rec["action"],
            signal_score=rec["signal_score"],
            confidence=rec["confidence"],
            market_regime=market_regime_info["regime"],
            risk_adjusted_score=rec["risk_adjusted_score"],
            data_quality=rec["data_quality"],
            model_version=rec["model_version"],
            entry_price=entry_price,
            score_components=rec["score_components"],
        )

        # 5. Forward outcome evaluation (> T)
        outcome = evaluate_forward_outcomes(
            df_stock=df_stock,
            evaluation_date=target_date_str,
            horizons=horizons,
            action=rec["action"],
        )

        results.append(BacktestResult(signal=signal, outcome=outcome))

    return results


def run_backtest_for_universe(
    universe_stock_map: dict[str, pd.DataFrame],
    evaluation_dates: list[str],
    candidate_metadata: list[dict] | None = None,
    df_vnindex: pd.DataFrame | None = None,
    df_vn30: pd.DataFrame | None = None,
    horizons: list[int] | None = None,
) -> list[BacktestResult]:
    """Run point-in-time deterministic backtest across an entire stock universe.

    Computes point-in-time market breadth as-of T across all stocks in universe_stock_map.
    """
    if horizons is None:
        horizons = DEFAULT_HORIZONS

    meta_map = {}
    if candidate_metadata:
        for item in candidate_metadata:
            meta_map[item["symbol"]] = item

    all_results: list[BacktestResult] = []

    for sym, df_stock in universe_stock_map.items():
        item = meta_map.get(sym, {})
        comp = item.get("companyName", "")
        sec = item.get("sector", "")
        ex = item.get("exchange", "HOSE")

        res_sym = run_backtest_for_symbol(
            symbol=sym,
            df_stock=df_stock,
            evaluation_dates=evaluation_dates,
            company_name=comp,
            sector=sec,
            exchange=ex,
            df_vnindex=df_vnindex,
            df_vn30=df_vn30,
            universe_stock_map=universe_stock_map,
            horizons=horizons,
        )
        all_results.extend(res_sym)

    return all_results


def calculate_return_stats(return_series: list[float]) -> dict[str, float | None]:
    """Calculate descriptive summary statistics for a list of return values."""
    if not return_series:
        return {
            "mean": None,
            "median": None,
            "min": None,
            "max": None,
        }

    arr = np.array(return_series, dtype=float)
    return {
        "mean": round(float(np.mean(arr)), 6),
        "median": round(float(np.median(arr)), 6),
        "min": round(float(np.min(arr)), 6),
        "max": round(float(np.max(arr)), 6),
    }


def aggregate_backtest_results(
    results: list[BacktestResult], horizons: list[int] | None = None
) -> dict[str, Any]:
    """Aggregate backtest signal results into summary statistics, forward returns, and directional hit rates.

    Metrics provided:
    - Signal Statistics: total signals, action counts, valid outcome count per horizon.
    - Forward Return Statistics (for each horizon): mean, median, min, max.
    - Directional Metrics:
      - BUY hit rate: ratio of BUY signals where forward return > 0
      - SELL hit rate: ratio of SELL signals where forward return < 0
      - Combined directional hit rate: ratio of directional (BUY/SELL) signals with positive direction outcome
    - Strategy Returns:
      - mean: average directional strategy return
      - median: median directional strategy return
      - sum_strategy_return: arithmetic sum of individual signal strategy returns (diagnostic metric only)
    - Breakdown by action and market regime.
    """
    if horizons is None:
        horizons = DEFAULT_HORIZONS

    total_signals = len(results)
    action_counts: dict[str, int] = {
        "BUY": 0,
        "HOLD": 0,
        "SELL": 0,
        "WATCH": 0,
        "AVOID": 0,
    }

    for res in results:
        act = res.signal.action
        action_counts[act] = action_counts.get(act, 0) + 1

    valid_outcome_counts: dict[int, int] = {h: 0 for h in horizons}
    horizon_metrics: dict[int, dict[str, Any]] = {}

    for h in horizons:
        fwd_returns: list[float] = []
        strat_returns: list[float] = []

        buy_hits = 0
        buy_total = 0

        sell_hits = 0
        sell_total = 0

        for res in results:
            if res.outcome.availability.get(h, False):
                fwd_ret = res.outcome.returns.get(h)
                strat_ret = res.outcome.strategy_returns.get(h)

                if fwd_ret is not None:
                    valid_outcome_counts[h] += 1
                    fwd_returns.append(fwd_ret)

                    if strat_ret is not None:
                        strat_returns.append(strat_ret)

                    if res.signal.action == "BUY":
                        buy_total += 1
                        if fwd_ret > 0:
                            buy_hits += 1
                    elif res.signal.action == "SELL":
                        sell_total += 1
                        if fwd_ret < 0:
                            sell_hits += 1

        fwd_stats = calculate_return_stats(fwd_returns)
        strat_stats = calculate_return_stats(strat_returns)

        buy_hit_rate = round(buy_hits / buy_total, 4) if buy_total > 0 else None
        sell_hit_rate = round(sell_hits / sell_total, 4) if sell_total > 0 else None

        combined_total = buy_total + sell_total
        combined_hits = buy_hits + sell_hits
        combined_hit_rate = round(combined_hits / combined_total, 4) if combined_total > 0 else None

        sum_strat_return = round(float(sum(strat_returns)), 6) if strat_returns else 0.0

        horizon_metrics[h] = {
            "valid_signals": valid_outcome_counts[h],
            "forward_return": fwd_stats,
            "strategy_return": {
                "mean": strat_stats["mean"],
                "median": strat_stats["median"],
                "sum_strategy_return": sum_strat_return,
            },
            "buy_hit_rate": buy_hit_rate,
            "buy_signals_count": buy_total,
            "sell_hit_rate": sell_hit_rate,
            "sell_signals_count": sell_total,
            "combined_directional_hit_rate": combined_hit_rate,
        }

    # Breakdown by action
    actions = sorted({res.signal.action for res in results})
    breakdown_by_action: dict[str, dict[int, dict[str, Any]]] = {}

    for act in actions:
        breakdown_by_action[act] = {}
        sub_results = [r for r in results if r.signal.action == act]

        for h in horizons:
            sub_rets = [
                r.outcome.returns[h]
                for r in sub_results
                if r.outcome.availability.get(h) and r.outcome.returns.get(h) is not None
            ]
            breakdown_by_action[act][h] = {
                "count": len(sub_rets),
                "stats": calculate_return_stats(sub_rets),
            }

    # Breakdown by market regime
    regimes = sorted({res.signal.market_regime for res in results})
    breakdown_by_regime: dict[str, dict[int, dict[str, Any]]] = {}

    for reg in regimes:
        breakdown_by_regime[reg] = {}
        sub_results = [r for r in results if r.signal.market_regime == reg]

        for h in horizons:
            sub_rets = [
                r.outcome.returns[h]
                for r in sub_results
                if r.outcome.availability.get(h) and r.outcome.returns.get(h) is not None
            ]
            breakdown_by_regime[reg][h] = {
                "count": len(sub_rets),
                "stats": calculate_return_stats(sub_rets),
            }

    return {
        "signal_statistics": {
            "total_signals": total_signals,
            "action_counts": action_counts,
            "valid_outcome_counts": valid_outcome_counts,
        },
        "horizon_metrics": horizon_metrics,
        "breakdown_by_action": breakdown_by_action,
        "breakdown_by_regime": breakdown_by_regime,
    }
