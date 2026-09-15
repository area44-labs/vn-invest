"""Deterministic No-Lookahead Backtesting Framework for Quantitative Signals.

This module provides a minimal, deterministic, and non-lookahead evaluation framework
to evaluate the forward historical outcomes of quantitative signal recommendations produced
by VN Invest Signal Engine.

Key Architectural Principles:
1. Temporal Separation & As-Of Semantics:
   At evaluation date T, the quantitative engine strictly receives data timestamped <= T.
   Point-in-time dataset slicing strictly uses date comparison (date <= T), NOT positional iloc.
   Future data (> T) is strictly isolated and used solely for forward outcome evaluation.
   Future data quality (> T) does NOT affect signal generation at T.
   All market-level inputs (VNINDEX, VN30, and universe market breadth as-of T) are
   strictly bounded <= T before evaluating market regime and signal recommendations.
2. Forward Return Calculation:
   Forward return at horizon N (e.g., 5, 10, 20 trading sessions) is defined as:
       forward_return_N = (Price[T + N] / Price[T]) - 1.0
   If fewer than N future trading sessions exist after T or if future prices/dates are malformed,
   the outcome horizon is marked as unavailable (returns = None, availability = False).
   No extrapolation, interpolation, or fake fill values are used.
3. Direction-Aware Evaluation:
   Directional strategy return is calculated as:
       - BUY: +forward_return
       - SELL: -forward_return
       - HOLD / WATCH / AVOID: 0.0
4. Strategy Return Diagnostic Semantics:
   The metric `sum_strategy_return` represents the arithmetic sum of individual signal strategy returns.
   It serves as a simple diagnostic indicator of signal directionality, NOT a portfolio/compounded return.
5. Fail-Closed Temporal Contract & Validation:
   - `validate_backtest_dataset()` validates canonical OHLCV data-quality contracts.
   - `get_as_of_dataset()` and `evaluate_forward_outcomes()` are the temporal-sensitive entry points
     explicitly enforcing strict chronological ordering (is_monotonic_increasing) and unique dates.
   - Unsorted dates or duplicate dates raise explicit ValueError exceptions rather than being
     silently swallowed or positionally misindexed.
6. Scope Notice:
   Backtest này đánh giá historical signal outcomes, chưa phải portfolio/execution backtest.
   It does not simulate portfolio allocation, position sizing, slippage, transaction costs,
   leverage, or trade execution dynamics.
"""

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from scripts.lib.recommendation import generate_recommendation
from scripts.lib.regime import detect_market_regime
from scripts.lib.vietnam_market import get_clean_ohlcv_data, validate_ohlcv_data

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


def validate_backtest_dataset(df: pd.DataFrame, dataset_name: str = "Dataset") -> dict:
    """Validate DataFrame against canonical OHLCV data-quality contracts for backtesting.

    Contract & Scope:
    - This function checks canonical OHLCV data quality (missing required columns, non-numeric values,
      invalid OHLC relationships, non-positive prices, negative volume).
    - Temporal-sensitive entry points (`get_as_of_dataset()` and `evaluate_forward_outcomes()`)
      are explicitly responsible for enforcing strict chronological ordering (`is_monotonic_increasing`)
      and unique dates before applying date or session indexing.

    Fail-Closed Semantics:
    Raises ValueError on malformed OHLCV data rather than silently swallowing errors.
    """
    if df is None or df.empty:
        raise ValueError(f"{dataset_name} cannot be empty or None.")

    val_res = validate_ohlcv_data(df, dataset_name)
    issues = val_res["issues"]

    critical_errors = [
        "missing_required_columns",
        "missing_date_column",
        "invalid_dates",
        "duplicate_dates",
        "non_numeric_values",
        "non_positive_prices",
        "negative_volume",
        "invalid_ohlc_relationship",
    ]

    found_critical = [iss for iss in issues if iss in critical_errors]
    if found_critical:
        raise ValueError(
            f"{dataset_name} validation failed due to critical data issues: {sorted(found_critical)}"
        )

    return val_res


def get_as_of_dataset(df: pd.DataFrame, evaluation_date: str | pd.Timestamp) -> pd.DataFrame:
    """Extract a strict non-mutating point-in-time dataset containing rows with timestamp <= evaluation_date.

    Temporal Contract & Fail-Closed Validation:
    1. Filters raw DataFrame strictly by date comparison (row_date <= T), NEVER by positional iloc!
       Future rows (> T) with invalid dates/prices never leak into or fail signal generation at T.
    2. Requires exact evaluation_date T to exist in price history.
    3. Validates that the point-in-time sequence (<= T) has parseable, unique, and strictly increasing
       chronological dates. Raises ValueError if dates <= T are unsorted or contain duplicates.
    4. Validates point-in-time OHLCV data <= T strictly via validate_backtest_dataset().
    """
    if df is None or df.empty:
        raise ValueError("Cannot slice empty or None DataFrame.")

    date_col = _find_date_column(df)
    if not date_col:
        raise ValueError("DataFrame missing required 'date' or 'time' column.")

    try:
        target_date_str = pd.to_datetime(evaluation_date).strftime("%Y-%m-%d")
    except (ValueError, TypeError) as err:
        raise ValueError(f"Invalid evaluation date format '{evaluation_date}': {err}") from err

    df_temp = df.copy()
    parsed_dates = pd.to_datetime(df_temp[date_col], errors="coerce")
    formatted_dates = [d.strftime("%Y-%m-%d") if pd.notna(d) else None for d in parsed_dates]
    df_temp["_date_str"] = formatted_dates

    # Check if target evaluation_date exists in dataset
    matches = df_temp[df_temp["_date_str"] == target_date_str]
    if matches.empty:
        raise ValueError(
            f"Evaluation date '{target_date_str}' not present in dataset price history."
        )

    target_idx = matches.index[0]

    # Verify if any unparseable invalid dates occur prior to or on evaluation date (<= T)
    if parsed_dates.iloc[: target_idx + 1].isna().any():
        raise ValueError(
            f"DataFrame column '{date_col}' contains invalid unparseable date entries prior to or on evaluation date '{target_date_str}'."
        )

    # Point-in-time filter strictly by date comparison (date <= T), NEVER by positional iloc!
    as_of_mask = (df_temp["_date_str"].notna()) & (df_temp["_date_str"] <= target_date_str)
    as_of_raw = df_temp[as_of_mask].drop(columns=["_date_str"]).copy()

    if as_of_raw.empty:
        raise ValueError(
            f"No historical data available on or before evaluation date '{target_date_str}'."
        )

    as_of_dates = pd.to_datetime(as_of_raw[date_col], errors="coerce")
    if as_of_dates.isna().any():
        raise ValueError(
            f"Point-in-time dataset <= '{target_date_str}' contains unparseable invalid dates."
        )

    as_of_date_strs = as_of_dates.dt.strftime("%Y-%m-%d")

    # Verify exact evaluation date T exists in dataset history
    if target_date_str not in as_of_date_strs.values:
        raise ValueError(
            f"Evaluation date '{target_date_str}' not present in dataset price history."
        )

    # Validate temporal sequence <= T: unique and strictly increasing chronological order
    if (
        not as_of_dates.is_monotonic_increasing
        or (as_of_dates.diff().dt.total_seconds() <= 0).iloc[1:].any()
    ):
        if as_of_dates.duplicated().any():
            raise ValueError(
                f"Point-in-time dataset <= '{target_date_str}' contains duplicate dates."
            )
        raise ValueError(
            f"Point-in-time dataset <= '{target_date_str}' is unsorted or not strictly increasing in chronological order."
        )

    # Validate point-in-time OHLCV data <= T
    val_res = validate_backtest_dataset(as_of_raw, "Point-in-time Dataset")
    clean_df = val_res["clean_df"]

    if clean_df.empty:
        raise ValueError("Point-in-time dataset contains no valid clean OHLCV rows.")

    return clean_df.reset_index(drop=True)


def calculate_as_of_market_breadth(
    universe_stock_map: dict[str, pd.DataFrame],
    evaluation_date: str,
) -> float:
    """Calculate point-in-time market breadth as-of evaluation date T (ratio of stocks with close > MA20).

    Strictly slices each universe stock dataset <= T before calculating MA20.
    Fails closed on empty universe or malformed universe stock datasets (propagates ValueError).
    """
    if not universe_stock_map:
        raise ValueError("Cannot calculate market breadth: universe_stock_map is empty or None.")

    valid_entries = {k: v for k, v in universe_stock_map.items() if v is not None and not v.empty}
    if not valid_entries:
        raise ValueError(
            "Cannot calculate market breadth: universe_stock_map contains no valid non-empty stock datasets."
        )

    bullish_count = 0
    valid_stocks_count = 0

    for sym, df_stock in valid_entries.items():
        # Extract point-in-time dataset. Fails closed if data <= T is malformed or unsorted.
        try:
            df_stock_as_of = get_as_of_dataset(df_stock, evaluation_date)
        except ValueError as err:
            # Expected when stock has no history prior to evaluation date
            if "No historical data available" in str(err) or "not present in dataset" in str(err):
                continue
            raise

        df_clean, val_res = get_clean_ohlcv_data(df_stock_as_of, sym)

        if val_res["status"] != "INSUFFICIENT" and len(df_clean) >= 20:
            c = _safe_float(df_clean["close"].iloc[-1])
            ma20 = _safe_float(df_clean["close"].tail(20).mean())
            if c is not None and ma20 is not None and ma20 > 0:
                valid_stocks_count += 1
                if c > ma20:
                    bullish_count += 1

    if valid_stocks_count == 0:
        raise ValueError(
            f"Cannot calculate market breadth as-of '{evaluation_date}': zero stocks in universe had sufficient historical data (>= 20 sessions) <= T."
        )

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

    Temporal Contract & Fail-Closed Validation:
    - Requires dataset dates to be parseable, unique, and strictly increasing in chronological order.
    - Requires evaluation date T to exist uniquely in price history.
    - Position T + N corresponds strictly to the N-th valid trading session observation after T.
    """
    if horizons is None:
        horizons = DEFAULT_HORIZONS

    if df_stock is None or df_stock.empty:
        raise ValueError("Cannot evaluate outcomes on empty or None DataFrame.")

    date_col_raw = _find_date_column(df_stock)
    if not date_col_raw or "close" not in df_stock.columns:
        raise ValueError("DataFrame missing required date or 'close' column.")

    try:
        target_date_str = pd.to_datetime(evaluation_date).strftime("%Y-%m-%d")
    except (ValueError, TypeError) as err:
        raise ValueError(f"Invalid evaluation date format '{evaluation_date}': {err}") from err

    # Parse and validate dates across entire outcome dataset strictly
    parsed_dates = pd.to_datetime(df_stock[date_col_raw], errors="coerce")
    if parsed_dates.isna().any():
        raise ValueError("Outcome dataset contains unparseable or invalid date entries.")

    if parsed_dates.duplicated().any():
        raise ValueError("Outcome dataset contains duplicate date entries.")

    if (
        not parsed_dates.is_monotonic_increasing
        or (parsed_dates.diff().dt.total_seconds() <= 0).iloc[1:].any()
    ):
        raise ValueError(
            "Outcome dataset dates are unsorted or not strictly increasing in chronological order."
        )

    # Validate OHLCV quality across dataset
    validate_backtest_dataset(df_stock, "Outcome Dataset")

    df_clean, _ = get_clean_ohlcv_data(df_stock, "SYMBOL")
    if df_clean.empty:
        raise ValueError("Stock DataFrame contains no valid OHLCV data.")

    clean_date_col = _find_date_column(df_clean)
    df_clean["_date_str"] = pd.to_datetime(df_clean[clean_date_col]).dt.strftime("%Y-%m-%d")

    matches = df_clean[df_clean["_date_str"] == target_date_str]

    if matches.empty:
        raise ValueError(f"Evaluation date '{target_date_str}' not present in stock price history.")

    idx_T = matches.index[0]
    price_T = _safe_float(df_clean.iloc[idx_T]["close"])

    if price_T is None or price_T <= 0:
        raise ValueError(f"Invalid price at evaluation date '{target_date_str}': {price_T}")

    returns: dict[int, float | None] = {}
    availability: dict[int, bool] = {}
    strategy_returns: dict[int, float | None] = {}

    total_sessions = len(df_clean)

    for h in horizons:
        if h <= 0:
            raise ValueError(f"Horizon must be a positive integer, got {h}")

        future_idx = idx_T + h
        if future_idx < total_sessions:
            row_future = df_clean.iloc[future_idx]
            date_future = row_future["_date_str"]
            price_future = _safe_float(row_future["close"])

            if (
                date_future is not None
                and not pd.isna(date_future)
                and price_future is not None
                and price_future > 0
            ):
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
    Fails closed on malformed market datasets.
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
            df_vnindex_as_of = get_as_of_dataset(df_vnindex, target_date_str)
            df_vnindex_clean_as_of, val_vn = get_clean_ohlcv_data(df_vnindex_as_of, "VNINDEX")
            if val_vn["status"] == "INSUFFICIENT":
                df_vnindex_clean_as_of = None

        df_vn30_clean_as_of = None
        if df_vn30 is not None and not df_vn30.empty:
            df_vn30_as_of = get_as_of_dataset(df_vn30, target_date_str)
            df_vn30_clean_as_of, val_30 = get_clean_ohlcv_data(df_vn30_as_of, "VN30")
            if val_30["status"] == "INSUFFICIENT":
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
