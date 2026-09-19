"""Deterministic No-Lookahead Portfolio-Level Backtesting Framework.

This module provides a deterministic, no-lookahead portfolio-level backtesting framework
built on top of the existing validated signal, walk-forward, and execution-eligibility infrastructure.

Key Architectural & Evaluation Principles:
1. Historical Portfolio Evaluation Layer:
   This module evaluates how stock-level signals behave when combined into a portfolio over time.
   It is strictly a historical evaluation tool.

   Disclaimers:
   - It is NOT a live trading simulator or broker execution simulator.
   - It does NOT prove profitability or causality.
   - It does NOT perform statistical validation (no p-values, hypothesis tests, or bootstrap optimization).
   - It does NOT perform portfolio optimization (no mean-variance, risk-parity, ML, or parameter sweeping).

2. Infrastructure Reuse & Non-Duplication:
   - Point-in-time dataset slicing timestamped <= T reuses `get_as_of_dataset()`.
   - Production market regime detection reuses `detect_market_regime()`.
   - Production stock signal recommendations reuse `generate_recommendation()`.
   - Execution eligibility evaluations reuse `evaluate_execution_eligibility()` and `ExecutionConfig`.
   - Point-in-time market breadth reuses `calculate_as_of_market_breadth()`.
   - Forward historical returns reuse `evaluate_forward_outcomes()`.

3. Portfolio Construction & Weighting Contract:
   - Candidates are selected at T using strictly observable signals and actions timestamped <= T.
   - Maximum position limit, minimum signal score, minimum confidence, allowed actions,
     and optional execution eligibility requirements filter candidate securities.
   - Equal-weight allocation is applied with optional maximum position weight constraints.
   - Unallocated weight (if any) is explicitly preserved (`unallocated_weight = 1.0 - sum(weights)`).
   - Tie-breaking for candidate selection is strictly deterministic:
     ranking by `(signal_score desc, risk_adjusted_score desc, confidence desc, symbol asc)`.
   - Portfolio weights are strictly validated (`validate_portfolio_weights()`):
     weights must be finite, non-negative, and total allocated weight must not exceed 1.0.
     Silently normalizing invalid weights is forbidden.

4. Forward Portfolio Outcome Semantics:
   - For a portfolio with weights w_i and stock forward returns r_i at horizon N:
       portfolio_return_N = Σ(w_i × r_i)
   - If any selected constituent lacks forward data at horizon N, the outcome for horizon N
     is marked unavailable (portfolio_return = None).
   - An intentionally empty portfolio is tracked with a explicit empty_reason, and its
     forward return is None (never silently converted to zero return).

5. Fail-Closed Temporal Contract:
   - Rejects duplicate dates, unsorted dates, invalid dates, future observations physically
     placed prior to T, missing evaluation dates, and invalid OHLCV data.
"""

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from scripts.lib.backtest import (
    DEFAULT_HORIZONS,
    ExecutionConfig,
    _parse_canonical_date,
    calculate_as_of_market_breadth,
    calculate_execution_return,
    evaluate_execution_eligibility,
    evaluate_forward_outcomes,
    get_as_of_dataset,
)
from scripts.lib.recommendation import generate_recommendation
from scripts.lib.vietnam_market import get_clean_ohlcv_data


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


def _validate_numeric_param(
    val: Any,
    field_name: str,
    min_val: float = 0.0,
    max_val: float | None = None,
    allow_zero: bool = True,
    strict_int: bool = False,
) -> None:
    """Validate numeric configuration parameter deterministically, raising ValueError on failure."""
    if val is None:
        return

    if isinstance(val, bool):
        raise ValueError(f"{field_name} cannot be a boolean, got {val}")  # noqa: TRY004

    if not isinstance(val, (int, float)):
        raise ValueError(f"{field_name} must be numeric, got {type(val).__name__}: {val}")  # noqa: TRY004

    if strict_int and not isinstance(val, int):
        raise ValueError(f"{field_name} must be an integer, got {type(val).__name__}: {val}")

    f = float(val)
    if math.isnan(f) or math.isinf(f):
        raise ValueError(f"{field_name} cannot be NaN or Inf, got {val}")

    if allow_zero:
        if f < min_val:
            raise ValueError(f"{field_name} must be >= {min_val}, got {val}")
    else:
        if f <= min_val:
            raise ValueError(f"{field_name} must be > {min_val}, got {val}")

    if max_val is not None and f > max_val:
        raise ValueError(f"{field_name} must be <= {max_val}, got {val}")


def _build_candidate_meta_map(
    candidate_metadata: list[dict] | None,
    universe_stock_map: dict[str, pd.DataFrame] | None = None,
) -> dict[str, dict]:
    """Validate and map candidate metadata list by symbol deterministically.

    Fail-Closed Validation:
    - If candidate_metadata is None or empty, returns empty dict.
    - Each entry must be a dictionary containing a valid, non-empty string 'symbol'.
    - Duplicate symbols raise ValueError.
    - Every symbol in candidate_metadata must exist in universe_stock_map.
    """
    if not candidate_metadata:
        return {}

    if not isinstance(candidate_metadata, (list, tuple)):
        raise TypeError("candidate_metadata must be a list or tuple of dictionaries.")

    meta_map: dict[str, dict] = {}
    for idx, item in enumerate(candidate_metadata):
        if not isinstance(item, dict):
            raise TypeError(
                f"candidate_metadata[{idx}] must be a dictionary, got {type(item).__name__}"
            )

        sym = item.get("symbol")
        if not isinstance(sym, str) or not sym.strip():
            raise ValueError(
                f"candidate_metadata[{idx}] missing or invalid required 'symbol' string: {sym}"
            )

        sym_clean = sym.strip()
        if sym_clean in meta_map:
            raise ValueError(
                f"Duplicate symbol '{sym_clean}' found in candidate_metadata at index {idx}."
            )

        if universe_stock_map is not None and sym_clean not in universe_stock_map:
            raise ValueError(
                f"Candidate metadata symbol '{sym_clean}' at index {idx} does not exist in universe_stock_map."
            )

        meta_map[sym_clean] = item

    return meta_map


@dataclass
class PortfolioConfig:
    """Configuration for deterministic portfolio construction and backtesting.

    Parameters:
    - max_positions: Maximum number of positions allowed in the portfolio (default: 5). Must be int > 0 or None.
    - min_signal_score: Minimum signal score (0-100) required for candidate eligibility (default: 50.0).
    - min_confidence: Minimum confidence score (0.0-1.0) required for candidate eligibility (default: None).
    - allowed_actions: Tuple of stock recommendation actions eligible for portfolio entry (default: ("BUY",)).
    - max_weight_per_position: Maximum weight allocated to any single position in (0.0, 1.0] (default: None).
      Position weights are capped at max_weight_per_position without silent re-normalization or redistribution.
      Unallocated weight is preserved explicitly (allocated_weight + unallocated_weight == 1.0).
    - min_history: Minimum required historical sessions timestamped <= T for every stock in the universe (default: 50).
    - require_executable: If True, execution eligibility is enforced as a strict candidate selection constraint
      (stocks failing execution eligibility are excluded). If False, execution eligibility is evaluated if
      execution_config is present and attached to PortfolioPosition.is_executable, but does NOT exclude candidate securities.
    - execution_config: ExecutionConfig parameters used when require_executable is True or when evaluating eligibility.
    """

    max_positions: int | None = 5
    min_signal_score: float | None = 50.0
    min_confidence: float | None = None
    allowed_actions: tuple[str, ...] = ("BUY",)
    max_weight_per_position: float | None = None
    min_history: int = 50
    require_executable: bool = False
    execution_config: ExecutionConfig | None = None
    transaction_cost_pct: float = 0.0
    slippage_pct: float = 0.0

    def __post_init__(self) -> None:
        _validate_numeric_param(
            self.max_positions,
            "max_positions",
            min_val=1,
            allow_zero=True,
            strict_int=True,
        )
        _validate_numeric_param(
            self.min_history,
            "min_history",
            min_val=1,
            allow_zero=False,
            strict_int=True,
        )
        _validate_numeric_param(
            self.min_signal_score,
            "min_signal_score",
            min_val=0.0,
            max_val=100.0,
            allow_zero=True,
        )
        _validate_numeric_param(
            self.min_confidence,
            "min_confidence",
            min_val=0.0,
            max_val=1.0,
            allow_zero=True,
        )
        _validate_numeric_param(
            self.max_weight_per_position,
            "max_weight_per_position",
            min_val=0.0,
            max_val=1.0,
            allow_zero=False,
        )
        _validate_numeric_param(
            self.transaction_cost_pct,
            "transaction_cost_pct",
            min_val=0.0,
            max_val=1.0,
            allow_zero=True,
        )
        _validate_numeric_param(
            self.slippage_pct,
            "slippage_pct",
            min_val=0.0,
            max_val=1.0,
            allow_zero=True,
        )

        if not isinstance(self.require_executable, bool):
            raise TypeError(
                f"require_executable must be a boolean, got {type(self.require_executable).__name__}"
            )

        if not isinstance(self.allowed_actions, (list, tuple)):
            raise TypeError("allowed_actions must be a list or tuple of action strings.")

        if not self.allowed_actions:
            raise ValueError("allowed_actions cannot be empty.")

        for act in self.allowed_actions:
            if not isinstance(act, str) or not act.strip():
                raise ValueError(f"allowed_actions contains invalid action: {act}")


def validate_portfolio_weights(weights: list[float]) -> None:
    """Validate portfolio position weights deterministically, failing closed on violations.

    Validation Rules:
    - Each weight must be numeric, finite, non-negative.
    - Total allocated weight must not exceed 1.0 (with 1e-9 floating point tolerance).
    - Never silently normalize or adjust invalid weights.
    """
    if not isinstance(weights, list):
        raise TypeError(f"Weights must be a list, got {type(weights).__name__}")

    total_w = 0.0
    for idx, w in enumerate(weights):
        _validate_numeric_param(w, f"weight[{idx}]", min_val=0.0, max_val=1.0, allow_zero=True)
        total_w += float(w)

    total_w = round(total_w, 9)
    if total_w > 1.0 + 1e-9:
        raise ValueError(f"Total allocated portfolio weight exceeds 1.0: got {total_w}")


from copy import deepcopy


@dataclass
class PortfolioPosition:
    """Individual stock position held in the portfolio as of evaluation date T."""

    symbol: str
    weight: float
    action: str
    signal_score: float | None
    risk_adjusted_score: float | None
    confidence: float
    entry_price: float | None
    is_executable: bool | None
    forward_returns: dict[int, float | None] = field(default_factory=dict)
    forward_availability: dict[int, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "weight": self.weight,
            "action": self.action,
            "signal_score": self.signal_score,
            "risk_adjusted_score": self.risk_adjusted_score,
            "confidence": self.confidence,
            "entry_price": self.entry_price,
            "is_executable": self.is_executable,
            "forward_returns": dict(self.forward_returns),
            "forward_availability": dict(self.forward_availability),
        }


@dataclass
class PortfolioEvaluation:
    """Point-in-time portfolio construction and forward outcome result at evaluation date T."""

    evaluation_date: str
    positions: list[PortfolioPosition]
    allocated_weight: float
    unallocated_weight: float
    portfolio_forward_returns: dict[int, float | None]
    horizon_availability: dict[int, bool]
    excluded_non_executable: list[str] = field(default_factory=list)
    excluded_filtered: list[str] = field(default_factory=list)
    empty_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_date": self.evaluation_date,
            "positions": [p.to_dict() for p in self.positions],
            "allocated_weight": self.allocated_weight,
            "unallocated_weight": self.unallocated_weight,
            "portfolio_forward_returns": dict(self.portfolio_forward_returns),
            "horizon_availability": dict(self.horizon_availability),
            "excluded_non_executable": list(self.excluded_non_executable),
            "excluded_filtered": list(self.excluded_filtered),
            "empty_reason": self.empty_reason,
        }


@dataclass
class PortfolioBacktestResult:
    """Container for complete portfolio backtest across chronological evaluation dates."""

    evaluation_dates: list[str]
    evaluations: list[PortfolioEvaluation]
    config: PortfolioConfig
    aggregate: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_dates": list(self.evaluation_dates),
            "evaluations": [e.to_dict() for e in self.evaluations],
            "config": {
                "max_positions": self.config.max_positions,
                "min_signal_score": self.config.min_signal_score,
                "min_confidence": self.config.min_confidence,
                "allowed_actions": list(self.config.allowed_actions),
                "max_weight_per_position": self.config.max_weight_per_position,
                "min_history": self.config.min_history,
                "require_executable": self.config.require_executable,
                "transaction_cost_pct": self.config.transaction_cost_pct,
                "slippage_pct": self.config.slippage_pct,
            },
            "aggregate": deepcopy(self.aggregate),
        }


def evaluate_portfolio_at_date(
    evaluation_date: str,
    universe_stock_map: dict[str, pd.DataFrame],
    config: PortfolioConfig | None = None,
    candidate_metadata: list[dict] | None = None,
    df_vnindex: pd.DataFrame | None = None,
    df_vn30: pd.DataFrame | None = None,
    horizons: list[int] | None = None,
) -> PortfolioEvaluation:
    """Evaluate point-in-time portfolio construction at evaluation date T and measure forward performance.

    Temporal & No-Lookahead Contract:
    - Slices all stock datasets and market benchmark inputs strictly <= T via `get_as_of_dataset()`.
    - Generates signals and recommendations at T using production recommendation engine.
    - Applies execution eligibility if `config.require_executable` is True or execution_config is present.
    - Evaluates forward outcomes using data strictly > T via `evaluate_forward_outcomes()`.

    Deterministic Selection & Weight Allocation:
    1. Filter eligible universe candidates (action in allowed_actions, signal_score >= min_signal_score, confidence >= min_confidence).
    2. Exclude non-executable securities if `config.require_executable` is True.
    3. Rank candidates deterministically using tie-breaker:
       `(-signal_score, -risk_adjusted_score, -confidence, symbol)`.
    4. Limit positions up to `config.max_positions`.
    5. Allocate weights equally (`1 / count`), subject to optional `max_weight_per_position`.
    6. Validate weights via `validate_portfolio_weights()`.
    7. Calculate portfolio forward return: `Σ(w_i × r_i)` for each horizon.
    """
    if config is None:
        config = PortfolioConfig()

    if horizons is None:
        horizons = DEFAULT_HORIZONS

    if not universe_stock_map:
        raise ValueError("universe_stock_map cannot be empty or None.")

    target_date_str = _parse_canonical_date(evaluation_date)

    # 1. Fail-closed point-in-time and min_history validation for EVERY stock in universe
    df_stock_as_of_map: dict[str, pd.DataFrame] = {}
    for sym in sorted(universe_stock_map.keys()):
        df_s = universe_stock_map[sym]
        if df_s is None:
            raise ValueError(f"Stock '{sym}' dataset cannot be None in universe_stock_map.")
        if df_s.empty:
            raise ValueError(f"Stock '{sym}' dataset cannot be empty in universe_stock_map.")

        df_as_of = get_as_of_dataset(df_s, target_date_str)
        avail_sessions = len(df_as_of)
        if avail_sessions < config.min_history:
            raise ValueError(
                f"Stock '{sym}' on evaluation date '{target_date_str}' has insufficient history "
                f"({avail_sessions} sessions) for min_history requirement ({config.min_history})."
            )
        df_stock_as_of_map[sym] = df_as_of

    # 1. Point-in-time market data slicing <= T
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

    breadth_ratio = calculate_as_of_market_breadth(universe_stock_map, target_date_str)

    from scripts.lib.regime import detect_market_regime

    market_regime_info = detect_market_regime(
        df_vnindex=df_vnindex_clean_as_of,
        df_vn30=df_vn30_clean_as_of,
        breadth_ratio=breadth_ratio,
    )

    meta_map = _build_candidate_meta_map(candidate_metadata, universe_stock_map)

    # 2. Evaluate signals and execution eligibility for all universe stocks at T
    candidates: list[dict[str, Any]] = []
    excluded_filtered: list[str] = []
    excluded_non_executable: list[str] = []

    for sym in sorted(universe_stock_map.keys()):
        df_stock = universe_stock_map[sym]
        df_stock_as_of = df_stock_as_of_map[sym]

        item = meta_map.get(sym, {})
        comp = item.get("companyName", "")
        sec = item.get("sector", "")
        ex = item.get("exchange", "HOSE")

        rec = generate_recommendation(
            symbol=sym,
            company_name=comp,
            sector=sec,
            exchange=ex,
            df_stock=df_stock_as_of,
            market_regime_info=market_regime_info,
            df_vnindex=df_vnindex_clean_as_of,
            data_as_of=target_date_str,
        )

        act = rec["action"]
        sig_score = _safe_float(rec["signal_score"])
        risk_adj_score = _safe_float(rec["risk_adjusted_score"])
        conf = float(rec["confidence"])
        entry_p = _safe_float(rec["trade_plan"].get("current_price"))

        exec_elig = None
        if config.require_executable or config.execution_config is not None:
            exec_elig = evaluate_execution_eligibility(
                df_stock=df_stock_as_of,
                evaluation_date=target_date_str,
                config=config.execution_config,
            )

        # Check action eligibility
        if act not in config.allowed_actions:
            excluded_filtered.append(sym)
            continue

        # Check min signal score threshold
        if config.min_signal_score is not None and (
            sig_score is None or sig_score < config.min_signal_score
        ):
            excluded_filtered.append(sym)
            continue

        # Check min confidence threshold
        if config.min_confidence is not None and conf < config.min_confidence:
            excluded_filtered.append(sym)
            continue

        # Check execution eligibility if require_executable is True
        if config.require_executable and (exec_elig is None or not exec_elig.is_executable):
            excluded_non_executable.append(sym)
            continue

        is_exec = exec_elig.is_executable if exec_elig is not None else None

        candidates.append(
            {
                "symbol": sym,
                "df_stock": df_stock,
                "action": act,
                "signal_score": sig_score,
                "risk_adjusted_score": risk_adj_score,
                "confidence": conf,
                "entry_price": entry_p,
                "is_executable": is_exec,
            }
        )

    # Handle empty portfolio scenario
    if not candidates:
        empty_reason = (
            "all_candidates_non_executable"
            if excluded_non_executable and not candidates
            else "no_eligible_candidates"
        )
        return PortfolioEvaluation(
            evaluation_date=target_date_str,
            positions=[],
            allocated_weight=0.0,
            unallocated_weight=1.0,
            portfolio_forward_returns={h: None for h in horizons},
            horizon_availability={h: False for h in horizons},
            excluded_non_executable=sorted(excluded_non_executable),
            excluded_filtered=sorted(excluded_filtered),
            empty_reason=empty_reason,
        )

    # 3. Deterministic ranking & tie-breaking
    # Sort key: (-signal_score, -risk_adjusted_score, -confidence, symbol)
    def rank_key(cand: dict[str, Any]) -> tuple:
        s_score = cand["signal_score"] if cand["signal_score"] is not None else -1e9
        r_score = cand["risk_adjusted_score"] if cand["risk_adjusted_score"] is not None else -1e9
        return (-s_score, -r_score, -cand["confidence"], cand["symbol"])

    sorted_candidates = sorted(candidates, key=rank_key)

    # Limit positions to max_positions
    if config.max_positions is not None and len(sorted_candidates) > config.max_positions:
        selected_candidates = sorted_candidates[: config.max_positions]
    else:
        selected_candidates = sorted_candidates

    num_selected = len(selected_candidates)

    # 4. Deterministic Equal Weighting & Constraints
    raw_weight = 1.0 / num_selected
    if config.max_weight_per_position is not None and raw_weight > config.max_weight_per_position:
        pos_weight = round(config.max_weight_per_position, 6)
    else:
        pos_weight = round(raw_weight, 6)

    weights = [pos_weight] * num_selected
    validate_portfolio_weights(weights)

    allocated_w = round(sum(weights), 6)
    unallocated_w = round(1.0 - allocated_w, 6)

    # 5. Evaluate forward outcomes for selected constituent positions
    positions: list[PortfolioPosition] = []

    for cand, w in zip(selected_candidates, weights, strict=True):
        sym = cand["symbol"]
        df_stock = cand["df_stock"]

        outcome = evaluate_forward_outcomes(
            df_stock=df_stock,
            evaluation_date=target_date_str,
            horizons=horizons,
            action=cand["action"],
        )

        # Apply cost and slippage adjustments action-aware
        adjusted_returns: dict[int, float | None] = {}
        p_entry = cand["entry_price"]
        action = cand["action"]

        for h in horizons:
            strat_ret = outcome.strategy_returns.get(h)
            if strat_ret is not None and p_entry is not None and p_entry > 0:
                if action == "BUY":
                    p_exit = p_entry * (1.0 + strat_ret)
                elif action == "SELL":
                    p_exit = p_entry * (1.0 - strat_ret)
                else:
                    p_exit = p_entry

                exec_res = calculate_execution_return(
                    entry_price=p_entry,
                    exit_price=p_exit,
                    transaction_cost_pct=config.transaction_cost_pct,
                    slippage_pct=config.slippage_pct,
                    action=action,
                )
                adjusted_returns[h] = exec_res.net_return
            else:
                adjusted_returns[h] = None

        pos = PortfolioPosition(
            symbol=sym,
            weight=w,
            action=cand["action"],
            signal_score=cand["signal_score"],
            risk_adjusted_score=cand["risk_adjusted_score"],
            confidence=cand["confidence"],
            entry_price=cand["entry_price"],
            is_executable=cand["is_executable"],
            forward_returns=adjusted_returns,
            forward_availability=outcome.availability,
        )
        positions.append(pos)

    # 6. Aggregate portfolio forward returns across selected positions
    portfolio_fwd_returns: dict[int, float | None] = {}
    horizon_avail: dict[int, bool] = {}

    for h in horizons:
        # If ANY selected stock lacks forward return at horizon h, portfolio outcome is unavailable
        all_avail = all(p.forward_availability.get(h, False) for p in positions)
        if not all_avail:
            portfolio_fwd_returns[h] = None
            horizon_avail[h] = False
        else:
            weighted_ret = sum(
                p.weight * p.forward_returns[h]
                for p in positions
                if p.forward_returns.get(h) is not None
            )
            portfolio_fwd_returns[h] = round(float(weighted_ret), 6)
            horizon_avail[h] = True

    return PortfolioEvaluation(
        evaluation_date=target_date_str,
        positions=positions,
        allocated_weight=allocated_w,
        unallocated_weight=unallocated_w,
        portfolio_forward_returns=portfolio_fwd_returns,
        horizon_availability=horizon_avail,
        excluded_non_executable=sorted(excluded_non_executable),
        excluded_filtered=sorted(excluded_filtered),
        empty_reason=None,
    )


def aggregate_portfolio_results(
    evaluations: list[PortfolioEvaluation], horizons: list[int] | None = None
) -> dict[str, Any]:
    """Calculate aggregated descriptive summary metrics across historical portfolio evaluation dates.

    Metrics Provided:
    - total_evaluation_points: number of evaluation dates evaluated
    - non_empty_portfolios_count: number of evaluation points with active positions (> 0 positions)
    - empty_portfolios_count: number of evaluation points with no qualified positions
    - empty_reasons_breakdown: counts of empty portfolio reasons
    - horizon_metrics: summary return statistics per horizon (mean, median, std, min, max, hit_rate, sequential_compounded_return)

    Methodology & Disclaimer:
    - Sequential compounded return (`sequential_compounded_return`) is calculated across sequential valid
      non-empty evaluation points:
        sequential_compounded_return = ∏(1 + r_i) - 1.0
    - This metric is strictly diagnostic for historical descriptive comparison. It is NOT an equity curve,
      realized account return, or non-overlapping investment-period return.
    - Overlapping forward-return windows may exist across evaluation points when evaluation dates are closer
      together than the forward horizon, so this metric must NOT be interpreted as compounded live or realized portfolio performance.
    """
    if horizons is None:
        horizons = DEFAULT_HORIZONS

    total_points = len(evaluations)
    non_empty_evals = [e for e in evaluations if len(e.positions) > 0]
    empty_evals = [e for e in evaluations if len(e.positions) == 0]

    empty_reasons: dict[str, int] = {}
    for e in empty_evals:
        r = e.empty_reason or "unknown"
        empty_reasons[r] = empty_reasons.get(r, 0) + 1

    horizon_metrics: dict[int, dict[str, Any]] = {}

    for h in horizons:
        valid_returns: list[float] = []

        for e in non_empty_evals:
            if e.horizon_availability.get(h, False):
                ret = e.portfolio_forward_returns.get(h)
                if ret is not None:
                    valid_returns.append(ret)

        num_valid = len(valid_returns)
        if num_valid > 0:
            arr = np.array(valid_returns, dtype=float)
            mean_ret = round(float(np.mean(arr)), 6)
            median_ret = round(float(np.median(arr)), 6)
            std_ret = round(float(np.std(arr)), 6) if num_valid > 1 else 0.0
            min_ret = round(float(np.min(arr)), 6)
            max_ret = round(float(np.max(arr)), 6)

            positive_count = sum(1 for r in valid_returns if r > 0)
            hit_rate = round(positive_count / num_valid, 4)

            # Sequential compounding: ∏(1 + r_i) - 1
            cum_factor = 1.0
            for r in valid_returns:
                cum_factor *= 1.0 + r
            seq_compounded_return = round(cum_factor - 1.0, 6)
        else:
            mean_ret = None
            median_ret = None
            std_ret = None
            min_ret = None
            max_ret = None
            hit_rate = None
            seq_compounded_return = None

        horizon_metrics[h] = {
            "valid_evaluation_points": num_valid,
            "mean": mean_ret,
            "median": median_ret,
            "std": std_ret,
            "min": min_ret,
            "max": max_ret,
            "hit_rate": hit_rate,
            "sequential_compounded_return": seq_compounded_return,
        }

    return {
        "total_evaluation_points": total_points,
        "non_empty_portfolios_count": len(non_empty_evals),
        "empty_portfolios_count": len(empty_evals),
        "empty_reasons_breakdown": empty_reasons,
        "horizon_metrics": horizon_metrics,
    }


def run_portfolio_backtest(
    evaluation_dates: list[str],
    universe_stock_map: dict[str, pd.DataFrame],
    config: PortfolioConfig | None = None,
    candidate_metadata: list[dict] | None = None,
    df_vnindex: pd.DataFrame | None = None,
    df_vn30: pd.DataFrame | None = None,
    horizons: list[int] | None = None,
) -> PortfolioBacktestResult:
    """Run point-in-time deterministic portfolio backtest across a sequence of evaluation dates.

    Temporal Integrity & Fail-Closed Validation:
    - evaluation_dates must be non-empty, chronologically sorted, unique YYYY-MM-DD strings.
    - Slices all market inputs and stock datasets strictly <= T before candidate evaluation.
    - Aggregates portfolio evaluations into descriptive metrics.
    """
    if config is None:
        config = PortfolioConfig()

    if horizons is None:
        horizons = DEFAULT_HORIZONS

    if not evaluation_dates:
        raise ValueError("evaluation_dates list cannot be empty.")

    # Validate date strings and chronological sorting
    parsed_eval_dates = []
    for d in evaluation_dates:
        parsed_eval_dates.append(_parse_canonical_date(d))

    if len(parsed_eval_dates) != len(set(parsed_eval_dates)):
        raise ValueError("evaluation_dates list contains duplicate entries.")

    if sorted(parsed_eval_dates) != parsed_eval_dates:
        raise ValueError("evaluation_dates list is not sorted in chronological order.")

    evaluations: list[PortfolioEvaluation] = []

    for eval_d in parsed_eval_dates:
        eval_res = evaluate_portfolio_at_date(
            evaluation_date=eval_d,
            universe_stock_map=universe_stock_map,
            config=config,
            candidate_metadata=candidate_metadata,
            df_vnindex=df_vnindex,
            df_vn30=df_vn30,
            horizons=horizons,
        )
        evaluations.append(eval_res)

    aggregate_summary = aggregate_portfolio_results(evaluations, horizons=horizons)

    return PortfolioBacktestResult(
        evaluation_dates=parsed_eval_dates,
        evaluations=evaluations,
        config=config,
        aggregate=aggregate_summary,
    )
